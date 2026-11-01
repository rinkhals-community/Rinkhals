import copy
import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "files/4-apps/home/rinkhals/apps/40-moonraker/kobra.py"
)
MODULE_NAME = "testsupport.moonraker.components.kobra"
COMMON_NAME = "testsupport.moonraker.common"
UTILS_NAME = "testsupport.moonraker.utils"
POWER_NAME = "testsupport.moonraker.components.power"
MACHINE_NAME = "testsupport.moonraker.components.machine"
KLIPPY_CONNECTION_NAME = "testsupport.moonraker.components.klippy_connection"


class DummyTask:
    def __init__(self, coro):
        self._coro = coro
        coro.close()

    def cancel(self):
        return None

    def done(self):
        return True


class DummyEventLoop:
    def create_task(self, coro):
        return DummyTask(coro)


class DummyServer:
    error = RuntimeError

    def __init__(self):
        self._eventloop = DummyEventLoop()
        self.config = object()

    def get_event_loop(self):
        return self._eventloop

    def load_component(self, *args, **kwargs):
        return None


class DummyWebRequest:
    def __init__(self, endpoint: str, args=None):
        self.endpoint = endpoint
        self._args = args or {}

    def get_endpoint(self):
        return self.endpoint

    def get_args(self):
        return self._args


def _ensure_package(name: str):
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package
    return sys.modules[name]


def _build_machine_module():
    machine_module = types.ModuleType(MACHINE_NAME)

    class Machine:
        def __init__(self):
            self.inside_container = False
            self.system_info = {"virtualization": {"virt_identifier": "none"}}
            self.server = DummyServer()
            self.original_calls = []

        async def exec_sudo_command(self, command: str):
            self.original_calls.append(command)
            return f"original:{command}"

        async def _handle_machine_request(self, web_request):
            endpoint = web_request.get_endpoint()
            virt_id = self.system_info.get("virtualization", {}).get("virt_identifier", "none")
            if endpoint == "/machine/reboot":
                if self.inside_container:
                    raise self.server.error(f"Cannot reboot from within a {virt_id} container")
                await self.exec_sudo_command("systemctl reboot")
                return "ok"
            elif endpoint == "/machine/shutdown":
                if self.inside_container:
                    raise self.server.error(f"Cannot shutdown from within a {virt_id} container")
                await self.exec_sudo_command("systemctl poweroff")
                return "ok"
            else:
                self.original_calls.append(endpoint)
                return f"original:{endpoint}"

    machine_module.Machine = Machine
    sys.modules[MACHINE_NAME] = machine_module
    return machine_module


def _build_klippy_connection_module():
    klippy_connection_module = types.ModuleType(KLIPPY_CONNECTION_NAME)

    class KlippyConnection:
        def __init__(self, available_heaters=None, heater_error=None):
            self.available_heaters = available_heaters or []
            self.heater_error = heater_error
            self.requests = []

        async def request(self, web_request):
            endpoint = web_request.get_endpoint()
            self.requests.append((endpoint, copy.deepcopy(web_request.get_args())))

            if endpoint == "gcode/help":
                return {"TEST_MACRO": "test"}
            if endpoint == "objects/query":
                if self.heater_error is not None:
                    raise self.heater_error
                return {
                    "status": {
                        "heaters": {
                            "available_heaters": self.available_heaters,
                        }
                    }
                }
            return {"original": endpoint}

        # patch_objects_list wraps _request_standard too (MMU stripping), so the
        # fake must expose it even for tests that only exercise objects/list.
        @staticmethod
        async def _request_standard(me, web_request, timeout=None):
            return {"status": {}}

    class KlippyRequest:
        @staticmethod
        def set_result(me, result):
            pass

    klippy_connection_module.KlippyConnection = KlippyConnection
    klippy_connection_module.KlippyRequest = KlippyRequest
    sys.modules[KLIPPY_CONNECTION_NAME] = klippy_connection_module
    return klippy_connection_module


