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

        def patcher(status, is_subscription_update):
            received.append((status, is_subscription_update))
            return status

        self.kobra.register_status_patcher(patcher)
        self.kobra.patch_status({"foo": "bar"}, is_subscription_update=True)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], {"foo": "bar"})
        self.assertIs(received[0][1], True)

    def test_patch_status_defaults_is_subscription_update_to_false(self):
        received = []
        self.kobra.register_status_patcher(
            lambda status, is_sub: (received.append(is_sub), status)[1]
        )

        self.kobra.patch_status({})

        self.assertEqual(received, [False])


if __name__ == "__main__":
    unittest.main()