class FakeObjectsWebRequest:
    def __init__(self, endpoint: str, args: dict):
        self._endpoint = endpoint
        self._args = args

    def get_endpoint(self):
        return self._endpoint

    def get_args(self):
        return self._args


def load_kobra_module():
    if MODULE_NAME in sys.modules:
        return sys.modules[MODULE_NAME]

    _ensure_package("testsupport")
    _ensure_package("testsupport.moonraker")
    _ensure_package("testsupport.moonraker.components")
    _ensure_package("paho")
    _ensure_package("paho.mqtt")

    client_module = types.ModuleType("paho.mqtt.client")
    client_module.Client = type("Client", (), {})
    sys.modules["paho.mqtt.client"] = client_module

    common_module = types.ModuleType(COMMON_NAME)
    common_module.WebRequest = DummyWebRequest
    sys.modules[COMMON_NAME] = common_module

    utils_module = types.ModuleType(UTILS_NAME)
    utils_module.Sentinel = types.SimpleNamespace(MISSING=object())
    sys.modules[UTILS_NAME] = utils_module

    power_module = types.ModuleType(POWER_NAME)
    power_module.PowerDevice = type("PowerDevice", (), {})
    sys.modules[POWER_NAME] = power_module

    _build_machine_module()

    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class KobraMachineRebootPatchTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def setUp(self):
        self.machine_module = _build_machine_module()
        self.kobra = self.module.Kobra.__new__(self.module.Kobra)
        self.kobra.server = DummyServer()
        self.kobra.patch_machine_power_actions()

    async def test_reboot_request_is_intercepted_and_scheduled(self):
        scheduled = []
        self.kobra._schedule_native_machine_action = lambda action: scheduled.append(action)

        machine = self.machine_module.Machine()
        result = await machine._handle_machine_request(DummyWebRequest("/machine/reboot"))

        self.assertEqual(result, "ok")
        self.assertEqual(scheduled, ["reboot"])
        self.assertEqual(machine.original_calls, [])

    async def test_shutdown_request_is_intercepted_and_scheduled(self):
        scheduled = []
        self.kobra._schedule_native_machine_action = lambda action: scheduled.append(action)

        machine = self.machine_module.Machine()
        result = await machine._handle_machine_request(DummyWebRequest("/machine/shutdown"))

        self.assertEqual(result, "ok")
        self.assertEqual(scheduled, ["poweroff"])
        self.assertEqual(machine.original_calls, [])

    async def test_non_power_request_falls_back_to_original_handler(self):
        scheduled = []
        self.kobra._schedule_native_machine_action = lambda action: scheduled.append(action)

        machine = self.machine_module.Machine()
        result = await machine._handle_machine_request(DummyWebRequest("/machine/restart"))

        self.assertEqual(result, "original:/machine/restart")
        self.assertEqual(scheduled, [])
        self.assertEqual(machine.original_calls, ["/machine/restart"])

    async def test_reboot_request_preserves_container_guard(self):
        scheduled = []
        self.kobra._schedule_native_machine_action = lambda action: scheduled.append(action)

        machine = self.machine_module.Machine()
        machine.inside_container = True
        machine.system_info["virtualization"]["virt_identifier"] = "docker"

        with self.assertRaisesRegex(RuntimeError, "Cannot reboot from within a docker container"):
            await machine._handle_machine_request(DummyWebRequest("/machine/reboot"))

        self.assertEqual(scheduled, [])
        self.assertEqual(machine.original_calls, [])


class KobraEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    @mock.patch.object(
        load_kobra_module().subprocess,
        "check_output",
        return_value=b"20029|KS1M|2.7.1.4|device-id\n",
    )
    def test_reads_firmware_version_from_tools(self, _check_output):
        self.assertEqual(
            self.module._read_env_from_tools(),
            {
                "KOBRA_MODEL_ID": "20029",
                "KOBRA_MODEL_CODE": "KS1M",
                "KOBRA_VERSION": "2.7.1.4",
                "KOBRA_DEVICE_ID": "device-id",
            },
        )


class KobraObjectsListPatchTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def setUp(self):
        self.klippy_connection_module = _build_klippy_connection_module()
        self.kobra = self.module.Kobra.__new__(self.module.Kobra)
        self.kobra.is_goklipper_running = lambda: True

    async def _objects_for(self, model, version, available_heaters=None, heater_error=None):
        self.kobra.KOBRA_MODEL_CODE = model
        self.kobra.KOBRA_VERSION = version
        self.kobra.patch_objects_list()
        connection = self.klippy_connection_module.KlippyConnection(
            available_heaters=available_heaters,
            heater_error=heater_error,
        )
        result = await connection.request(DummyWebRequest("objects/list"))
        return result["objects"], connection.requests

    async def test_ks1_without_reported_chamber_does_not_expose_it(self):
        objects, requests = await self._objects_for(
            "KS1",
            "2.7.2.7",
            available_heaters=["heater_bed", "extruder"],
        )

        self.assertNotIn("chamber_temp", objects)
        self.assertNotIn("controller_fan controller_fan", objects)
        self.assertEqual(
            requests[-1],
            (
                "objects/query",
                {"objects": {"heaters": ["available_heaters"]}},
            ),
        )

    async def test_other_model_exposes_chamber_when_reported(self):
        objects, _requests = await self._objects_for(
            "K3",
            "2.4.6.7",
            available_heaters=["heater_bed", "chamber_temp", "extruder"],
        )

        self.assertIn("chamber_temp", objects)

    async def test_verified_ks1m_exposes_reported_chamber_and_fans(self):
        objects, _requests = await self._objects_for(
            "KS1M",
            "2.7.1.4",
            available_heaters=["heater_bed", "chamber_temp", "extruder"],
        )

        self.assertIn("chamber_temp", objects)
        self.assertIn("fan_generic chamber_fan", objects)
        self.assertIn("fan_generic exhaust_fan", objects)
        self.assertIn("controller_fan controller_fan", objects)

    async def test_older_ks1m_exposes_reported_chamber_but_not_unverified_fans(self):
        objects, _requests = await self._objects_for(
            "KS1M",
            "2.6.9.3",
            available_heaters=["heater_bed", "chamber_temp", "extruder"],
        )

        self.assertIn("chamber_temp", objects)
        self.assertNotIn("fan_generic chamber_fan", objects)
        self.assertNotIn("fan_generic exhaust_fan", objects)
        self.assertNotIn("controller_fan controller_fan", objects)

    async def test_heater_discovery_failure_does_not_advertise_chamber(self):
        objects, _requests = await self._objects_for(
            "KS1M",
            "2.7.1.4",
            heater_error=RuntimeError("query failed"),
        )

        self.assertNotIn("chamber_temp", objects)


class KobraMmuObjectStrippingTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def setUp(self):
        self.klippy_connection_module = _build_klippy_connection_module()
        self.kobra = self.module.Kobra.__new__(self.module.Kobra)
        # Cache is valid for the next 100s, so is_goklipper_running()
        # short-circuits on the cached PID without scanning /proc.
        self.kobra._goklipper_next_check = time.time() + 100

    async def _install_fake_and_patch(self, goklipper_pid):
        self.kobra._goklipper_pid = goklipper_pid

        captured = {}

        async def fake_request_standard(me, web_request, timeout=None):
            captured['objects'] = dict(web_request.get_args()['objects'])
            return {"status": {}}

        self.klippy_connection_module.KlippyConnection._request_standard = fake_request_standard
        self.kobra.patch_objects_list()
        return captured

    async def test_mmu_and_mmu_machine_stripped_when_goklipper_running(self):
        captured = await self._install_fake_and_patch(goklipper_pid=12345)

        web_request = FakeObjectsWebRequest(
            "objects/subscribe",
            {"objects": {"mmu": None, "mmu_machine": None, "toolhead": None}},
        )
        result = await self.klippy_connection_module.KlippyConnection._request_standard(
            None, web_request
        )

        self.assertNotIn('mmu', captured['objects'])
        self.assertNotIn('mmu_machine', captured['objects'])
        self.assertIn('toolhead', captured['objects'])
        self.assertEqual(result, {"status": {}})

    async def test_mmu_objects_not_stripped_when_goklipper_not_running(self):
        captured = await self._install_fake_and_patch(goklipper_pid=None)

        web_request = FakeObjectsWebRequest(
            "objects/subscribe",
            {"objects": {"mmu": None, "mmu_machine": None}},
        )
        await self.klippy_connection_module.KlippyConnection._request_standard(None, web_request)

        self.assertIn('mmu', captured['objects'])
        self.assertIn('mmu_machine', captured['objects'])

    async def test_mmu_objects_not_stripped_for_unrelated_endpoint(self):
        captured = await self._install_fake_and_patch(goklipper_pid=12345)

        web_request = FakeObjectsWebRequest(
            "some/other/endpoint",
            {"objects": {"mmu": None}},
        )
        await self.klippy_connection_module.KlippyConnection._request_standard(None, web_request)

        self.assertIn('mmu', captured['objects'])


class KobraStatusPatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def setUp(self):
        self.kobra = self.module.Kobra.__new__(self.module.Kobra)
        # Kobra.status_patchers is a mutable CLASS-level default list;
        # shadow it with a fresh instance list so this test doesn't
        # leak patchers into other tests/instances.
        self.kobra.status_patchers = []

    def test_registered_patcher_receives_status_and_is_subscription_update(self):
        received = []

        def patcher(status, is_subscription_update, requested):
            received.append((status, is_subscription_update, requested))
            return status

        self.kobra.register_status_patcher(patcher)
        self.kobra.patch_status({"foo": "bar"}, is_subscription_update=True)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], {"foo": "bar"})
        self.assertIs(received[0][1], True)
        # No request context: None means "caller does not know".
        self.assertIsNone(received[0][2])

    def test_patch_status_forwards_requested_objects(self):
        received = []
        self.kobra.register_status_patcher(
            lambda status, is_sub, requested: (received.append(requested), status)[1]
        )

        self.kobra.patch_status({}, requested={"print_stats"})
        self.kobra.patch_status({}, requested=())

        self.assertEqual(received, [{"print_stats"}, ()])

    def test_patch_status_defaults_is_subscription_update_to_false(self):
        received = []
        self.kobra.register_status_patcher(
            lambda status, is_sub, requested: (received.append(is_sub), status)[1]
        )

        self.kobra.patch_status({})

        self.assertEqual(received, [False])


class CountingGcodeFile:
    """Stands in for an open gcode file and counts how many lines were read."""

    def __init__(self, lines):
        self.lines = lines
        self.lines_read = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for line in self.lines:
            self.lines_read += 1
            yield line


class KobraExcludeObjectScanTests(unittest.TestCase):
    """Looking up exclude_object definitions must not read a whole gcode file (#111)."""

    FILE = 'Head+v4+plate_PETG_0.2_15h0m.gcode'
    HEADER = ['; generated by OrcaSlicer 2.4.0\n', '; HEADER_BLOCK_END\n', 'M190 S60\n']
    BODY = ['G1 X10 Y10 E0.5\n'] * 1000

    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def setUp(self):
        self.kobra = self.module.Kobra.__new__(self.module.Kobra)
        self.kobra.status_patchers = []
        self.kobra.is_goklipper_running = lambda: True
        self.kobra._maybe_force_end_excluded_object = lambda status: None
        self.opened = []

    def _scan(self, lines):
        self.gcode = CountingGcodeFile(lines)

        def fake_open(path, *args, **kwargs):
            self.opened.append(path)
            return self.gcode

        isfile = mock.patch.object(self.module.os.path, 'isfile', return_value=True)
        opener = mock.patch('builtins.open', fake_open)
        return isfile, opener

    def _objects(self, lines):
        isfile, opener = self._scan(lines)
        with isfile, opener:
            self.kobra._set_exclude_object_file(self.FILE)
            return self.kobra._get_exclude_object_objects()

    def test_unlabeled_file_is_read_only_up_to_the_first_layer(self):
        lines = self.HEADER + [';LAYER_CHANGE\n', ';Z:0.2\n'] + self.BODY

        self.assertEqual(self._objects(lines), [])
        self.assertEqual(self.gcode.lines_read, len(self.HEADER) + 1)

    def test_cura_layer_marker_also_stops_the_scan(self):
        lines = self.HEADER + [';LAYER:0\n'] + self.BODY

        self.assertEqual(self._objects(lines), [])
        self.assertEqual(self.gcode.lines_read, len(self.HEADER) + 1)

    def test_file_without_layer_markers_stops_at_the_line_cap(self):
        cap = self.module.Kobra.EXCLUDE_OBJECT_SCAN_MAX_LINES
        lines = self.HEADER + ['G1 X10 Y10 E0.5\n'] * (cap + 1000)

        self.assertEqual(self._objects(lines), [])
        self.assertEqual(self.gcode.lines_read, cap + 1)

    def test_definitions_in_the_header_are_still_found(self):
        lines = self.HEADER + [
            'EXCLUDE_OBJECT_DEFINE NAME=cube_id_0_copy_0 CENTER=128,128 POLYGON=[[118,118],[138,118],[138,138],[118,138]]\n',
            'EXCLUDE_OBJECT_DEFINE NAME="spinner 2" CENTER=60.5,70\n',
            ';LAYER_CHANGE\n',
            'EXCLUDE_OBJECT_START NAME=cube_id_0_copy_0\n',
        ] + self.BODY

        objects = self._objects(lines)

        self.assertEqual(objects, [
            {'name': 'cube_id_0_copy_0', 'center': [128.0, 128.0],
             'polygon': [[118, 118], [138, 118], [138, 138], [118, 138]]},
            {'name': 'spinner 2', 'center': [60.5, 70.0]},
        ])
        self.assertEqual(self.gcode.lines_read, len(self.HEADER) + 3)

    def test_gcodes_directory_alone_does_not_replace_the_tracked_file(self):
        self._objects(self.HEADER + [';LAYER_CHANGE\n'])

        self.kobra._set_exclude_object_file('/useremain/app/gk/gcodes/')

        self.assertEqual(self.kobra._exclude_object_current_file, self.FILE)
        self.assertEqual(self.kobra._exclude_object_objects, [])

    def test_mainsail_reconnects_after_a_print_read_the_file_once(self):
        # Every reconnect in the #111 log: print_stats still names the last file
        # while virtual_sdcard.file_path is just the gcodes directory
        reconnect = [
            {
                'print_stats': {'filename': self.FILE},
                'virtual_sdcard': {'file_path': '/useremain/app/gk/gcodes/'},
                'exclude_object': {'objects': [], 'excluded_objects': [], 'current_object': None},
            },
            {
                'print_stats': {'filename': self.FILE},
                'exclude_object': {'objects': [], 'excluded_objects': [], 'current_object': None},
            },
        ]

        isfile, opener = self._scan(self.HEADER + [';LAYER_CHANGE\n'] + self.BODY)
        with isfile, opener:
            for _ in range(5):
                for status in copy.deepcopy(reconnect):
                    self.kobra.patch_status(status, is_subscription_update=True)

        self.assertEqual(len(self.opened), 1)


class KobraRequestedObjectsTests(unittest.IsolatedAsyncioTestCase):
    """objects/query must return only what was asked for (issue #140)."""

    PANDA = {"webhooks": None, "virtual_sdcard": None, "print_stats": None,
             "extruder": None, "heater_bed": None, "gcode_macro _KNOMI_STATUS": None}

    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def setUp(self):
        self.connection_module = _build_klippy_connection_module()
        self.kobra = self.module.Kobra.__new__(self.module.Kobra)
        self.kobra.status_patchers = []

        # Behaves like MmuAcePatcher: adds mmu objects only when asked.
        def mmu_patcher(status, is_sub, requested):
            for name in ("mmu", "mmu_machine"):
                if requested is None or name in requested:
                    status[name] = {"from": "patcher"}
            return status
        self.kobra.register_status_patcher(mmu_patcher)

    async def _call(self, endpoint, objects, inner):
        self.connection_module.KlippyConnection.request = inner
        self.kobra.patch_requested_objects()
        conn = self.connection_module.KlippyConnection()
        request = FakeObjectsWebRequest(endpoint, {"objects": dict(objects)})
        return await self.connection_module.KlippyConnection.request(conn, request)

    @staticmethod
    def _inner_returning(extra):
        async def inner(me, web_request):
            names = list(web_request.get_args().get("objects", {}))
            status = {name: {} for name in names}
            status.update(extra)
            return {"status": status, "eventtime": 1.0}
        return inner

    async def test_query_drops_objects_the_client_did_not_ask_for(self):
        inner = self._inner_returning({"idle_timeout": {"state": "printing"}})
        result = await self._call("objects/query", self.PANDA, inner)

        self.assertEqual(set(result["status"]), set(self.PANDA))
        self.assertNotIn("idle_timeout", result["status"])
        self.assertNotIn("mmu", result["status"])
        self.assertNotIn("mmu_machine", result["status"])

    async def test_query_still_returns_mmu_when_requested(self):
        inner = self._inner_returning({})
        result = await self._call("objects/query", {"mmu": None, "print_stats": None}, inner)

        self.assertEqual(result["status"]["mmu"], {"from": "patcher"})
        self.assertNotIn("mmu_machine", result["status"])

    async def test_requested_names_are_captured_before_inner_patches_edit_them(self):
        # patch_bed_mesh deletes bed_mesh from the request before gklib sees
        # it and adds it back to the result. Pruning against the edited list
        # would throw the heightmap away.
        async def inner(me, web_request):
            del web_request.get_args()["objects"]["bed_mesh"]
            return {"status": {"bed_mesh": {"profile_name": "default"}, "print_stats": {}}}

        result = await self._call("objects/query", {"bed_mesh": None, "print_stats": None}, inner)
        self.assertEqual(result["status"]["bed_mesh"], {"profile_name": "default"})

    async def test_subscribe_is_not_pruned_but_mmu_still_needs_requesting(self):
        inner = self._inner_returning({"idle_timeout": {"state": "printing"}})

        plain = await self._call("objects/subscribe", {"print_stats": None}, inner)
        self.assertIn("idle_timeout", plain["status"])
        self.assertNotIn("mmu", plain["status"])

        with_mmu = await self._call("objects/subscribe", {"print_stats": None, "mmu": None}, inner)
        self.assertEqual(with_mmu["status"]["mmu"], {"from": "patcher"})

    async def test_other_endpoints_are_left_untouched(self):
        async def inner(me, web_request):
            return {"status": {"anything": 1}}
        self.connection_module.KlippyConnection.request = inner
        self.kobra.patch_requested_objects()
        conn = self.connection_module.KlippyConnection()
        request = FakeObjectsWebRequest("gcode/script", {"script": "G28"})
        result = await self.connection_module.KlippyConnection.request(conn, request)
        self.assertEqual(result, {"status": {"anything": 1}})

if __name__ == "__main__":
    unittest.main()
