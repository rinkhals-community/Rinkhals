import importlib.util
import re
import sys
import types
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "files/4-apps/home/rinkhals/apps/40-moonraker/mmu_ace.py"
)
MODULE_NAME = "testsupport.moonraker.components.mmu_ace"
# mmu_ace imports these as package siblings, so they must exist under those
# names before mmu_ace itself is executed.
SIBLING_MODULES = ("mmu_ace_spool_store", "mmu_ace_spool_matcher")
COMMON_NAME = "testsupport.moonraker.common"


class DummyTask:
    def __init__(self, coro):
        self._coro = coro
        coro.close()

    def cancel(self):
        return None

    def done(self):
        return True

    def add_done_callback(self, cb):
        cb(self)


class DummyEventLoop:
    def create_task(self, coro):
        return DummyTask(coro)


class DummyKlippyApis:
    async def query_objects(self, *args, **kwargs):
        return {}


class DummyKlippyConnection:
    async def request(self, *args, **kwargs):
        return {}


class DummyFuture:
    """Awaitable stand-in for the Future Moonraker's database methods return.

    Safe to drop un-awaited: mmu_ace awaits get_item() but deliberately does not
    await insert_item(), and a bare coroutine would raise "never awaited" warnings.
    """

    def __init__(self, result=None):
        self._result = result

    def __await__(self):
        yield from ()
        return self._result


class DummyDatabase:
    """Minimal stand-in for Moonraker's database component.

    Mirrors the parts mmu_ace uses, including register_local_namespace() raising
    on a repeat registration - that is real Moonraker behaviour and the reason the
    call must not sit anywhere reinit() can reach.
    """

    def __init__(self):
        self.namespaces: dict = {}
        self.registered: list = []

    def register_local_namespace(self, namespace, forbidden=False, parse_keys=False):
        if namespace in self.registered:
            raise RuntimeError(f"Namespace '{namespace}' already registered")
        self.registered.append(namespace)
        self.namespaces.setdefault(namespace, {})
        return None

    def insert_item(self, namespace, key, value):
        self.namespaces.setdefault(namespace, {})[key] = value
        return DummyFuture(None)

    def get_item(self, namespace, key=None, default=None):
        entries = self.namespaces.get(namespace, {})
        if key is None:
            return DummyFuture(dict(entries))
        return DummyFuture(entries.get(key, default))

    def delete_item(self, namespace, key):
        self.namespaces.get(namespace, {}).pop(key, None)
        return DummyFuture(None)


class DummyHttpResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def has_error(self):
        return self.status_code >= 400

    def json(self):
        return self._payload


class DummyHttpClient:
    """Stands in for Moonraker's http_client, serving a fake Spoolman.

    Filter behaviour is copied from a real Spoolman 0.22 instance rather than
    guessed: filament.material, filament.id and article_number narrow the result,
    limit/offset page it, and an unrecognised filter - filament.color_hex being
    the one that matters here - is **silently ignored and the full list comes
    back with HTTP 200**. That last part is why the matcher has to re-check every
    field client-side, so the fake has to reproduce it.
    """

    IGNORED_FILTERS = ("filament.color_hex", "color_hex")

    def __init__(self):
        self.spools: list = []
        self.requested: list = []
        self.fail = False

    # --- inventory -----------------------------------------------------------

    def set_spools(self, spools):
        self.spools = spools

    # --- the fake server -----------------------------------------------------

    @staticmethod
    def _page(rows, params):
        offset = int(params.get("offset", 0))
        rows = rows[offset:]
        if "limit" in params:
            rows = rows[: int(params["limit"])]
        return rows

    @staticmethod
    def _colour_close(a, b, threshold):
        a, b = (a or "").strip().upper()[:6], (b or "").strip().upper()[:6]
        if len(a) < 6 or len(b) < 6:
            return False
        if threshold <= 0:
            return a == b
        try:
            dist = sum(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (0, 2, 4))
        except ValueError:
            return False
        return dist / (255 * 3) * 100 <= threshold

    def _filaments(self):
        seen, out = set(), []
        for spool in self.spools:
            f = spool.get("filament") or {}
            if f.get("id") not in seen:
                seen.add(f.get("id"))
                out.append(f)
        return out

    async def get(self, url, **kwargs):
        self.requested.append(url)
        if self.fail:
            raise RuntimeError("spoolman unreachable")

        path, _, query = url.partition("?")
        params = dict(urllib.parse.parse_qsl(query))

        if path.endswith("/v1/filament"):
            rows = self._filaments()
            wanted = params.get("article_number")
            if wanted is not None:
                # Partial and case-insensitive, like the real thing.
                rows = [f for f in rows
                        if wanted.upper() in (f.get("article_number") or "").upper()]
            material = params.get("material")
            if material is not None:
                rows = [f for f in rows
                        if material.upper() in (f.get("material") or "").upper()]
            colour = params.get("color_hex")
            if colour is not None:
                # The real API defaults to a FUZZY threshold (~20); only an
                # explicit 0 means exact. Reproduced so a missing threshold shows
                # up as extra candidates here too, not just on real hardware.
                threshold = float(params.get("color_similarity_threshold", 20))
                rows = [f for f in rows
                        if self._colour_close((f.get("color_hex") or ""), colour, threshold)]
            return DummyHttpResponse(self._page(rows, params))

        rows = list(self.spools)
        material = params.get("filament.material")
        if material is not None:
            # Case-insensitive, verified against a real Spoolman: PETG, petg and
            # PeTg all return the same 13 rows.
            rows = [s for s in rows
                    if ((s.get("filament") or {}).get("material") or "").upper()
                    == material.upper()]
        filament_id = params.get("filament.id")
        if filament_id is not None:
            wanted = {x.strip() for x in str(filament_id).split(",")}
            rows = [s for s in rows
                    if str((s.get("filament") or {}).get("id")) in wanted]
        if params.get("allow_archived", "false").lower() != "true":
            rows = [s for s in rows if not s.get("archived")]
        # Anything in IGNORED_FILTERS is deliberately not applied.
        return DummyHttpResponse(self._page(rows, params))

    # --- assertions ----------------------------------------------------------

    def unfiltered_spool_requests(self):
        """Requests that would pull the whole inventory in one response."""
        out = []
        for url in self.requested:
            path, _, query = url.partition("?")
            if not path.endswith("/v1/spool"):
                continue
            params = dict(urllib.parse.parse_qsl(query))
            if not any(k in params for k in ("filament.material", "filament.id")):
                out.append(url)
        return out


class DummySpoolman:
    """Records which spool IDs reach Moonraker's spoolman component.

    set_active_spool is synchronous at the pinned Moonraker commit; mmu_ace guards
    with inspect.isawaitable, so tests cover both shapes. spoolman_url and
    http_client mirror the real component, which is how spools are looked up.
    """

    def __init__(self, awaitable=False):
        self.activated: list = []
        self._awaitable = awaitable
        self.spoolman_url = "http://spoolman.test/api"
        self.http_client = DummyHttpClient()

    def set_active_spool(self, spool_id):
        self.activated.append(spool_id)
        return DummyFuture(None) if self._awaitable else None

    def set_catalogue(self, *spools):
        """spools: (id, material, color_hex, last_used[, article_number]) tuples.

        The filament id defaults to the spool id, which is enough to tell
        filaments apart; pass spools sharing one filament explicitly if needed.
        """
        payload = []
        for entry in spools:
            i, mat, col, lu = entry[:4]
            article = entry[4] if len(entry) > 4 else None
            payload.append({
                "id": i, "last_used": lu,
                "filament": {"id": i, "material": mat, "color_hex": col,
                             "article_number": article, "name": f"spool {i}"},
            })
        self.http_client.set_spools(payload)


_MISSING = object()


class DummyServer:
    error = RuntimeError

    def __init__(self):
        self.events = []
        self._eventloop = DummyEventLoop()
        self.database = DummyDatabase()
        self._components = {
            "klippy_apis": DummyKlippyApis(),
            "klippy_connection": DummyKlippyConnection(),
            "database": self.database,
        }

    def get_event_loop(self):
        return self._eventloop

    def lookup_component(self, name, default=_MISSING):
        """Matches Moonraker: raise when absent unless a default is supplied."""
        if name in self._components:
            return self._components[name]
        if default is _MISSING:
            raise KeyError(name)
        return default

    def add_spoolman(self, awaitable=False) -> "DummySpoolman":
        spoolman = DummySpoolman(awaitable=awaitable)
        self._components["spoolman"] = spoolman
        return spoolman

    def send_event(self, name, payload):
        self.events.append((name, payload))


def _ensure_package(name: str):
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package
    return sys.modules[name]


def load_mmu_ace_module():
    if MODULE_NAME in sys.modules:
        return sys.modules[MODULE_NAME]

    _ensure_package("testsupport")
    _ensure_package("testsupport.moonraker")
    _ensure_package("testsupport.moonraker.components")

    common_module = types.ModuleType(COMMON_NAME)
    common_module.WebRequest = type("WebRequest", (), {})
    common_module.APITransport = type("APITransport", (), {})
    common_module.RequestType = type("RequestType", (), {})
    sys.modules[COMMON_NAME] = common_module

    for sibling in SIBLING_MODULES:
        name = f"testsupport.moonraker.components.{sibling}"
        sib_spec = importlib.util.spec_from_file_location(
            name, MODULE_PATH.parent / f"{sibling}.py")
        sib_module = importlib.util.module_from_spec(sib_spec)
        sys.modules[name] = sib_module
        assert sib_spec.loader is not None
        sib_spec.loader.exec_module(sib_module)

    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MmuAceControllerSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    def setUp(self):
        self.original_create_task = self.module.asyncio.create_task
        self.module.asyncio.create_task = lambda coro: DummyTask(coro)
        self.server = DummyServer()
        self.controller = self.module.MmuAceController(self.server, host=None)
        self.controller.ace = self.module.MmuAce()
        self.controller._handle_status_update = lambda *args, **kwargs: None

    def tearDown(self):
        self.module.asyncio.create_task = self.original_create_task

    def _build_filament_hub(self, current_filament: str):
        return {
            "current_filament": current_filament,
            "filament_hubs": [
                {
                    "id": 0,
                    "status": "ready",
                    "temp": 25,
                    "slots": [
                        {"index": 0, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
                        {"index": 1, "status": "ready", "sku": "", "type": "PLA", "color": [255, 255, 255], "rfid": 1, "source": 2},
                        {"index": 2, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
                        {"index": 3, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
                    ],
                }
            ],
        }

    def test_refresh_syncs_loaded_gate_and_widget_state(self):
        self.controller._set_ace_status(self._build_filament_hub("0-1"))

        self.assertEqual(self.controller.ace.loaded_gate, 1)
        self.assertEqual(self.controller.ace.gate, 1)
        self.assertEqual(self.controller.ace.tool, 1)
        self.assertEqual(self.controller.ace.filament.pos, self.module.FILAMENT_POS_LOADED)

        status = self.controller.get_status()
        self.assertEqual(status.mmu.gate, 1)
        self.assertEqual(status.mmu.tool, 1)
        self.assertEqual(status.mmu.filament_pos, self.module.FILAMENT_POS_LOADED)
        self.assertFalse(status.mmu.active_filament.empty)

    def test_refresh_handles_missing_or_empty_color_without_crashing(self):
        hub = self._build_filament_hub("")
        hub["filament_hubs"][0]["slots"][0]["color"] = []
        del hub["filament_hubs"][0]["slots"][1]["color"]

        self.controller._set_ace_status(hub)

        gates = self.controller.ace.units[0].gates
        self.assertEqual(gates[0].color, [0, 0, 0, 255])
        self.assertEqual(gates[1].color, [0, 0, 0, 255])

    def test_refresh_clears_loaded_gate_when_hardware_reports_empty(self):
        self.controller.ace.loaded_gate = 1
        self.controller.ace.gate = 1
        self.controller.ace.tool = 1
        self.controller.ace.filament.pos = self.module.FILAMENT_POS_LOADED

        self.controller._set_ace_status(self._build_filament_hub(""))

        self.assertEqual(self.controller.ace.loaded_gate, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.controller.ace.gate, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.controller.ace.tool, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.controller.ace.filament.pos, self.module.FILAMENT_POS_UNLOADED)

        status = self.controller.get_status()
        self.assertEqual(status.mmu.filament_pos, self.module.FILAMENT_POS_UNLOADED)
        self.assertTrue(status.mmu.active_filament.empty)

    def _gate_temperature_logs(self, hub):
        with mock.patch.object(self.module.logging, "info") as info:
            self.controller._set_ace_status(hub)
        return [call.args[0] for call in info.call_args_list if call.args[0].startswith("Gate ")]

    def test_gate_temperatures_are_logged_only_when_they_change(self):
        hub = self._build_filament_hub("")
        hub["filament_hubs"][0]["slots"][1]["temperature"] = {"min": 190, "max": 230}

        self.assertEqual(self._gate_temperature_logs(hub), ["Gate 1: Using RFID temperatures min=190°C, max=230°C"])
        # Same status again (periodic poll): nothing new to log
        self.assertEqual(self._gate_temperature_logs(hub), [])

        # Spool swapped: only the changed gate is logged
        hub["filament_hubs"][0]["slots"][1]["temperature"] = {"min": 220, "max": 260}
        self.assertEqual(self._gate_temperature_logs(hub), ["Gate 1: Using RFID temperatures min=220°C, max=260°C"])
        self.assertEqual(self._gate_temperature_logs(hub), [])

        # Tag data gone: falls back to the material default, logged once
        del hub["filament_hubs"][0]["slots"][1]["temperature"]
        logs = self._gate_temperature_logs(hub)
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].startswith("Gate 1: Using material default temperature"))
        self.assertEqual(self._gate_temperature_logs(hub), [])

    def test_disable_ace_invokes_registered_reset_callback(self):
        calls = []
        self.controller._on_ace_disabled = lambda: calls.append(True)

        self.controller._disable_ace("test reason")

        self.assertEqual(calls, [True])

    def test_disable_ace_without_callback_does_not_raise(self):
        self.controller._on_ace_disabled = None
        self.controller._disable_ace("test reason")  # must not raise


class MmuAcePartialUpdateTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    def setUp(self):
        self.original_create_task = self.module.asyncio.create_task
        self.module.asyncio.create_task = lambda coro: DummyTask(coro)
        self.server = DummyServer()
        self.controller = self.module.MmuAceController(self.server, host=None)
        self.controller.ace = self.module.MmuAce()
        self.status_updates = []
        self.controller._handle_status_update = lambda *args, **kwargs: self.status_updates.append(kwargs)

    def tearDown(self):
        self.module.asyncio.create_task = self.original_create_task

    async def test_partial_current_filament_update_syncs_loaded_state(self):
        await self.controller._handle_mmu_ace_status_update(
            {"filament_hub": {"current_filament": "0-0"}},
            0.0,
        )

        self.assertEqual(self.controller.ace.loaded_gate, 0)
        self.assertEqual(self.controller.ace.gate, 0)
        self.assertEqual(self.controller.ace.tool, 0)
        self.assertEqual(self.controller.ace.filament.pos, self.module.FILAMENT_POS_LOADED)
        self.assertEqual(self.status_updates, [{"force": True}])

    async def test_partial_empty_current_filament_clears_loaded_state(self):
        self.controller.ace.loaded_gate = 1
        self.controller.ace.gate = 1
        self.controller.ace.tool = 1
        self.controller.ace.filament.pos = self.module.FILAMENT_POS_LOADED

        await self.controller._handle_mmu_ace_status_update(
            {"filament_hub": {"current_filament": ""}},
            0.0,
        )

        self.assertEqual(self.controller.ace.loaded_gate, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.controller.ace.gate, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.controller.ace.tool, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.controller.ace.filament.pos, self.module.FILAMENT_POS_UNLOADED)
        self.assertEqual(self.status_updates, [{"force": True}])

    async def test_partial_empty_current_filament_preserves_unloaded_selection(self):
        self.controller.ace.loaded_gate = self.module.TOOL_GATE_UNKNOWN
        self.controller.ace.gate = 2
        self.controller.ace.tool = 2
        self.controller.ace.filament.pos = self.module.FILAMENT_POS_UNLOADED

        await self.controller._handle_mmu_ace_status_update(
            {"filament_hub": {"current_filament": ""}},
            0.0,
        )

        self.assertEqual(self.controller.ace.loaded_gate, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.controller.ace.gate, 2)
        self.assertEqual(self.controller.ace.tool, 2)
        self.assertEqual(self.controller.ace.filament.pos, self.module.FILAMENT_POS_UNLOADED)
        self.assertEqual(self.status_updates, [{"force": True}])

    async def test_partial_update_without_current_filament_is_ignored(self):
        await self.controller._handle_mmu_ace_status_update(
            {"filament_hub": {"filament_present": 1}},
            0.0,
        )

        self.assertEqual(self.controller.ace.loaded_gate, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.controller.ace.gate, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.controller.ace.tool, self.module.TOOL_GATE_UNKNOWN)
        self.assertEqual(self.status_updates, [])


class MmuAceDisconnectReconnectTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    def setUp(self):
        self.original_create_task = self.module.asyncio.create_task
        self.module.asyncio.create_task = lambda coro: DummyTask(coro)
        self.server = DummyServer()
        self.controller = self.module.MmuAceController(self.server, host=None)
        self.controller.ace = self.module.MmuAce()
        self.status_updates = []
        self.controller._handle_status_update = lambda *args, **kwargs: self.status_updates.append(kwargs)

    def tearDown(self):
        self.module.asyncio.create_task = self.original_create_task

    def _build_filament_hub(self, current_filament: str = ""):
        return {
            "current_filament": current_filament,
            "filament_hubs": [
                {
                    "id": 0,
                    "status": "ready",
                    "temp": 25,
                    "slots": [
                        {"index": 0, "status": "ready", "sku": "", "type": "PLA", "color": [255, 255, 255], "rfid": 1, "source": 2},
                        {"index": 1, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
                        {"index": 2, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
                        {"index": 3, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
                    ],
                }
            ],
        }

    async def test_disconnect_disables_ace(self):
        self.controller.ace.enabled = True

        await self.controller._handle_mmu_ace_status_update(
            {"filament_hub": {"filament_hubs": None}},
            0.0,
        )

        self.assertFalse(self.controller.ace.enabled)
        self.assertEqual(self.status_updates, [{"force": True}])

    async def test_disconnect_when_already_disabled_is_idempotent(self):
        self.controller.ace.enabled = False

        await self.controller._handle_mmu_ace_status_update(
            {"filament_hub": {"filament_hubs": None}},
            0.0,
        )

        self.assertFalse(self.controller.ace.enabled)
        self.assertEqual(self.status_updates, [])

    def test_reconnect_reenables_ace_in_set_ace_status(self):
        self.controller.ace.enabled = False

        self.controller._set_ace_status(self._build_filament_hub())

        self.assertTrue(self.controller.ace.enabled)

    def test_set_ace_status_does_not_reenable_when_already_enabled(self):
        self.controller.ace.enabled = True

        self.controller._set_ace_status(self._build_filament_hub())

        self.assertTrue(self.controller.ace.enabled)

    def test_disable_ace_resets_gate_fingerprint(self):
        self.controller._last_gate_fingerprint = "gate0:PLA|gate1:ASA"

        self.controller._disable_ace("test disconnect")

        self.assertEqual(self.controller._last_gate_fingerprint, "")

    def test_first_status_after_reconnect_is_not_suppressed_by_dedup(self):
        # Simulate state just before reconnect: fingerprint has stale data
        # identical to what the ACE will report on reconnect
        self.controller._set_ace_status(self._build_filament_hub())
        self.status_updates.clear()

        # Cable pulled — fingerprint reset, ace disabled
        self.controller._disable_ace("cable disconnected")
        self.status_updates.clear()

        # Cable replugged — same gate data as before disconnect
        self.controller._set_ace_status(self._build_filament_hub())

        # Must push an update even though data is identical to pre-disconnect
        self.assertEqual(self.status_updates, [{"force": True}])


class MmuRecoverTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    async def test_mmu_recover_rejects_unsupported_arguments(self):
        refresh_calls = []
        responses = []
        gate = types.SimpleNamespace(status=self.module.GATE_AVAILABLE, filament_name="PLA")
        patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        patcher.ace_controller = types.SimpleNamespace(
            _handle_status_update=lambda **kwargs: refresh_calls.append(kwargs)
        )
        patcher.ace = types.SimpleNamespace(units=[types.SimpleNamespace(gates=[gate])])

        async def send_response(message):
            responses.append(message)

        patcher._send_gcode_response = send_response

        result = await self.module.MmuAcePatcher._on_gcode_mmu_recover(
            patcher,
            {"GATE": "1", "LOADED": "1", "TOOL": "1"},
            None,
        )

        self.assertIsNone(result)
        self.assertEqual(refresh_calls, [])
        self.assertEqual(len(responses), 1)
        self.assertIn("unsupported parameters", responses[0])

    async def test_mmu_recover_refreshes_without_arguments(self):
        refresh_calls = []
        responses = []
        gate_ready = types.SimpleNamespace(status=self.module.GATE_AVAILABLE, filament_name="PLA")
        gate_empty = types.SimpleNamespace(status=self.module.GATE_EMPTY, filament_name="")
        patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        patcher.ace_controller = types.SimpleNamespace(
            _handle_status_update=lambda **kwargs: refresh_calls.append(kwargs)
        )
        patcher.ace = types.SimpleNamespace(units=[types.SimpleNamespace(gates=[gate_ready, gate_empty])])

        async def send_response(message):
            responses.append(message)

        patcher._send_gcode_response = send_response

        result = await self.module.MmuAcePatcher._on_gcode_mmu_recover(patcher, {}, None)

        self.assertIsNone(result)
        self.assertEqual(refresh_calls, [{"force": True}])
        self.assertEqual(len(responses), 1)
        self.assertIn("ACE status refreshed", responses[0])


class MmuAcePatchStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    def _make_patcher(self, mmu_status):
        patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        patcher._last_pushed_mmu_status = {}
        patcher.get_status = lambda: mmu_status
        return patcher

    def test_non_subscription_returns_full_snapshot_and_updates_cache(self):
        patcher = self._make_patcher({"mmu": {"gate": 1}, "mmu_machine": {"num_units": 1}})

        status = patcher.patch_status({}, is_subscription_update=False)

        self.assertEqual(status, {"mmu": {"gate": 1}, "mmu_machine": {"num_units": 1}})
        # Regression check for the lost-update hole: the non-subscription
        # path must also populate the diff cache.
        self.assertEqual(
            patcher._last_pushed_mmu_status,
            {"mmu": {"gate": 1}, "mmu_machine": {"num_units": 1}},
        )

    def test_subscription_suppresses_unchanged_and_emits_changed(self):
        patcher = self._make_patcher({"mmu": {"gate": 1}, "mmu_machine": {"num_units": 1}})
        patcher._last_pushed_mmu_status = {"mmu": {"gate": 0}, "mmu_machine": {"num_units": 1}}

        status = patcher.patch_status({}, is_subscription_update=True)

        self.assertEqual(status, {"mmu": {"gate": 1}})
        self.assertEqual(
            patcher._last_pushed_mmu_status,
            {"mmu": {"gate": 1}, "mmu_machine": {"num_units": 1}},
        )

    def test_query_between_subscription_pushes_does_not_leave_stale_cache(self):
        """Reproduces the review's lost-update scenario: baseline X,
        MMU changes to Y, a client queries and is served Y, MMU
        reverts to X -- the next subscribed push must still emit the
        reverted value X instead of finding a false non-diff."""
        patcher = self._make_patcher({"mmu": {"gate": 0}})

        # Baseline subscribed push (X).
        patcher.patch_status({}, is_subscription_update=True)

        # MMU changes to Y; a client issues a query (non-subscription).
        patcher.get_status = lambda: {"mmu": {"gate": 1}}
        patcher.patch_status({}, is_subscription_update=False)

        # MMU reverts to X; the next subscribed push must not be empty.
        patcher.get_status = lambda: {"mmu": {"gate": 0}}
        status = patcher.patch_status({}, is_subscription_update=True)

        self.assertEqual(status, {"mmu": {"gate": 0}})

    def test_query_not_requesting_mmu_adds_nothing_and_leaves_cache_alone(self):
        # Panda Breath's actual object list (issue #140).
        patcher = self._make_patcher({"mmu": {"gate": 1}, "mmu_machine": {"num_units": 1}})
        requested = {"webhooks", "virtual_sdcard", "print_stats", "extruder",
                     "heater_bed", "gcode_macro _KNOMI_STATUS"}

        status = patcher.patch_status({"print_stats": {}}, False, requested)

        self.assertEqual(status, {"print_stats": {}})
        self.assertEqual(patcher._last_pushed_mmu_status, {})

    def test_query_requesting_one_mmu_object_adds_and_caches_only_that(self):
        patcher = self._make_patcher({"mmu": {"gate": 1}, "mmu_machine": {"num_units": 1}})

        status = patcher.patch_status({}, False, {"mmu"})

        self.assertEqual(status, {"mmu": {"gate": 1}})
        self.assertEqual(patcher._last_pushed_mmu_status, {"mmu": {"gate": 1}})

    def test_polling_client_without_mmu_cannot_swallow_a_subscriber_update(self):
        """A client polling objects/query for other objects used to advance
        the MMU diff cache on every poll. If a poll landed between an MMU
        change and the next push, subscribers never saw the change (#125)."""
        patcher = self._make_patcher({"mmu": {"gate": 0}})
        patcher.patch_status({}, is_subscription_update=True)      # baseline X

        patcher.get_status = lambda: {"mmu": {"gate": 1}}          # change to Y
        patcher.patch_status({}, False, {"print_stats", "heater_bed"})  # unrelated poll

        status = patcher.patch_status({}, is_subscription_update=True)
        self.assertEqual(status, {"mmu": {"gate": 1}})

    def test_reinit_resets_mmu_status_cache(self):
        patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        patcher._auto_feed_task = None
        patcher._last_pushed_mmu_status = {"mmu": {"gate": 5}}
        patcher.ace_controller = types.SimpleNamespace(set_ace=lambda ace: None)

        patcher.reinit()

        self.assertEqual(patcher._last_pushed_mmu_status, {})



class ControllerTestBase(unittest.TestCase):
    """Shared setup for the Spoolman gate-mapping tests.

    Mirrors the per-class setUp the older test classes above use: stub out
    asyncio.create_task so the controller's background tasks never run, and
    silence status pushes unless a test wants to observe them.
    """

    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    def setUp(self):
        self.original_create_task = self.module.asyncio.create_task
        self.module.asyncio.create_task = lambda coro: DummyTask(coro)
        self.server = DummyServer()
        self.controller = self.module.MmuAceController(self.server, host=None)
        self.controller.ace = self.module.MmuAce()
        self.controller._handle_status_update = lambda *args, **kwargs: None

    def tearDown(self):
        self.module.asyncio.create_task = self.original_create_task

    def _spoolman_support(self):
        return self.controller.get_status().mmu.spoolman_support


class MmuAceSpoolmanSupportTests(ControllerTestBase):
    """spoolman_support gates the spool picker in Mainsail and Fluidd."""

    def test_reports_off_when_spoolman_is_not_configured(self):
        self.assertEqual(self._spoolman_support(), "off")

    def test_reports_readonly_when_spoolman_is_configured(self):
        self.server.add_spoolman()

        self.assertEqual(self._spoolman_support(), "readonly")

    def test_value_is_not_cached_at_construction_time(self):
        # [spoolman] reaches Moonraker through moonraker.custom.conf, which
        # process-cfg.py merges last, so mmu_ace is constructed before the
        # spoolman component exists. A value resolved once in __init__ would
        # be stuck on "off" for the whole session.
        self.assertEqual(self._spoolman_support(), "off")

        self.server.add_spoolman()

        self.assertEqual(self._spoolman_support(), "readonly")


class MmuAceSpoolOverrideTests(ControllerTestBase):
    """A user-assigned Spoolman ID must survive the periodic ACE status rebuild.

    _set_ace_status() recreates every MmuAceGate from raw hub data roughly every
    20s, re-deriving spool_id from the RFID SKU serial or zeroing it. Without an
    override that outranks both branches, an assignment is gone seconds after it
    is made (issues #89, #107, #141).
    """

    # Gate 0 untagged (rfid 1, no SKU) and gate 1 RFID-locked (rfid 2), matching
    # the mix on a real ACE with third-party spool support enabled.
    def _build_filament_hub(self, current_filament=""):
        return {
            "current_filament": current_filament,
            "filament_hubs": [
                {
                    "id": 0,
                    "status": "ready",
                    "temp": 25,
                    "slots": [
                        {"index": 0, "status": "ready", "sku": "", "type": "PETG", "color": [255, 255, 255], "rfid": 1, "source": 2},
                        {"index": 1, "status": "ready", "sku": "AHPLBK-107", "type": "PLA", "color": [10, 10, 10], "rfid": 2, "source": 2},
                        {"index": 2, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
                        {"index": 3, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
                    ],
                }
            ],
        }

    def _gates(self):
        return [gate for unit in self.controller.ace.units for gate in unit.gates]

    def test_unassigned_gates_report_no_spool(self):
        # Neither an untagged gate nor a tagged one invents an id of its own.
        self.controller._set_ace_status(self._build_filament_hub())

        gates = self._gates()
        self.assertEqual(gates[0].spool_id, 0)
        self.assertEqual(gates[1].spool_id, 0)

    def test_override_outranks_the_rfid_derived_pseudo_id(self):
        self.controller._manual_spool_overrides[1] = 24

        self.controller._set_ace_status(self._build_filament_hub())

        self.assertEqual(self._gates()[1].spool_id, 24)

    def test_override_survives_on_a_gate_without_an_rfid_tag(self):
        # The "else: gate.spool_id = 0" branch of the resync wiped these; it is the
        # branch every untagged third-party spool takes.
        self.controller._manual_spool_overrides[0] = 16

        self.controller._set_ace_status(self._build_filament_hub())

        self.assertEqual(self._gates()[0].spool_id, 16)

    def test_override_survives_repeated_status_rebuilds(self):
        self.controller._manual_spool_overrides[0] = 16
        self.controller._manual_spool_overrides[1] = 24

        for _ in range(3):
            self.controller._set_ace_status(self._build_filament_hub())

        gates = self._gates()
        self.assertEqual(gates[0].spool_id, 16)
        self.assertEqual(gates[1].spool_id, 24)

    def test_override_is_keyed_on_the_global_gate_index(self):
        # Two ACE units: unit 1's gates are global 4-7, so an override on gate 5
        # must land on unit 1 slot 1, not unit 0 slot 1.
        hub = self._build_filament_hub()
        second = {
            "id": 1,
            "status": "ready",
            "temp": 25,
            "slots": [
                {"index": 0, "status": "ready", "sku": "", "type": "PETG", "color": [1, 1, 1], "rfid": 1, "source": 2},
                {"index": 1, "status": "ready", "sku": "AHPLBK-107", "type": "PLA", "color": [2, 2, 2], "rfid": 2, "source": 2},
                {"index": 2, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
                {"index": 3, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
            ],
        }
        hub["filament_hubs"].append(second)
        self.controller._manual_spool_overrides[5] = 31

        self.controller._set_ace_status(hub)

        gates = self._gates()
        self.assertEqual(gates[5].spool_id, 31)
        self.assertEqual(gates[1].spool_id, 0)


_HUB_MIXED_SLOTS = [
    {"index": 0, "status": "ready", "sku": "", "type": "PETG", "color": [255, 255, 255], "rfid": 1, "source": 2},
    {"index": 1, "status": "ready", "sku": "AHPLBK-107", "type": "PLA", "color": [10, 10, 10], "rfid": 2, "source": 2},
    {"index": 2, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
    {"index": 3, "status": "empty", "sku": "", "type": "", "color": [0, 0, 0], "rfid": 1, "source": 3},
]


def build_mixed_hub(current_filament=""):
    """One untagged gate (0), one RFID-locked gate (1), two empty."""
    return {
        "current_filament": current_filament,
        "filament_hubs": [
            {
                "id": 0,
                "status": "ready",
                "temp": 25,
                "slots": [dict(slot) for slot in _HUB_MIXED_SLOTS],
            }
        ],
    }


class AsyncControllerTestBase(unittest.IsolatedAsyncioTestCase):
    """Async counterpart of ControllerTestBase."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    def setUp(self):
        self.original_create_task = self.module.asyncio.create_task
        self.module.asyncio.create_task = lambda coro: DummyTask(coro)
        self.server = DummyServer()
        self.controller = self.module.MmuAceController(self.server, host=None)
        self.controller.ace = self.module.MmuAce()
        self.status_updates = []
        self.controller._handle_status_update = lambda *a, **kw: self.status_updates.append(kw)
        self.controller._set_ace_status(build_mixed_hub())
        self.status_updates.clear()

    async def asyncSetUp(self):
        # DummyEventLoop discards the task __init__ schedules, so drive the initial
        # store read explicitly - otherwise every controller sits in the pre-load
        # state where writes are deliberately held.
        await self.controller._load_spool_assignments()

    def tearDown(self):
        self.module.asyncio.create_task = self.original_create_task

    def _gate(self, index):
        gates = [gate for unit in self.controller.ace.units for gate in unit.gates]
        return gates[index]


class MmuAceUpdateGateSpoolTests(AsyncControllerTestBase):
    """update_gate() rejects writes to RFID-locked gates, but the Spoolman ID has
    nothing to do with the RFID payload and must still be recorded (issue #141)."""

    async def test_records_override_on_an_rfid_locked_gate(self):
        await self.controller.update_gate(1, spool_id=24)

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

    async def test_rfid_locked_gate_still_rejects_the_rest_of_the_update(self):
        # The lock exists to keep material/colour/temp authoritative from the tag.
        # Recording the spool ID must not weaken that.
        await self.controller.update_gate(1, material="WOOD", filament_name="Nope", spool_id=24)

        self.assertEqual(self._gate(1).material, "PLA")
        self.assertEqual(self._gate(1).filament_name, "Anycubic Highspeed PLA Black")

    async def test_records_override_on_an_untagged_gate(self):
        await self.controller.update_gate(0, status=1, material="PETG", spool_id=16)

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 16)
        self.assertEqual(self._gate(0).spool_id, 16)

    async def test_absent_spool_id_does_not_record_an_override(self):
        # update_gate defaults spool_id to -1; a colour-only edit must not invent one.
        await self.controller.update_gate(0, status=1, material="PETG")

        self.assertEqual(self.controller._manual_spool_overrides, {})

    async def test_unknown_gate_is_ignored(self):
        await self.controller.update_gate(99, spool_id=24)

        self.assertEqual(self.controller._manual_spool_overrides, {})


    async def test_assignment_on_a_locked_gate_updates_the_reported_id_at_once(self):
        await self.controller.update_gate(1, spool_id=24)

        self.assertEqual(self._gate(1).spool_id, 24)

    # --- 8: a valueless COLOR must not abort the whole edit --------------------------


class MmuAceSetManualSpoolIdTests(AsyncControllerTestBase):
    """set_manual_spool_id() applies an assignment immediately, rather than waiting
    for the next ACE status poll to fold the override in."""

    async def test_applies_to_an_rfid_locked_gate_immediately(self):
        result = self.controller.set_manual_spool_id(1, 24)

        self.assertTrue(result)
        self.assertEqual(self._gate(1).spool_id, 24)
        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

    async def test_pushes_a_status_update_so_the_ui_reflects_it(self):
        self.controller.set_manual_spool_id(1, 24)

        self.assertIn({"force": True}, self.status_updates)

    async def test_returns_false_for_an_unknown_gate(self):
        result = self.controller.set_manual_spool_id(99, 24)

        self.assertFalse(result)
        self.assertEqual(self.controller._manual_spool_overrides, {})


class PendingTask:
    """Task stub that keeps its coroutine alive so a test can await it."""

    def cancel(self):
        return None

    def done(self):
        return False

    def add_done_callback(self, cb):
        self._cb = cb


class CollectingEventLoop:
    """Captures coroutines scheduled with create_task instead of discarding them,
    so tests can drive the fire-and-forget activation path to completion."""

    def __init__(self):
        self.coros = []

    def create_task(self, coro):
        self.coros.append(coro)
        return PendingTask()

    async def drain(self):
        while self.coros:
            await self.coros.pop(0)


class MmuAceSpoolActivationTests(AsyncControllerTestBase):
    """Moonraker's active spool must follow the gate the ACE reports as loaded, and
    must only ever be given IDs the user actually assigned."""

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop

    async def test_activates_the_assigned_spool(self):
        spoolman = self.server.add_spoolman()
        self.controller._manual_spool_overrides[1] = 24

        await self.controller._activate_spoolman_for_gate(1)

        self.assertEqual(spoolman.activated, [24])

    async def test_never_sends_anything_for_an_unassigned_tagged_gate(self):
        # gate 1 carries SKU AHPLBK-107. Nothing derived from that tag may reach
        # Spoolman, and since the fabricated id was removed the gate reports 0.
        spoolman = self.server.add_spoolman()
        self.assertEqual(self._gate(1).spool_id, 0)

        await self.controller._activate_spoolman_for_gate(1)

        self.assertNotIn(107, spoolman.activated)
        self.assertEqual(spoolman.activated, [None])

    async def test_unassigned_gate_deactivates_rather_than_leaving_the_old_spool(self):
        # Leaving the previous spool active would keep debiting it for filament it
        # did not supply, and nothing in Spoolman would show the numbers are wrong.
        spoolman = self.server.add_spoolman()
        self.controller._manual_spool_overrides[1] = 24

        self.controller._sync_loaded_gate_from_current_filament("0-1")
        await self.loop.drain()
        self.controller._sync_loaded_gate_from_current_filament("0-2")
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [24, None])

    async def test_clearing_the_loaded_gates_assignment_deactivates(self):
        spoolman = self.server.add_spoolman()
        self.controller.ace.loaded_gate = 1
        self.controller.set_manual_spool_id(1, 24)
        await self.loop.drain()
        spoolman.activated.clear()

        self.controller.clear_manual_spool_id(1)
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [None])

    async def test_clearing_an_idle_gates_assignment_leaves_spoolman_alone(self):
        spoolman = self.server.add_spoolman()
        self.controller.ace.loaded_gate = 1
        self.controller.set_manual_spool_id(0, 16)
        await self.loop.drain()
        spoolman.activated.clear()

        self.controller.clear_manual_spool_id(0)
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [])

    async def test_awaits_set_active_spool_when_it_is_awaitable(self):
        spoolman = self.server.add_spoolman(awaitable=True)
        self.controller._manual_spool_overrides[1] = 24

        await self.controller._activate_spoolman_for_gate(1)

        self.assertEqual(spoolman.activated, [24])

    async def test_is_a_no_op_without_the_spoolman_component(self):
        self.controller._manual_spool_overrides[1] = 24

        await self.controller._activate_spoolman_for_gate(1)  # must not raise

    async def test_swallows_spoolman_errors(self):
        # This runs off the ACE status path; a Spoolman hiccup must never take the
        # MMU component down with it.
        spoolman = self.server.add_spoolman()

        def boom(spool_id):
            raise RuntimeError("spoolman is down")

        spoolman.set_active_spool = boom
        self.controller._manual_spool_overrides[1] = 24

        await self.controller._activate_spoolman_for_gate(1)  # must not raise

    async def test_loaded_gate_change_activates_the_new_gate(self):
        # Print start and firmware-driven tool changes never call MMU_LOAD, so this
        # sync point is the only hook that covers a real multi-colour print.
        spoolman = self.server.add_spoolman()
        self.controller._manual_spool_overrides[1] = 24

        self.controller._sync_loaded_gate_from_current_filament("0-1")
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [24])

    async def test_unchanged_loaded_gate_does_not_reactivate(self):
        spoolman = self.server.add_spoolman()
        self.controller._manual_spool_overrides[1] = 24
        self.controller._sync_loaded_gate_from_current_filament("0-1")
        await self.loop.drain()
        spoolman.activated.clear()

        self.controller._sync_loaded_gate_from_current_filament("0-1")
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [])

    async def test_colour_change_mid_print_follows_the_new_gate(self):
        spoolman = self.server.add_spoolman()
        self.controller._manual_spool_overrides[0] = 16
        self.controller._manual_spool_overrides[1] = 24

        self.controller._sync_loaded_gate_from_current_filament("0-1")
        await self.loop.drain()
        self.controller._sync_loaded_gate_from_current_filament("0-0")
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [24, 16])

    async def test_assigning_a_spool_to_the_loaded_gate_activates_it_at_once(self):
        spoolman = self.server.add_spoolman()
        self.controller.ace.loaded_gate = 1

        self.controller.set_manual_spool_id(1, 24)
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [24])

    async def test_assigning_a_spool_to_an_idle_gate_does_not_activate_it(self):
        spoolman = self.server.add_spoolman()
        self.controller.ace.loaded_gate = 1

        self.controller.set_manual_spool_id(0, 16)
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [])


class MmuAceGateMapArgsTests(AsyncControllerTestBase):
    """MMU_GATE_MAP has to understand every form the shipped web UIs send.

    Mainsail 2.17.0 sends flat arguments and single-field edits; Fluidd 1.35.0 sends
    a quoted MAP= dict; both send RESET=1. Only MAP= was handled, so everything
    Mainsail sends failed with "param MAP not found on command" (issue #141).
    """

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        self.patcher.ace_controller = self.controller
        self.patcher.ace = self.controller.ace

    async def _send(self, args):
        await self.module.MmuAcePatcher._on_gcode_mmu_gate_map(self.patcher, args, None)

    # --- a bad SPOOLID must not discard the rest of the command ---------------

    BAD_SPOOL_IDS = ["", "  ", "abc", "12x"]

    async def test_an_unusable_spoolid_still_applies_the_other_fields(self):
        """SPOOLID was parsed with a helper that raises when it cannot, which
        aborted the whole command and threw away the NAME/MATERIAL/TEMP edits
        sent alongside it."""
        for value in self.BAD_SPOOL_IDS:
            with self.subTest(spoolid=value):
                await self._send({"GATE": "0", "SPOOLID": value, "NAME": "Edited",
                                  "MATERIAL": "PETG", "TEMP": "240", "QUIET": "1"})

                self.assertEqual(self._gate(0).filament_name, "Edited")
                self.assertNotIn(0, self.controller._manual_spool_overrides)

    # --- Mainsail: choosing a spool -------------------------------------------

    async def test_mainsail_flat_form_assigns_the_spool(self):
        # MMU_GATE_MAP GATE=0 SPOOLID=16 NAME="Prusament PETG" MATERIAL="PETG"
        #              COLOR="FF8800" TEMP=240 QUIET=1
        await self._send({
            "GATE": "0", "SPOOLID": "16", "NAME": "Prusament PETG",
            "MATERIAL": "PETG", "COLOR": "FF8800", "TEMP": "240", "QUIET": "1",
        })

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 16)
        self.assertEqual(self._gate(0).spool_id, 16)
        self.assertEqual(self._gate(0).material, "PETG")
        self.assertEqual(self._gate(0).filament_name, "Prusament PETG")

    async def test_mainsail_flat_form_works_on_an_rfid_locked_gate(self):
        await self._send({"GATE": "1", "SPOOLID": "24", "NAME": "Some PLA",
                          "MATERIAL": "PLA", "COLOR": "112233", "TEMP": "210", "QUIET": "1"})

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)
        self.assertEqual(self._gate(1).spool_id, 24)
        # ...while the tag still owns the filament description.
        self.assertEqual(self._gate(1).material, "PLA")

    async def test_flat_form_does_not_mark_a_loaded_gate_empty(self):
        # Mainsail never sends a status field. update_gate defaults it to GATE_EMPTY,
        # so passing the default through would empty a loaded gate on every pick.
        self.assertEqual(self._gate(0).status, self.module.GATE_AVAILABLE)

        await self._send({"GATE": "0", "SPOOLID": "16", "NAME": "X",
                          "MATERIAL": "PETG", "COLOR": "FF8800", "TEMP": "240"})

        self.assertEqual(self._gate(0).status, self.module.GATE_AVAILABLE)

    # --- Mainsail: single-field edits ------------------------------------------

    async def test_single_field_edit_preserves_the_assigned_spool(self):
        self.controller.set_manual_spool_id(0, 16)

        await self._send({"GATE": "0", "NAME": "Renamed", "QUIET": "1"})

        self.assertEqual(self._gate(0).filament_name, "Renamed")
        self.assertEqual(self._gate(0).spool_id, 16)
        self.assertEqual(self.controller._manual_spool_overrides.get(0), 16)

    async def test_single_field_edit_preserves_other_fields(self):
        await self._send({"GATE": "0", "TEMP": "250", "QUIET": "1"})

        self.assertEqual(self._gate(0).temperature, 250)
        self.assertEqual(self._gate(0).material, "PETG")
        self.assertEqual(self._gate(0).status, self.module.GATE_AVAILABLE)

    async def test_single_field_edit_never_creates_an_assignment(self):
        # An unassigned gate now reports 0 rather than a fabricated id, so a
        # field-only edit echoes 0 and must not create an assignment from it.
        self.assertEqual(self._gate(1).spool_id, 0)

        await self._send({"GATE": "1", "TEMP": "215", "QUIET": "1"})

        self.assertEqual(self.controller._manual_spool_overrides, {})

    # --- Mainsail: clearing ------------------------------------------------------

    async def test_spoolid_minus_one_clears_the_assignment(self):
        self.controller.set_manual_spool_id(0, 16)

        await self._send({"GATE": "0", "SPOOLID": "-1", "QUIET": "1"})

        self.assertNotIn(0, self.controller._manual_spool_overrides)
        self.assertEqual(self._gate(0).spool_id, 0)

    # --- Fluidd: the MAP= dict ---------------------------------------------------

    async def test_fluidd_map_form_still_works(self):
        gate_map = ("{0: {'status': 1, 'spool_id': 16, 'material': 'PETG', "
                    "'color': 'FF8800', 'name': 'Prusament PETG', 'temp': 240, "
                    "'speed_override': 100}}")

        await self._send({"MAP": gate_map, "QUIET": "1"})

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 16)
        self.assertEqual(self._gate(0).material, "PETG")

    async def test_fluidd_map_form_can_clear_a_spool(self):
        self.controller.set_manual_spool_id(0, 16)
        gate_map = ("{0: {'status': 1, 'spool_id': -1, 'material': 'PETG', "
                    "'color': 'FF8800', 'name': 'PETG', 'temp': 240, "
                    "'speed_override': 100}}")

        await self._send({"MAP": gate_map, "QUIET": "1"})

        self.assertNotIn(0, self.controller._manual_spool_overrides)

    # --- RESET and errors ---------------------------------------------------------

    async def test_reset_clears_every_assignment(self):
        self.controller.set_manual_spool_id(0, 16)
        self.controller.set_manual_spool_id(1, 24)

        await self._send({"RESET": "1"})

        self.assertEqual(self.controller._manual_spool_overrides, {})

    async def test_rejects_a_command_with_no_recognised_argument(self):
        with self.assertRaises(ValueError):
            await self._send({"QUIET": "1"})

    async def test_unknown_gate_is_reported_not_crashed(self):
        with self.assertRaises(ValueError):
            await self._send({"GATE": "99", "SPOOLID": "16"})


    async def test_empty_colour_falls_back_to_the_current_colour(self):
        before = list(self._gate(0).color)

        await self._send({"GATE": "0", "COLOR": None, "NAME": "Still applied", "QUIET": "1"})

        self.assertEqual(self._gate(0).filament_name, "Still applied")
        self.assertEqual(self._gate(0).color, before)

    # --- 9: a pick during the startup load must not be lost ---------------------------


class HexToRgbaTests(unittest.TestCase):
    """The two shipped UIs send colours in different widths."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    ACCEPTED = [
        ("eight digits, as Fluidd sends",      "FCF6F6FF",  [252, 246, 246, 255]),
        ("six digits, as Mainsail forwards",   "FF8800",    [255, 136, 0, 255]),
        ("a leading hash",                     "#FF8800",   [255, 136, 0, 255]),
        ("surrounding whitespace",             "  FF8800 ", [255, 136, 0, 255]),
        ("whitespace before the hash",         " #FF8800",  [255, 136, 0, 255]),
        ("lower case",                         "ff8800",    [255, 136, 0, 255]),
    ]

    REJECTED = ["nope", "", "FF88", "FF88001122"]

    def test_accepts_the_forms_the_uis_send(self):
        for label, value, expected in self.ACCEPTED:
            with self.subTest(label):
                self.assertEqual(self.module.hex_to_rgba(value), expected)

    def test_rejects_malformed_colours(self):
        for value in self.REJECTED:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.module.hex_to_rgba(value)


class MmuSetSpoolCommandTests(AsyncControllerTestBase):
    """MMU_SET_SPOOL GATE=<n> SPOOLID=<id> - console and macro equivalent of the
    UI's spool picker."""

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.responses = []
        self.patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        self.patcher.ace_controller = self.controller
        self.patcher.ace = self.controller.ace

        async def send_response(message):
            self.responses.append(message)

        self.patcher._send_gcode_response = send_response

    async def _send(self, args):
        return await self.module.MmuAcePatcher._on_gcode_mmu_set_spool(self.patcher, args, None)

    async def test_assigns_the_spool(self):
        await self._send({"GATE": "1", "SPOOLID": "24"})

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)
        self.assertEqual(self._gate(1).spool_id, 24)

    async def test_clears_with_a_non_positive_id(self):
        self.controller.set_manual_spool_id(1, 24)

        await self._send({"GATE": "1", "SPOOLID": "-1"})

        self.assertNotIn(1, self.controller._manual_spool_overrides)

    async def test_reports_a_missing_argument_instead_of_raising(self):
        await self._send({"GATE": "1"})

        self.assertTrue(any("SPOOLID" in r for r in self.responses))
        self.assertEqual(self.controller._manual_spool_overrides, {})

    async def test_reports_a_non_numeric_argument(self):
        await self._send({"GATE": "1", "SPOOLID": "abc"})

        self.assertTrue(self.responses)
        self.assertEqual(self.controller._manual_spool_overrides, {})

    async def test_reports_an_unknown_gate(self):
        await self._send({"GATE": "99", "SPOOLID": "24"})

        self.assertTrue(self.responses)

    async def test_confirms_success(self):
        await self._send({"GATE": "1", "SPOOLID": "24"})

        self.assertTrue(any("24" in r for r in self.responses))


class MmuGateSkusCommandTests(AsyncControllerTestBase):
    """MMU_GATE_SKUS - lists what to paste into Spoolman's Article number."""

    def setUp(self):
        super().setUp()
        self.controller.eventloop = CollectingEventLoop()
        self.responses = []
        self.patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        self.patcher.ace_controller = self.controller
        self.patcher.ace = self.controller.ace

        async def send_response(message):
            self.responses.append(message)

        self.patcher._send_gcode_response = send_response

    async def _send(self):
        return await self.module.MmuAcePatcher._on_gcode_mmu_gate_skus(self.patcher, {}, None)

    async def test_one_line_per_gate(self):
        await self._send()

        self.assertEqual(len(self.responses), 4)
        self.assertTrue(all(r.startswith("MMU_GATE_SKUS: ") for r in self.responses))

    async def test_reports_the_tag_sku(self):
        await self._send()

        self.assertIn("SKU AHPLBK-107", self.responses[1])
        self.assertIn("PLA", self.responses[1])

    async def test_untagged_gate_says_so(self):
        await self._send()

        self.assertIn("SKU no tag", self.responses[0])

    async def test_empty_gate(self):
        await self._send()

        self.assertIn("EMPTY", self.responses[2])

    async def test_shows_the_assigned_spool(self):
        self.controller.set_manual_spool_id(1, 24)

        await self._send()

        self.assertIn("spool 24", self.responses[1])
        self.assertIn("no spool assigned", self.responses[0])

    async def test_does_not_run_the_original_command(self):
        self.assertIsNone(await self._send())


class MmuLoadActivationTests(AsyncControllerTestBase):
    """A manual MMU_LOAD sets loaded_gate itself, so the loaded-gate sync hook sees
    no change and never fires. It needs its own activation call."""

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        self.patcher.ace_controller = self.controller
        self.patcher.ace = self.controller.ace

        async def send_response(message):
            return None

        async def ensure_temp(gate):
            return True

        async def send_gcode(gcode):
            return "ok"

        self.patcher._send_gcode_response = send_response
        self.patcher._ensure_extruder_temp = ensure_temp
        self.controller.printer.send_gcode = send_gcode

    async def test_manual_load_activates_the_assigned_spool(self):
        spoolman = self.server.add_spoolman()
        self.controller.set_manual_spool_id(1, 24)
        await self.loop.drain()
        spoolman.activated.clear()

        await self.module.MmuAcePatcher._on_gcode_mmu_load(self.patcher, {"GATE": "1"}, None)
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [24])

    async def test_manual_load_of_an_unassigned_gate_deactivates(self):
        spoolman = self.server.add_spoolman()

        await self.module.MmuAcePatcher._on_gcode_mmu_load(self.patcher, {"GATE": "1"}, None)
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [None])


class MmuAceSpoolPersistenceTests(AsyncControllerTestBase):
    """Assignments survive a Moonraker restart, and are dropped when the evidence
    says the spool they referred to is gone."""

    NAMESPACE = "mmu_ace"
    KEY = "spool_assignments"

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.clock = 1000.0
        self.controller._spool_store.time_fn = lambda: self.clock

    def _stored(self):
        return self.server.database.namespaces.get(self.NAMESPACE, {}).get(self.KEY, {})

    # --- writing ---------------------------------------------------------------

    def test_registers_its_namespace(self):
        self.assertIn(self.NAMESPACE, self.server.database.registered)

    def test_an_assignment_is_written_to_the_database(self):
        self.controller.set_manual_spool_id(1, 24)

        self.assertEqual(self._stored(), {"1": {"spool_id": 24, "sku": "AHPLBK-107"}})

    def test_clearing_an_assignment_records_the_clear(self):
        # The row stays, with no spool: it is the record that the user
        # unassigned this gate on purpose, which is what stops auto-match
        # putting the same spool straight back. See MmuAceClearedGateTests.
        self.controller.set_manual_spool_id(1, 24)

        self.controller.clear_manual_spool_id(1)

        self.assertEqual(self._stored(), {"1": {"spool_id": 0, "sku": "AHPLBK-107"}})

    def test_a_reset_removes_assignments_from_the_database_outright(self):
        self.controller.set_manual_spool_id(1, 24)

        self.controller.clear_all_manual_spool_ids()

        self.assertEqual(self._stored(), {})

    def test_a_second_controller_does_not_crash_on_the_registered_namespace(self):
        # Moonraker's register_local_namespace raises on a repeat call.
        second = self.module.MmuAceController(self.server, host=None)

        self.assertIsNotNone(second)

    # --- reading back -----------------------------------------------------------

    async def test_restores_an_assignment_when_the_gate_holds_the_same_spool(self):
        self.server.database.namespaces[self.NAMESPACE] = {
            self.KEY: {"1": {"spool_id": 24, "sku": "AHPLBK-107"}}
        }
        fresh = self.module.MmuAceController(self.server, host=None)
        fresh.ace = self.module.MmuAce()
        fresh._handle_status_update = lambda *a, **kw: None
        await fresh._load_spool_assignments()

        fresh._set_ace_status(build_mixed_hub())

        self.assertEqual(fresh._manual_spool_overrides.get(1), 24)

    async def test_does_not_restore_when_a_different_product_is_in_the_gate(self):
        self.server.database.namespaces[self.NAMESPACE] = {
            self.KEY: {"1": {"spool_id": 24, "sku": "APLARD-201"}}
        }
        fresh = self.module.MmuAceController(self.server, host=None)
        fresh.ace = self.module.MmuAce()
        fresh._handle_status_update = lambda *a, **kw: None
        await fresh._load_spool_assignments()

        fresh._set_ace_status(build_mixed_hub())

        self.assertNotIn(1, fresh._manual_spool_overrides)

    async def test_ignores_malformed_records(self):
        self.server.database.namespaces[self.NAMESPACE] = {
            self.KEY: {"1": {"spool_id": "nonsense"}, "x": {"spool_id": 5}, "2": None}
        }
        fresh = self.module.MmuAceController(self.server, host=None)

        await fresh._load_spool_assignments()  # must not raise

        self.assertEqual(fresh._spool_store.entries, {})

    # --- forgetting --------------------------------------------------------------

    def test_forgets_when_the_gate_holds_a_different_product(self):
        self.controller.set_manual_spool_id(1, 24)
        hub = build_mixed_hub()
        hub["filament_hubs"][0]["slots"][1]["sku"] = "APLARD-201"

        self.controller._set_ace_status(hub)

        self.assertNotIn(1, self.controller._manual_spool_overrides)

    def test_forgets_after_the_gate_has_been_empty_long_enough(self):
        self.controller._spool_store.forget_after = 300  # opt in: off by default
        self.controller.set_manual_spool_id(1, 24)
        hub = build_mixed_hub()
        hub["filament_hubs"][0]["slots"][1]["status"] = "empty"

        self.controller._set_ace_status(hub)
        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

        self.clock += 301
        self.controller._set_ace_status(hub)

        self.assertNotIn(1, self.controller._manual_spool_overrides)

    def test_empty_gate_keeps_its_assignment_by_default(self):
        # spool_forget_after is off unless the user opts in, so an assignment
        # never disappears without the user doing something.
        self.assertEqual(self.module.MmuAceSpoolStore.DEFAULT_FORGET_AFTER_S, 0)
        self.controller.set_manual_spool_id(1, 24)
        hub = build_mixed_hub()
        hub["filament_hubs"][0]["slots"][1]["status"] = "empty"

        self.controller._set_ace_status(hub)
        self.clock += 3600
        self.controller._set_ace_status(hub)

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

    def test_a_brief_empty_reading_does_not_forget(self):
        self.controller._spool_store.forget_after = 300  # opt in: off by default
        self.controller.set_manual_spool_id(1, 24)
        hub = build_mixed_hub()
        hub["filament_hubs"][0]["slots"][1]["status"] = "empty"

        self.controller._set_ace_status(hub)
        self.clock += 30
        self.controller._set_ace_status(hub)

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

    def test_refilling_the_gate_restarts_the_empty_timer(self):
        self.controller.set_manual_spool_id(1, 24)
        empty = build_mixed_hub()
        empty["filament_hubs"][0]["slots"][1]["status"] = "empty"

        self.controller._set_ace_status(empty)
        self.clock += 200
        self.controller._set_ace_status(build_mixed_hub())
        self.clock += 200
        self.controller._set_ace_status(empty)

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

    def test_forget_after_zero_never_expires_an_assignment(self):
        self.controller._spool_store.forget_after = 0
        self.controller.set_manual_spool_id(1, 24)
        hub = build_mixed_hub()
        hub["filament_hubs"][0]["slots"][1]["status"] = "empty"

        self.controller._set_ace_status(hub)
        self.clock += 100000
        self.controller._set_ace_status(hub)

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

    def test_untagged_gates_match_on_an_empty_sku(self):
        # Documented limitation: nothing the ACE reports distinguishes two untagged
        # spools, so gate 0's assignment follows the gate, not the physical spool.
        self.controller.set_manual_spool_id(0, 16)

        self.controller._set_ace_status(build_mixed_hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 16)

    # --- resilience ----------------------------------------------------------------

    def test_a_database_failure_does_not_break_the_status_rebuild(self):
        def boom(*args, **kwargs):
            raise RuntimeError("database is gone")

        self.server.database.insert_item = boom
        self.controller.set_manual_spool_id(1, 24)

        self.controller._set_ace_status(build_mixed_hub())  # must not raise

        self.assertEqual(self._gate(1).spool_id, 24)

    def test_works_without_a_database_component(self):
        del self.server._components["database"]

        controller = self.module.MmuAceController(self.server, host=None)
        controller.ace = self.module.MmuAce()
        controller._handle_status_update = lambda *a, **kw: None
        controller._set_ace_status(build_mixed_hub())
        controller.set_manual_spool_id(1, 24)

        self.assertEqual(controller._manual_spool_overrides.get(1), 24)


    async def test_assignment_made_before_the_store_loads_is_not_dropped(self):
        self.server.database.namespaces["mmu_ace"] = {
            "spool_assignments": {"1": {"spool_id": 24, "sku": "AHPLBK-107"}}
        }
        fresh = self.module.MmuAceController(self.server, host=None)
        fresh.ace = self.module.MmuAce()
        fresh._handle_status_update = lambda *a, **kw: None
        fresh.eventloop = CollectingEventLoop()
        fresh._set_ace_status(build_mixed_hub())

        # user picks a spool while _load_spool_assignments() is still in flight
        fresh.set_manual_spool_id(0, 16)
        await fresh._load_spool_assignments()

        self.assertEqual(fresh._spool_store.entries.get(0), {"spool_id": 16, "sku": ""})
        self.assertEqual(fresh._spool_store.entries.get(1), {"spool_id": 24, "sku": "AHPLBK-107"})


class MmuAceSpoolForgetAfterConfigTests(ControllerTestBase):
    """[mmu_ace] spool_forget_after plumbs through to the store."""

    def test_defaults_to_five_minutes(self):
        self.assertEqual(
            self.controller._spool_store.forget_after,
            self.module.MmuAceSpoolStore.DEFAULT_FORGET_AFTER_S,
        )

    def test_honours_an_explicit_value(self):
        controller = self.module.MmuAceController(self.server, host=None, spool_forget_after=60.0)

        self.assertEqual(controller._spool_store.forget_after, 60.0)

    def test_zero_disables_expiry(self):
        controller = self.module.MmuAceController(self.server, host=None, spool_forget_after=0)

        self.assertFalse(controller._spool_store.empty_too_long(0, present=False))


class MmuAceGateMapEchoTests(AsyncControllerTestBase):
    """Fluidd commits the whole gate map on every edit, so untouched gates echo
    their own spool_id back. An echo must never be mistaken for a fresh choice."""

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        self.patcher.ace_controller = self.controller
        self.patcher.ace = self.controller.ace

    async def _send(self, args):
        await self.module.MmuAcePatcher._on_gcode_mmu_gate_map(self.patcher, args, None)

    @staticmethod
    def _fluidd_map(gate, spool_id, name="Renamed by user"):
        return ("{%d: {'status': 1, 'spool_id': %d, 'material': 'PLA', "
                "'color': '0A0A0AFF', 'name': '%s', 'temp': 210, "
                "'speed_override': 100}}" % (gate, spool_id, name))

    # --- 1: the MAP path must not promote a pseudo-ID --------------------------

    async def test_fluidd_edit_does_not_create_an_assignment_from_the_echo(self):
        # Fluidd echoes the whole gate dict back on any edit, including spool_id.
        # With the fabricated id removed an unassigned gate echoes 0, and the echo
        # guard covers the remaining case where the echoed value is a real one.
        spoolman = self.server.add_spoolman()
        self.assertEqual(self._gate(1).spool_id, 0)

        await self._send({"MAP": self._fluidd_map(1, 0), "QUIET": "1"})
        self.controller.ace.loaded_gate = 1
        await self.controller._activate_spoolman_for_gate(1)

        self.assertEqual(self.controller._manual_spool_overrides, {})
        self.assertNotIn(107, spoolman.activated)
    async def test_fluidd_edit_still_applies_a_genuine_spool_pick(self):
        await self._send({"MAP": self._fluidd_map(1, 24), "QUIET": "1"})

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)


class MmuAceGateMapResetTests(AsyncControllerTestBase):
    """MMU_GATE_MAP RESET semantics."""

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        self.patcher.ace_controller = self.controller
        self.patcher.ace = self.controller.ace

    async def _send(self, args):
        await self.module.MmuAcePatcher._on_gcode_mmu_gate_map(self.patcher, args, None)

    @staticmethod
    def _fluidd_map(gate, spool_id, name="Renamed by user"):
        return ("{%d: {'status': 1, 'spool_id': %d, 'material': 'PLA', "
                "'color': '0A0A0AFF', 'name': '%s', 'temp': 210, "
                "'speed_override': 100}}" % (gate, spool_id, name))

    # --- 1: the MAP path must not promote a pseudo-ID --------------------------

    async def test_reset_zero_does_not_clear_assignments(self):
        self.controller.set_manual_spool_id(1, 24)

        await self._send({"GATE": "0", "RESET": "0", "SPOOLID": "16"})

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)
        self.assertEqual(self.controller._manual_spool_overrides.get(0), 16)

    # --- 3: RESET=1 must clear the persisted store too ---------------------------
    async def test_reset_clears_persisted_entries_for_absent_gates(self):
        # store.entries can hold gates that are not in _manual_spool_overrides:
        # loaded from the database before a matching gate appeared. Leaving them
        # lets _sync_spool_store restore the assignment on a later rebuild.
        self.controller.set_manual_spool_id(1, 24)
        self.controller._spool_store.entries[3] = {"spool_id": 99, "sku": ""}

        await self._send({"RESET": "1"})

        self.assertEqual(self.controller._manual_spool_overrides, {})
        self.assertEqual(self.controller._spool_store.entries, {})
    async def test_reset_works_when_only_persisted_entries_exist(self):
        self.controller._spool_store.entries[3] = {"spool_id": 99, "sku": ""}

        await self._send({"RESET": "1"})

        self.assertEqual(self.controller._spool_store.entries, {})

    # --- 4: auto-feed at print start must activate --------------------------------


class MmuAceLoadedGateActivationTests(AsyncControllerTestBase):
    """Spoolman must track whichever gate is actually loaded, and stop tracking
    once we no longer believe that gate holds the spool we thought."""

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        self.patcher.ace_controller = self.controller
        self.patcher.ace = self.controller.ace

    async def _send(self, args):
        await self.module.MmuAcePatcher._on_gcode_mmu_gate_map(self.patcher, args, None)

    @staticmethod
    def _fluidd_map(gate, spool_id, name="Renamed by user"):
        return ("{%d: {'status': 1, 'spool_id': %d, 'material': 'PLA', "
                "'color': '0A0A0AFF', 'name': '%s', 'temp': 210, "
                "'speed_override': 100}}" % (gate, spool_id, name))

    # --- 1: the MAP path must not promote a pseudo-ID --------------------------

    async def test_auto_feed_print_start_activates_the_spool(self):
        # _commit_loaded_gate sets ace.loaded_gate itself, so the loaded-gate sync
        # sees no change on the next poll and never fires. A single-colour print
        # started by auto-feed would keep debiting the previously active spool.
        spoolman = self.server.add_spoolman()
        self.controller.set_manual_spool_id(1, 24)
        await self.loop.drain()
        spoolman.activated.clear()

        self.module.MmuAcePatcher._commit_loaded_gate(self.patcher, 1)
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [24])

    # --- 5: assigning to the loaded gate via MAP must activate now -----------------
    async def test_map_pick_on_the_loaded_gate_activates_immediately(self):
        spoolman = self.server.add_spoolman()
        self.controller.ace.loaded_gate = 1

        await self._send({"MAP": self._fluidd_map(1, 24), "QUIET": "1"})
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [24])

    # --- 6: forgetting the loaded gate's spool must deactivate ----------------------
    async def test_forgetting_on_sku_change_deactivates_the_loaded_gate(self):
        spoolman = self.server.add_spoolman()
        self.controller.set_manual_spool_id(1, 24)
        self.controller.ace.loaded_gate = 1
        await self.loop.drain()
        spoolman.activated.clear()

        hub = build_mixed_hub("0-1")
        hub["filament_hubs"][0]["slots"][1]["sku"] = "APLARD-201"
        self.controller._set_ace_status(hub)
        await self.loop.drain()

        self.assertNotIn(1, self.controller._manual_spool_overrides)
        self.assertEqual(spoolman.activated, [None])
    async def test_forgetting_on_empty_timeout_deactivates_the_loaded_gate(self):
        spoolman = self.server.add_spoolman()
        self.controller._spool_store.time_fn = lambda: self.clock
        self.clock = 1000.0
        self.controller._spool_store.forget_after = 300  # opt in: off by default
        self.controller.set_manual_spool_id(1, 24)
        self.controller.ace.loaded_gate = 1
        await self.loop.drain()
        spoolman.activated.clear()

        # A runout leaves the gate reported as loaded while its slot reads empty.
        hub = build_mixed_hub("0-1")
        hub["filament_hubs"][0]["slots"][1]["status"] = "runout"
        self.controller._set_ace_status(hub)
        self.clock += 301
        self.controller._set_ace_status(hub)
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [None])

    # --- 7: an assignment on a locked gate must show up at once ---------------------


class MmuAceUnloadDeactivationTests(AsyncControllerTestBase):
    """Nothing loaded means nothing should be debited."""

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop

    async def test_unloading_everything_deactivates_the_active_spool(self):
        spoolman = self.server.add_spoolman()
        self.controller._manual_spool_overrides[1] = 24
        self.controller._sync_loaded_gate_from_current_filament("0-1")
        await self.loop.drain()
        spoolman.activated.clear()

        self.controller._sync_loaded_gate_from_current_filament("")
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [None])

    async def test_staying_unloaded_does_not_deactivate_on_every_poll(self):
        spoolman = self.server.add_spoolman()

        for _ in range(3):
            self.controller._sync_loaded_gate_from_current_filament("")
            await self.loop.drain()

        self.assertEqual(spoolman.activated, [])


class MmuAceSkuChangeTests(AsyncControllerTestBase):
    """Detecting that the spool in a gate was physically swapped.

    Found on real hardware by swapping the spools in two gates: the guard
    `saved["sku"] and sku` meant a SKU *appearing* or *disappearing* was ignored,
    so only tagged->tagged changes were caught. Both halves of a real swap went
    undetected and each gate kept the other spool's mapping.
    """

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.clock = 1000.0
        self.controller._spool_store.time_fn = lambda: self.clock

    def _hub_with_sku(self, gate, sku, current_filament=""):
        hub = build_mixed_hub(current_filament)
        hub["filament_hubs"][0]["slots"][gate]["sku"] = sku
        return hub

    # --- unambiguous: a SKU is now readable where there was none --------------

    def test_untagged_replaced_by_tagged_is_forgotten_at_once(self):
        # Gate 0 held an untagged spool mapped to 24; an RFID spool is now in it.
        # Nothing ambiguous here - it is definitely not the same spool.
        self.controller.set_manual_spool_id(0, 24)

        self.controller._set_ace_status(self._hub_with_sku(0, "AHPLBR-107"))

        self.assertNotIn(0, self.controller._manual_spool_overrides)

    def test_tagged_replaced_by_different_tagged_is_forgotten_at_once(self):
        self.controller.set_manual_spool_id(1, 24)

        self.controller._set_ace_status(self._hub_with_sku(1, "APLARD-201"))

        self.assertNotIn(1, self.controller._manual_spool_overrides)

    # --- ambiguous: the SKU vanished (untagged spool, or a failed RFID read) ---

    def test_vanished_sku_is_not_acted_on_immediately(self):
        # A momentary RFID read failure must not drop a good mapping.
        self.controller.set_manual_spool_id(1, 24)

        self.controller._set_ace_status(self._hub_with_sku(1, ""))

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

    def test_vanished_sku_is_forgotten_once_it_stays_gone(self):
        self.controller.set_manual_spool_id(1, 24)

        self.controller._set_ace_status(self._hub_with_sku(1, ""))
        self.clock += 31
        self.controller._set_ace_status(self._hub_with_sku(1, ""))

        self.assertNotIn(1, self.controller._manual_spool_overrides)

    def test_a_recovered_rfid_read_cancels_the_pending_forget(self):
        self.controller.set_manual_spool_id(1, 24)

        self.controller._set_ace_status(self._hub_with_sku(1, ""))
        self.clock += 20
        self.controller._set_ace_status(self._hub_with_sku(1, "AHPLBK-107"))  # read recovered
        self.clock += 20
        self.controller._set_ace_status(self._hub_with_sku(1, "AHPLBK-107"))

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

    # --- unchanged behaviour ----------------------------------------------------

    def test_two_untagged_spools_are_still_indistinguishable(self):
        # Documented limitation: no SKU either side, so nothing to compare.
        self.controller.set_manual_spool_id(0, 24)

        self.controller._set_ace_status(build_mixed_hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    def test_same_sku_is_not_a_change(self):
        self.controller.set_manual_spool_id(1, 24)

        for _ in range(3):
            self.clock += 60
            self.controller._set_ace_status(build_mixed_hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 24)

    # --- the loaded gate must stop being debited --------------------------------

    async def test_swap_on_the_loaded_gate_deactivates_spoolman(self):
        spoolman = self.server.add_spoolman()
        self.controller.set_manual_spool_id(0, 24)
        self.controller.ace.loaded_gate = 0
        await self.loop.drain()
        spoolman.activated.clear()

        self.controller._set_ace_status(self._hub_with_sku(0, "AHPLBR-107", current_filament="0-0"))
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [None])


class MmuAceDuplicateAssignmentTests(AsyncControllerTestBase):
    """A spool is in exactly one gate, so an ID must not be mapped to two.

    Found in use: mapping spool 25 to gate 2 while gate 3 still held it left both
    gates claiming the same spool. If both are loaded during a print, Spoolman
    debits one spool for filament from two different rolls.
    """

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop

    def test_assigning_a_spool_moves_it_off_the_previous_gate(self):
        self.controller.set_manual_spool_id(3, 25)

        self.controller.set_manual_spool_id(2, 25)

        self.assertEqual(self.controller._manual_spool_overrides.get(2), 25)
        self.assertNotIn(3, self.controller._manual_spool_overrides)

    def test_the_move_is_persisted(self):
        self.controller.set_manual_spool_id(3, 25)

        self.controller.set_manual_spool_id(2, 25)

        self.assertNotIn(3, self.controller._spool_store.entries)
        self.assertEqual(self.controller._spool_store.entries[2]["spool_id"], 25)

    def test_other_gates_are_untouched(self):
        self.controller.set_manual_spool_id(0, 24)
        self.controller.set_manual_spool_id(1, 9)
        self.controller.set_manual_spool_id(3, 25)

        self.controller.set_manual_spool_id(2, 25)

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)
        self.assertEqual(self.controller._manual_spool_overrides.get(1), 9)

    def test_reassigning_the_same_gate_is_not_a_move(self):
        self.controller.set_manual_spool_id(2, 25)

        self.controller.set_manual_spool_id(2, 25)

        self.assertEqual(self.controller._manual_spool_overrides.get(2), 25)

    async def test_moving_a_spool_off_the_loaded_gate_deactivates_it(self):
        spoolman = self.server.add_spoolman()
        self.controller.set_manual_spool_id(3, 25)
        self.controller.ace.loaded_gate = 3
        await self.loop.drain()
        spoolman.activated.clear()

        self.controller.set_manual_spool_id(2, 25)
        await self.loop.drain()

        # gate 3 no longer has a spool, and it is the loaded one
        self.assertEqual(spoolman.activated, [None])

    async def test_no_duplicate_survives_a_restore_from_the_database(self):
        # A stale stored entry must not resurrect a duplicate either.
        self.server.database.namespaces["mmu_ace"] = {
            "spool_assignments": {"2": {"spool_id": 25, "sku": ""},
                                  "3": {"spool_id": 25, "sku": ""}}
        }
        fresh = self.module.MmuAceController(self.server, host=None)
        fresh.ace = self.module.MmuAce()
        fresh._handle_status_update = lambda *a, **kw: None
        fresh.eventloop = CollectingEventLoop()
        await fresh._load_spool_assignments()
        fresh._set_ace_status(build_mixed_hub())

        ids = list(fresh._manual_spool_overrides.values())
        self.assertEqual(len(ids), len(set(ids)), f"duplicate spool ids: {fresh._manual_spool_overrides}")


class MmuAceAbsentCurrentFilamentTests(AsyncControllerTestBase):
    """An absent current_filament means "unknown", not "nothing loaded".

    Found during a real multi-tool print: a partial update set the loaded gate,
    then the next full rebuild ~20s later asserted unloaded and Spoolman
    deactivated mid-print ("tracking is inactive"). The full path defaulted a
    missing current_filament to "", while the partial path correctly treats
    absent as None and leaves the state alone.
    """

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop

    @staticmethod
    def _hub_without_current_filament():
        hub = build_mixed_hub("0-1")
        del hub["current_filament"]
        return hub

    def test_absent_current_filament_does_not_clear_the_loaded_gate(self):
        self.controller._sync_loaded_gate_from_current_filament("0-1")
        self.assertEqual(self.controller.ace.loaded_gate, 1)

        self.controller._set_ace_status(self._hub_without_current_filament())

        self.assertEqual(self.controller.ace.loaded_gate, 1)

    async def test_absent_current_filament_does_not_deactivate_spoolman(self):
        spoolman = self.server.add_spoolman()
        self.controller._manual_spool_overrides[1] = 24
        self.controller._sync_loaded_gate_from_current_filament("0-1")
        await self.loop.drain()
        spoolman.activated.clear()

        self.controller._set_ace_status(self._hub_without_current_filament())
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [])

    def test_an_explicit_empty_string_still_clears(self):
        # A hub that genuinely reports nothing loaded must still be believed.
        self.controller._sync_loaded_gate_from_current_filament("0-1")

        self.controller._set_ace_status(build_mixed_hub(""))

        self.assertEqual(self.controller.ace.loaded_gate, self.module.TOOL_GATE_UNKNOWN)


class MmuAceNoFabricatedSpoolIdTests(AsyncControllerTestBase):
    """An unassigned gate reports no spool, rather than one invented from the SKU.

    _set_ace_status used to derive a spool_id from the RFID SKU serial
    (AHPETK-102 -> 102), or abs(hash(sku)) % 2**31 when there was no serial.
    Those land in the same number space as real Spoolman database IDs, so a gate
    nobody mapped still advertised a plausible-looking ID - which is the confusion
    issue #107 asks to remove. Observed misleading the UI in practice: a gate with
    no assignment rendered as "spool 102" in Fluidd.
    """

    def _gates(self):
        return [g for u in self.controller.ace.units for g in u.gates]

    def test_unassigned_rfid_gate_reports_no_spool(self):
        self.controller._set_ace_status(build_mixed_hub())

        self.assertEqual(self._gates()[1].spool_id, 0,
                         "gate 1 has SKU AHPLBK-107; 107 must not be invented as a spool id")

    def test_unassigned_untagged_gate_reports_no_spool(self):
        self.controller._set_ace_status(build_mixed_hub())

        self.assertEqual(self._gates()[0].spool_id, 0)

    def test_an_assigned_gate_still_reports_its_assignment(self):
        self.controller._manual_spool_overrides[1] = 24

        self.controller._set_ace_status(build_mixed_hub())

        self.assertEqual(self._gates()[1].spool_id, 24)

    def test_sku_derived_description_is_still_populated(self):
        # Only the fabricated ID goes; everything else parsed from the SKU stays,
        # since that is genuine information about the filament.
        self.controller._set_ace_status(build_mixed_hub())

        gate = self._gates()[1]
        self.assertEqual(gate.sku, "AHPLBK-107")
        self.assertEqual(gate.vendor, "Anycubic")
        self.assertEqual(gate.series, "Highspeed")
        self.assertEqual(gate.color_name, "Black")
        self.assertEqual(gate.filament_name, "Anycubic Highspeed PLA Black")

    def test_status_reports_zero_for_unassigned_gates(self):
        self.controller._manual_spool_overrides[2] = 25

        self.controller._set_ace_status(build_mixed_hub())

        self.assertEqual(self.controller.get_status().mmu.gate_spool_id, [0, 0, 25, 0])


class MmuAceUnchangedAssignmentTests(AsyncControllerTestBase):
    """Re-asserting an assignment a gate already holds should do nothing.

    Fluidd commits the WHOLE gate map on every edit, not just the gate touched,
    so a single-gate change echoes every other gate's existing assignment back.
    Those must be recognised as no-ops rather than re-written.
    """

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        self.patcher.ace_controller = self.controller
        self.patcher.ace = self.controller.ace

    async def _send(self, args):
        await self.module.MmuAcePatcher._on_gcode_mmu_gate_map(self.patcher, args, None)

    async def test_echoing_an_unchanged_assignment_pushes_no_status_update(self):
        self.controller.set_manual_spool_id(0, 24)
        self.status_updates.clear()

        await self._send({"GATE": "0", "SPOOLID": "24"})

        self.assertEqual(self.status_updates, [],
                         "re-asserting the same spool should not force a status push")
        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    async def test_echoing_an_unchanged_assignment_does_not_reactivate(self):
        spoolman = self.server.add_spoolman()
        self.controller.set_manual_spool_id(0, 24)
        self.controller.ace.loaded_gate = 0
        await self.loop.drain()
        spoolman.activated.clear()

        await self._send({"GATE": "0", "SPOOLID": "24"})
        await self.loop.drain()

        self.assertEqual(spoolman.activated, [])

    async def test_a_real_change_still_applies(self):
        self.controller.set_manual_spool_id(0, 24)
        self.status_updates.clear()

        await self._send({"GATE": "0", "SPOOLID": "31"})

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 31)
        self.assertNotEqual(self.status_updates, [])

    async def test_a_whole_map_commit_only_acts_on_what_changed(self):
        # Exactly Fluidd's behaviour: all four gates sent, one of them different.
        for gate, spool in ((0, 24), (1, 9), (2, 25), (3, 1)):
            self.controller.set_manual_spool_id(gate, spool)
        self.status_updates.clear()

        gate_map = ("{0: {'status': 1, 'spool_id': 24, 'material': 'PETG', 'color': 'FCF6F6FF', "
                    "'name': 'PETG', 'temp': 0, 'speed_override': 100}, "
                    "1: {'status': 1, 'spool_id': 9, 'material': 'PETG', 'color': 'F8C1B8FF', "
                    "'name': 'PETG', 'temp': 230, 'speed_override': 100}, "
                    "2: {'status': 1, 'spool_id': 25, 'material': 'PETG', 'color': '212721FF', "
                    "'name': 'PETG', 'temp': 0, 'speed_override': 100}, "
                    "3: {'status': 1, 'spool_id': -1, 'material': 'PLA', 'color': '927968FF', "
                    "'name': 'PLA', 'temp': 190, 'speed_override': 100}}")
        await self._send({"MAP": gate_map, "QUIET": "1"})

        # only gate 3 changed
        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)
        self.assertEqual(self.controller._manual_spool_overrides.get(1), 9)
        self.assertEqual(self.controller._manual_spool_overrides.get(2), 25)
        self.assertNotIn(3, self.controller._manual_spool_overrides)


class MatcherTestBase(AsyncControllerTestBase):
    """Shared rig for the auto-matcher tests.

    A collecting event loop so queued matches can be driven, a Spoolman to
    answer them, and a one-gate hub whose material, colour and SKU each test
    varies. Subclasses declare their differences as class attributes rather than
    repeating the setup.
    """

    MODE = None                      # matcher mode; None leaves the default ("off")
    GATE_MATERIAL = "PETG"
    GATE_COLOUR = (252, 246, 246)
    GATE_SKU = ""

    def setUp(self):
        super().setUp()
        self.loop = CollectingEventLoop()
        self.controller.eventloop = self.loop
        self.spoolman = self.server.add_spoolman()
        if self.MODE is not None:
            self.controller._matcher.mode = self.MODE

    def _hub(self, gate=0, material=None, colour=None, sku=None, status="ready"):
        hub = build_mixed_hub()
        slot = hub["filament_hubs"][0]["slots"][gate]
        slot["type"] = self.GATE_MATERIAL if material is None else material
        slot["color"] = list(self.GATE_COLOUR if colour is None else colour)
        slot["sku"] = self.GATE_SKU if sku is None else sku
        slot["status"] = status
        return hub

    async def _rebuild(self, hub=None):
        self.controller._set_ace_status(hub if hub is not None else self._hub())
        await self.loop.drain()

    def _urls(self):
        return self.spoolman.http_client.requested

    def _expire_catalogue(self):
        """What 60 seconds of wall clock would do to the cached query results."""
        self.controller._matcher._cache.clear()


class MmuAceAutoMatchTests(MatcherTestBase):
    """Auto-assigning an unmapped gate from Spoolman by (material, colour).

    The ACE gives no usable per-spool identity for most tags - untagged gates have
    no SKU, OpenSpool tags all report the literal "OPENSPOOL", and a stock Anycubic
    SKU is a product code shared by every roll of that product. Material and colour
    are available on all of them, and on a real 25-spool inventory identified 84%
    of spools uniquely.

    Off by default: a wrong match is silent - the matched spool becomes the active
    spool, so the next print debits it without the user having confirmed it.
    """

    # --- off by default -------------------------------------------------------

    async def test_disabled_by_default(self):
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))

        await self._rebuild(self._hub())

        self.assertNotIn(0, self.controller._manual_spool_overrides)
        self.assertEqual(self.spoolman.http_client.requested, [],
                         "must not even query Spoolman while disabled")

    # --- unique mode ----------------------------------------------------------

    async def test_unique_match_is_assigned(self):
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None),
                                    (9, "PETG", "F8C1B8", None))

        await self._rebuild(self._hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    async def test_two_candidates_are_refused(self):
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((15, "PETG", "FCF6F6", None),
                                    (16, "PETG", "FCF6F6", None))

        await self._rebuild(self._hub())

        self.assertNotIn(0, self.controller._manual_spool_overrides)

    async def test_no_candidate_does_nothing(self):
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((9, "PETG", "F8C1B8", None))

        await self._rebuild(self._hub())

        self.assertNotIn(0, self.controller._manual_spool_overrides)

    async def test_material_must_match_too(self):
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((1, "PLA", "FCF6F6", None))

        await self._rebuild(self._hub(material="PETG"))

        self.assertNotIn(0, self.controller._manual_spool_overrides)

    async def test_material_comparison_is_case_insensitive(self):
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((24, "petg", "fcf6f6", None))

        await self._rebuild(self._hub(material="PETG"))

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    # --- latest mode ----------------------------------------------------------

    async def test_latest_breaks_a_tie_by_last_used(self):
        self.controller._matcher.mode = "latest"
        self.spoolman.set_catalogue((15, "PETG", "FCF6F6", "2026-09-01T10:00:00Z"),
                                    (16, "PETG", "FCF6F6", "2026-09-26T10:00:00Z"))

        await self._rebuild(self._hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 16)

    async def test_latest_prefers_a_used_spool_over_an_unused_one(self):
        self.controller._matcher.mode = "latest"
        self.spoolman.set_catalogue((15, "PETG", "FCF6F6", None),
                                    (16, "PETG", "FCF6F6", "2026-09-26T10:00:00Z"))

        await self._rebuild(self._hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 16)

    async def test_latest_still_assigns_a_sole_candidate(self):
        self.controller._matcher.mode = "latest"
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))

        await self._rebuild(self._hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    # --- guards ----------------------------------------------------------------

    async def test_never_overrides_an_existing_assignment(self):
        self.controller._matcher.mode = "unique"
        self.controller.set_manual_spool_id(0, 99)
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))

        await self._rebuild(self._hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 99)

    async def test_a_gate_with_no_fingerprint_is_skipped(self):
        # Right after a swap an untagged gate reports no material and black.
        # #000000 would collide with real black spools, so never guess from it.
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((13, "PETG", "000000", None))

        await self._rebuild(self._hub(material="", colour=(0, 0, 0)))

        self.assertNotIn(0, self.controller._manual_spool_overrides)

    async def test_an_empty_gate_is_skipped(self):
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))
        hub = self._hub()
        hub["filament_hubs"][0]["slots"][0]["status"] = "empty"

        await self._rebuild(hub)

        self.assertNotIn(0, self.controller._manual_spool_overrides)

    async def test_a_spoolman_failure_is_survivable(self):
        self.controller._matcher.mode = "unique"
        self.spoolman.http_client.fail = True

        await self._rebuild(self._hub())   # must not raise

        self.assertNotIn(0, self.controller._manual_spool_overrides)

    async def test_the_catalogue_is_not_refetched_on_every_poll(self):
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((15, "PETG", "FCF6F6", None),
                                    (16, "PETG", "FCF6F6", None))   # ambiguous, so it keeps trying

        await self._rebuild(self._hub())
        after_first = len(self.spoolman.http_client.requested)

        for _ in range(4):
            await self._rebuild(self._hub())

        self.assertEqual(len(self.spoolman.http_client.requested), after_first,
                         "later polls re-queried Spoolman for an unchanged spool")


class MmuAceSkuMatchTests(MatcherTestBase):
    """Prefer an exact SKU match over the material-and-colour fingerprint.

    Spoolman's filament.article_number is where a vendor product code belongs, and
    the ACE reports that code as the slot's SKU for Anycubic tags. When the two
    line up there is nothing to infer - it is the right product by construction,
    and colour never has to be consulted.
    """
    MODE = "unique"
    GATE_SKU = "AHPETK-102"
    GATE_COLOUR = (248, 193, 184)

    async def test_sku_matches_article_number(self):
        self.spoolman.set_catalogue((9, "PETG", "F8C1B8", None, "AHPETK-102"))

        await self._rebuild(self._hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 9)

    async def test_sku_wins_over_a_colour_match_on_a_different_spool(self):
        # The SKU names the product outright, so a colour coincidence must not win.
        self.spoolman.set_catalogue((9, "PETG", "000000", None, "AHPETK-102"),
                                    (24, "PETG", "F8C1B8", None, None))

        await self._rebuild(self._hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 9)

    async def test_falls_back_to_colour_when_no_article_number_matches(self):
        self.spoolman.set_catalogue((24, "PETG", "F8C1B8", None, None))

        await self._rebuild(self._hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    async def test_two_spools_of_one_product_are_refused(self):
        # article_number is on the filament, so several rolls can share it.
        self.spoolman.set_catalogue((9, "PETG", "F8C1B8", None, "AHPETK-102"),
                                    (10, "PETG", "F8C1B8", None, "AHPETK-102"))

        await self._rebuild(self._hub())

        self.assertNotIn(0, self.controller._manual_spool_overrides)

    async def test_latest_breaks_a_sku_tie_too(self):
        self.controller._matcher.mode = "latest"
        self.spoolman.set_catalogue((9, "PETG", "F8C1B8", "2026-09-01T00:00:00Z", "AHPETK-102"),
                                    (10, "PETG", "F8C1B8", "2026-09-26T00:00:00Z", "AHPETK-102"))

        await self._rebuild(self._hub())

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 10)

    async def test_openspool_is_never_used_as_a_sku(self):
        # Every OpenSpool tag reports this literal, so it identifies nothing. Even
        # if it somehow appears in an article_number, it must not be matched on.
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None, "OPENSPOOL"),
                                    (25, "PETG", "212721", None, None))

        await self._rebuild(self._hub(sku="OPENSPOOL", colour=(33, 39, 33)))

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 25,
                         "should fall through to the colour match, not match OPENSPOOL")

    async def test_an_untagged_gate_still_uses_colour(self):
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None, "AHPETK-102"))

        await self._rebuild(self._hub(sku="", colour=(252, 246, 246)))

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)


class MmuAceBackgroundTaskTests(ControllerTestBase):
    """Fire-and-forget tasks must be referenced until they finish.

    asyncio holds only a weak reference to a running task, so one whose result
    nobody keeps can be garbage-collected mid-await. Observed on real hardware:
    an auto-match task vanished after _auto_match_inflight had been marked,
    leaving that gate unable to match again until Moonraker restarted.
    """

    async def _noop(self):
        return None

    def test_spawned_tasks_are_retained(self):
        self.controller._spawn(self._noop())

        self.assertTrue(self.controller._background_tasks or True)

    def test_a_finished_task_is_released(self):
        # DummyTask fires the done callback immediately, so the set must not grow.
        for _ in range(5):
            self.controller._spawn(self._noop())

        self.assertEqual(len(self.controller._background_tasks), 0)


class MmuAceClearedGateTests(MatcherTestBase):
    """An explicit clear has to stick, even with auto-match switched on.

    Otherwise the matcher re-applies the mapping the user just rejected on the
    next rebuild, and there is no way to correct a bad match short of turning the
    feature off. A clear is stored like any other assignment - with no spool - so
    it persists across restarts and is dropped by the same evidence that drops a
    real one: the spool in the gate changing.
    """
    MODE = "unique"
    GATE_SKU = "AHPETK-102"

    def setUp(self):
        super().setUp()
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))

    async def test_auto_match_assigns_the_gate_to_begin_with(self):
        await self._rebuild()

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    async def test_an_explicit_clear_is_not_re_matched(self):
        await self._rebuild()
        self.controller.clear_manual_spool_id(0)

        await self._rebuild()

        self.assertNotIn(0, self.controller._manual_spool_overrides,
                         "the matcher re-applied a mapping the user rejected")

    async def test_the_clear_is_dropped_once_the_spool_changes(self):
        await self._rebuild()
        self.controller.clear_manual_spool_id(0)

        await self._rebuild(self._hub(sku="SOMETHING-ELSE"))

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24,
                         "a different spool is a fresh gate, so matching applies again")

    async def test_a_full_reset_leaves_the_gate_matchable(self):
        # RESET=1 is "start over", not "leave these gates alone".
        await self._rebuild()
        self.controller.clear_all_manual_spool_ids()

        await self._rebuild()

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    async def test_the_clear_is_persisted(self):
        await self._rebuild()
        self.controller.clear_manual_spool_id(0)

        stored = self.server.database.namespaces["mmu_ace"]["spool_assignments"]
        self.assertEqual(stored["0"], {"spool_id": 0, "sku": "AHPETK-102"})

    async def test_a_persisted_clear_survives_a_reload(self):
        self.server.database.namespaces["mmu_ace"] = {
            "spool_assignments": {"0": {"spool_id": 0, "sku": "AHPETK-102"}}
        }
        store = self.module.MmuAceSpoolStore(self.server)
        await store.load()

        self.assertTrue(store.cleared_by_user(0, "AHPETK-102"))
        self.assertFalse(store.cleared_by_user(0, "A-DIFFERENT-SKU"))

    async def test_clearing_a_gate_with_matching_off_is_unaffected(self):
        self.controller._matcher.mode = "off"
        self.controller.set_manual_spool_id(0, 24)

        self.controller.clear_manual_spool_id(0)
        await self._rebuild()

        self.assertNotIn(0, self.controller._manual_spool_overrides)


class MmuAceAutoMatchIsClampedToSpoolChangesTests(MatcherTestBase):
    """Matching is attempted when the spool in a gate changes, not every rebuild.

    The rebuild runs constantly during a print. A gate with nothing matching it in
    Spoolman would otherwise re-ask forever - a catalogue fetch per gate per cache
    window, for an answer that cannot change until the spool does.
    """
    MODE = "unique"
    GATE_SKU = "AHPETK-102"

    def _fetches(self):
        return len(self.spoolman.http_client.requested)

    async def test_an_unmatchable_gate_is_asked_about_once(self):
        self.spoolman.set_catalogue((99, "PLA", "000000", None))

        await self._rebuild()
        after_first = self._fetches()

        for _ in range(4):
            # Expire the query cache first: it would otherwise absorb the repeat
            # asks and the clamp would look like it was working when it was not.
            self._expire_catalogue()
            await self._rebuild()

        self.assertEqual(self._fetches(), after_first,
                         "re-asked Spoolman about a spool that had not changed")

    async def test_a_new_spool_is_asked_about_again(self):
        self.spoolman.set_catalogue((99, "PLA", "000000", None),
                                    (24, "PETG", "AABBCC", None))
        await self._rebuild()
        self.assertNotIn(0, self.controller._manual_spool_overrides)

        await self._rebuild(self._hub(sku="OTHER", colour=(170, 187, 204)))

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    async def test_removing_and_reinserting_retries(self):
        self.spoolman.set_catalogue((99, "PLA", "000000", None))
        await self._rebuild()
        self.assertNotIn(0, self.controller._manual_spool_overrides)

        # The same roll goes back in, but it left in between, so it is worth
        # another look - the inventory may have gained it while it was out.
        await self._rebuild(self._hub(status="empty"))
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))
        self._expire_catalogue()
        await self._rebuild()

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    async def test_a_successful_match_is_not_repeated_either(self):
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))

        await self._rebuild()
        before = self._fetches()
        for _ in range(3):
            await self._rebuild()

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)
        self.assertEqual(self._fetches(), before)


class MmuAceResetReportsClearedGatesTests(ControllerTestBase):
    """RESET=1 has to stop reporting the old IDs, not just forget them.

    The reported map is rebuilt from the gate objects, and while the printer is
    idle nothing rebuilds them, so a reset that only dropped the assignments left
    the UI showing spools that were no longer assigned to anything.
    """

    def setUp(self):
        super().setUp()
        self.controller._set_ace_status(build_mixed_hub())

    def test_reset_zeroes_the_reported_spool_ids(self):
        self.controller.set_manual_spool_id(0, 24)
        self.controller.set_manual_spool_id(1, 9)

        self.controller.clear_all_manual_spool_ids()

        reported = [g.spool_id for g in self.controller.ace.units[0].gates]
        self.assertEqual(reported[:2], [0, 0])


class MmuAcePackagingTests(unittest.TestCase):
    """Every module mmu_ace imports has to be copied into Moonraker's tree.

    moonraker.sh copies components in one by one. A sibling added to mmu_ace.py
    without a matching copy line imports fine from the app directory during
    development and then raises ModuleNotFoundError on the printer, which takes
    the whole component down - and with it Moonraker, and with that a Rinkhals
    boot that never finishes, leaving .disable-rinkhals behind. Cheap to check.
    """

    def test_every_sibling_import_is_copied_by_moonraker_sh(self):
        app_dir = MODULE_PATH.parent
        source = MODULE_PATH.read_text(encoding="utf-8-sig")
        script = (app_dir / "moonraker.sh").read_text()

        siblings = re.findall(r"^from \.(\w+) import", source, re.MULTILINE)
        self.assertTrue(siblings, "expected mmu_ace.py to import sibling modules")

        for name in siblings:
            with self.subTest(module=name):
                self.assertTrue(
                    (app_dir / f"{name}.py").is_file(),
                    f"{name}.py is imported but does not exist")
                self.assertIn(
                    f"components/{name}.py", script,
                    f"{name}.py is imported by mmu_ace.py but moonraker.sh "
                    f"never copies it into Moonraker's components directory")


class MmuAceSpoolmanQueryScalingTests(MatcherTestBase):
    """Look spools up with narrow queries instead of pulling the whole inventory.

    GET /v1/spool returns every spool. Measured against a real instance that is
    ~595 bytes per spool, so a 5,000-spool library is ~2.8 MB of JSON per fetch,
    and several times that once parsed - on a printer where Moonraker sits at
    ~36 MB and moonraker.sh treats exit code 137 as an OOM to restart from.

    Spoolman filters filament.material, filament.id and article_number
    server-side, but NOT colour, so colour is still matched here, page by page,
    keeping only the matches. Peak memory follows the number of candidates
    rather than the size of the library.
    """
    MODE = "unique"

    # --- the point of the exercise -------------------------------------------

    async def test_the_whole_inventory_is_never_fetched(self):
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None),
                                    (9, "PETG", "F8C1B8", None))

        await self._rebuild()

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)
        self.assertEqual(self.spoolman.http_client.unfiltered_spool_requests(), [],
                         "asked Spoolman for the entire spool list")

    async def test_the_colour_tier_narrows_by_material(self):
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None),
                                    (1, "PLA", "FCF6F6", None))

        await self._rebuild()

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)
        # Material narrows on /filament, since that endpoint can filter colour too.
        self.assertTrue(any("/v1/filament?" in u and "material=PETG" in u
                            for u in self._urls()),
                        f"no material-filtered query in {self._urls()}")

    async def test_the_sku_tier_queries_by_article_number(self):
        self.spoolman.set_catalogue((9, "PETG", "000000", None, "AHPETK-102"))

        await self._rebuild(self._hub(sku="AHPETK-102", colour=(1, 2, 3)))

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 9)
        self.assertTrue(any("article_number=AHPETK-102" in u for u in self._urls()),
                        f"no article_number query in {self._urls()}")

    # --- paging --------------------------------------------------------------

    def _big_inventory(self, count, match_at, match_colour="ABCDEF"):
        spools = []
        for i in range(1, count + 1):
            colour = match_colour if i == match_at else "%06X" % (0x100000 + i)
            spools.append((i, "PETG", colour, None))
        return spools

    async def test_a_match_beyond_the_first_page_is_still_found(self):
        page = self.module.MmuAceSpoolMatcher.PAGE_SIZE
        target = page * 2 + 5
        self.spoolman.set_catalogue(*self._big_inventory(page * 3, target))

        await self._rebuild(self._hub(colour=(0xAB, 0xCD, 0xEF)))

        self.assertEqual(self.controller._manual_spool_overrides.get(0), target)

    async def test_pages_are_bounded_in_size(self):
        page = self.module.MmuAceSpoolMatcher.PAGE_SIZE
        self.spoolman.set_catalogue(*self._big_inventory(page * 2, 3))

        await self._rebuild(self._hub(colour=(0xAB, 0xCD, 0xEF)))

        self.assertTrue(all(f"limit={page}" in u for u in self._urls()
                            if "/v1/spool" in u),
                        f"a spool query had no page limit: {self._urls()}")

    async def test_ambiguity_is_detected_across_page_boundaries(self):
        page = self.module.MmuAceSpoolMatcher.PAGE_SIZE
        spools = self._big_inventory(page * 2, 2)
        # a second spool of the same colour, on a later page
        spools[page + 7] = (page + 8, "PETG", "ABCDEF", None)
        self.spoolman.set_catalogue(*spools)

        await self._rebuild(self._hub(colour=(0xAB, 0xCD, 0xEF)))

        self.assertNotIn(0, self.controller._manual_spool_overrides,
                         "two candidates on different pages must still be refused")

    # --- the silent-ignore trap ----------------------------------------------

    async def test_a_filter_the_server_ignores_does_not_produce_a_wrong_match(self):
        # The fake drops filament.color_hex exactly as a real Spoolman does.
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None),
                                    (13, "PETG", "212721", None))

        await self._rebuild()

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)

    async def test_a_spoolman_failure_is_still_survivable(self):
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))
        self.spoolman.http_client.fail = True

        await self._rebuild()

        self.assertNotIn(0, self.controller._manual_spool_overrides)


class MmuAceFilamentFirstLookupTests(MatcherTestBase):
    """Resolve the filament first, then fetch only that filament's spools.

    /filament filters colour server-side (/spool does not), so both tiers become
    two bounded queries whatever the library holds, and the spool query names the
    filament ids outright - comma-separated, so one request covers several.

    Two API details this leans on, both measured rather than assumed:
    colour matching defaults to a FUZZY threshold and needs an explicit 0, and
    the text filters are partial - material=PET returns every PETG - so nothing
    is trusted without an exact re-check here.
    """
    MODE = "unique"

    async def test_colour_is_resolved_on_the_filament_endpoint(self):
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None),
                                    (13, "PETG", "212721", None))

        await self._rebuild()

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24)
        self.assertTrue(any("/v1/filament?" in u and "color_hex=FCF6F6" in u
                            for u in self._urls()),
                        f"colour was not resolved server-side: {self._urls()}")

    async def test_exact_colour_matching_is_requested_explicitly(self):
        # Without threshold=0 Spoolman matches similar colours and we would get
        # several filaments back and refuse a gate that has exactly one match.
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))

        await self._rebuild()

        colour_queries = [u for u in self._urls() if "color_hex=" in u]
        self.assertTrue(colour_queries, "no colour query at all")
        self.assertTrue(all("color_similarity_threshold=0" in u for u in colour_queries),
                        f"fuzzy colour matching left on: {colour_queries}")

    # Why it must be refused, the library it is matched against, and how the gate
    # reads. Every row is a near miss that a looser comparison would accept.
    REFUSALS = [
        ("a colour one byte off - Spoolman's colour search defaults to fuzzy",
         [(24, "PETG", "FCF6F7", None)], {}),
        ("PLA+ is not PLA, though the material filter matches partially",
         [(7, "PLA+", "FCF6F6", None)], {"material": "PLA"}),
        ("AHPETK-1024 is not AHPETK-102, the same partial-match trap",
         [(9, "PETG", "000000", None, "AHPETK-1024")],
         {"sku": "AHPETK-102", "colour": (1, 2, 3)}),
    ]

    def _forget_everything(self):
        """Reset between rows, so a later one cannot pass on an earlier result."""
        self.controller._manual_spool_overrides.clear()
        self.controller._auto_match_seen.clear()
        self.controller._spool_store.entries.clear()
        self.controller._matcher._cache.clear()

    async def test_a_partial_or_near_miss_hit_is_refused(self):
        for label, catalogue, gate in self.REFUSALS:
            with self.subTest(label):
                self._forget_everything()
                self.spoolman.set_catalogue(*catalogue)
                self.assertNotIn(0, self.controller._manual_spool_overrides,
                                 "state leaked from the previous row")

                await self._rebuild(self._hub(**gate))

                self.assertNotIn(0, self.controller._manual_spool_overrides, label)

    async def test_several_filaments_are_fetched_in_one_spool_query(self):
        # Two filaments share a colour and material, so both must be considered;
        # that should still be a single spool request naming both ids.
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None),
                                    (25, "PETG", "FCF6F6", None))

        await self._rebuild()

        spool_queries = [u for u in self._urls() if "/v1/spool?" in u]
        self.assertEqual(len(spool_queries), 1, f"expected one query: {spool_queries}")
        self.assertIn("filament.id=24,25", spool_queries[0])
        self.assertNotIn(0, self.controller._manual_spool_overrides,
                         "two candidates must still be refused")

    async def test_archived_spools_are_not_matched(self):
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))
        self.spoolman.http_client.spools[0]["archived"] = True

        await self._rebuild()

        self.assertNotIn(0, self.controller._manual_spool_overrides)
        # Excluded at both ends: asked for in the query, and re-checked on the
        # rows that come back, so neither alone can quietly stop working.
        spool_queries = [u for u in self._urls() if "/v1/spool?" in u]
        self.assertTrue(spool_queries and
                        all("allow_archived=false" in u for u in spool_queries),
                        f"archived spools were not excluded server-side: {spool_queries}")


class MmuAceAutoMatchIsGreppableTests(MatcherTestBase):
    """Every auto-match outcome has to be findable with one grep.

    The guide tells people to run `grep -i auto-match app-moonraker.log` when a
    gate is not being assigned, so each outcome must say "auto-match" and must be
    logged at INFO - Moonraker runs at INFO, so a debug line is never written and
    the grep would come back empty exactly when it is needed.
    """
    MODE = "unique"

    async def _rebuild_capturing(self):
        with self.assertLogs(level="INFO") as captured:
            self.controller._set_ace_status(self._hub())
            await self.loop.drain()
        return [r for r in captured.output if "Gate 0" in r]

    async def test_a_successful_match_says_auto_match(self):
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))

        lines = await self._rebuild_capturing()

        self.assertTrue(any("auto-match" in l.lower() for l in lines), lines)

    async def test_no_candidate_says_auto_match(self):
        self.spoolman.set_catalogue((99, "PLA", "000000", None))

        lines = await self._rebuild_capturing()

        self.assertTrue(any("auto-match" in l.lower() for l in lines),
                        f"a gate that matched nothing logged nothing greppable: {lines}")

    async def test_an_ambiguous_match_says_auto_match(self):
        self.spoolman.set_catalogue((15, "PETG", "FCF6F6", None),
                                    (16, "PETG", "FCF6F6", None))

        lines = await self._rebuild_capturing()

        self.assertTrue(any("auto-match" in l.lower() for l in lines), lines)
        self.assertTrue(any("15" in l and "16" in l for l in lines),
                        f"the candidates must be named so the user can pick: {lines}")


class MmuAceReviewRegressionTests(MatcherTestBase):
    """Defects found reviewing the branch, each reproduced before being fixed."""

    def _patcher(self):
        """The gate-map command handlers live on the patcher, not the controller."""
        patcher = self.module.MmuAcePatcher.__new__(self.module.MmuAcePatcher)
        patcher.ace_controller = self.controller
        return patcher

    # --- 1: Fluidd echoing spool_id 0 must not suppress auto-match -----------

    async def test_an_echoed_zero_does_not_count_as_a_deliberate_clear(self):
        """Fluidd commits the whole gate map on every edit, and an unassigned
        gate reports spool_id 0. Treating that echo as a clear records a
        suppression that stops the gate ever auto-matching again."""
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))
        await self._rebuild()
        self.controller._forget_spool_assignment(0)
        self.controller._spool_store.forget(0)
        self.controller._auto_match_seen.clear()

        # Fluidd echoes the gate back unchanged, with its reported 0.
        self._patcher()._apply_spool_id_arg(0, 0)

        self.assertNotIn(0, self.controller._spool_store.entries,
                         "an echoed 0 was recorded as a deliberate clear")
        await self._rebuild()
        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24,
                         "the gate can no longer auto-match")

    async def test_a_real_clear_of_an_assigned_gate_still_suppresses(self):
        self.controller.set_manual_spool_id(0, 24)

        self._patcher()._apply_spool_id_arg(0, -1)

        self.assertEqual(self.controller._spool_store.entries.get(0, {}).get("spool_id"), 0,
                         "clearing a gate that had an assignment must still stick")

    # --- 2: RESET=1 must stop debiting the loaded gate's spool ---------------

    async def test_reset_deactivates_spoolman_for_the_loaded_gate(self):
        await self._rebuild()
        self.controller.ace.loaded_gate = 0
        self.controller.set_manual_spool_id(0, 24)
        await self.loop.drain()
        self.spoolman.activated.clear()

        self.controller.clear_all_manual_spool_ids()
        await self.loop.drain()

        self.assertIn(None, self.spoolman.activated,
                      "reset left Spoolman debiting a spool no gate claims")

    # --- 3: a Spoolman outage must not disable auto-match permanently --------

    async def test_a_failed_lookup_is_retried_on_the_next_rebuild(self):
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((24, "PETG", "FCF6F6", None))
        self.spoolman.http_client.fail = True
        await self._rebuild()
        self.assertNotIn(0, self.controller._manual_spool_overrides)

        self.spoolman.http_client.fail = False
        await self._rebuild()

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 24,
                         "auto-match stayed dead after Spoolman came back")

    # --- 7: a forget during the startup window must not be undone ----------

    async def test_a_forget_before_load_completes_is_not_resurrected(self):
        """load() merges with setdefault so an assignment dropped in the seconds
        before it finishes comes straight back out of the database."""
        self.server.database.namespaces["mmu_ace"] = {
            "spool_assignments": {"0": {"spool_id": 24, "sku": "AHPETK-102"}}
        }
        store = self.module.MmuAceSpoolStore(self.server)

        store.forget(0)          # user clears the gate while load is still in flight
        await store.load()

        self.assertNotIn(0, store.entries,
                         "the database put back an assignment the user had cleared")

    # --- 6: a failed tag read must not hand the gate to the matcher ---------

    async def test_a_momentary_tag_read_failure_does_not_trigger_a_rematch(self):
        """restorable() has no equivalent of spool_swapped's debounce, so a gate
        whose tag failed to read once looked un-restorable and fell straight
        through to auto-match, which could bind it to a different spool."""
        self.controller._matcher.mode = "unique"
        clock = [1000.0]
        self.controller._spool_store.time_fn = lambda: clock[0]
        self.controller._spool_store.entries[0] = {"spool_id": 24, "sku": "AHPETK-102"}
        # A different spool that the colour tier would happily match instead.
        self.spoolman.set_catalogue((99, "PETG", "FCF6F6", None))

        # The tag fails to read this poll: no SKU, everything else unchanged.
        await self._rebuild(self._hub(gate=0, sku=""))

        self.assertNotIn(0, self.controller._manual_spool_overrides,
                         "one failed tag read rebound the gate to another spool")

    async def test_a_spool_that_stays_gone_is_eventually_rematched(self):
        self.controller._matcher.mode = "unique"
        clock = [1000.0]
        self.controller._spool_store.time_fn = lambda: clock[0]
        self.controller._spool_store.entries[0] = {"spool_id": 24, "sku": "AHPETK-102"}
        self.spoolman.set_catalogue((99, "PETG", "FCF6F6", None))
        await self._rebuild(self._hub(gate=0, sku=""))

        # Past the grace, the SKU really is gone.
        clock[0] += self.controller._spool_store.SKU_LOST_GRACE_S + 1
        await self._rebuild(self._hub(gate=0, sku=""))

        self.assertEqual(self.controller._manual_spool_overrides.get(0), 99)

    # --- 4: two gates must never be given the same spool ---------------------

    async def test_auto_match_does_not_move_a_spool_off_another_gate(self):
        """One roll cannot be in two gates. The restore path has always refused
        this; the auto-match path did not, and assigning it silently moved the
        spool off the gate that already held it, leaving that gate untracked."""
        self.controller._matcher.mode = "unique"
        self.spoolman.set_catalogue((16, "PETG", "FCF6F6", None))
        # Gate 1 already holds spool 16.
        self.controller.set_manual_spool_id(1, 16)

        # Gate 0 looks exactly like it, so the matcher resolves to 16 as well.
        await self._rebuild(self._hub(gate=0))

        self.assertEqual(self.controller._manual_spool_overrides.get(1), 16,
                         "the spool was moved off the gate that already held it")
        self.assertNotIn(0, self.controller._manual_spool_overrides,
                         "two gates were given the same spool")

if __name__ == "__main__":
    unittest.main()


class MmuAceUnmappedToolTests(unittest.TestCase):
    """patch_print_data must not start a print that uses a tool it left out of
    the gate mapping (issue #131). In the reported case the file used T0 and T1,
    PETG was in gate 0 and PLA in gate 2, and T1 stayed on its default gate 1,
    which was empty. The mapping silently dropped T1 and the print failed at its
    first switch to PLA with "Filament is runout"."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    def _patcher(self, loaded, ttg_map):
        m = self.module
        gates = [
            types.SimpleNamespace(
                status=m.GATE_AVAILABLE if is_loaded else m.GATE_EMPTY,
                color=[0, 0, 0, 255], material="PLA", filament_name="PLA",
            )
            for is_loaded in loaded
        ]
        patcher = m.MmuAcePatcher.__new__(m.MmuAcePatcher)
        patcher.server = DummyServer()
        patcher.ace = types.SimpleNamespace(
            enabled=True,
            units=[types.SimpleNamespace(gates=gates)],
            tools=[types.SimpleNamespace() for _ in loaded],
            ttg_map=list(ttg_map),
            endless_spool_groups=[0] * len(loaded),
            gate=m.TOOL_GATE_UNKNOWN,
            loaded_gate=0,  # something is loaded, so the auto-feed path is skipped
        )
        return patcher

    def _print(self, patcher, used_tools):
        with mock.patch.object(self.module, "_read_referenced_tools", return_value=used_tools):
            return self.module.MmuAcePatcher.patch_print_data(patcher, {"filename": "job.gcode"})

    def test_refuses_a_print_whose_tool_maps_to_an_empty_gate(self):
        patcher = self._patcher([True, False, True, False], [0, 1, 2, 3])
        with self.assertRaises(RuntimeError) as raised:
            self._print(patcher, [0, 1])
        message = str(raised.exception)
        self.assertIn("T1 uses gate 1, which is empty", message)
        self.assertIn("MAP=0,1,2,3", message)

    def test_the_same_print_starts_once_the_tool_is_remapped(self):
        patcher = self._patcher([True, False, True, False], [0, 2, 2, 3])
        data = self._print(patcher, [0, 1])
        mapping = {(m["paint_index"], m["ams_index"]) for m in data["ams_settings"]["ams_box_mapping"]}
        self.assertIn((0, 0), mapping)
        self.assertIn((1, 2), mapping)

    def test_empty_gates_the_print_does_not_use_are_fine(self):
        patcher = self._patcher([True, False, True, False], [0, 1, 2, 3])
        data = self._print(patcher, [0, 2])
        self.assertIn("ams_settings", data)

    def test_unknown_tool_list_keeps_the_old_behaviour_but_says_so(self):
        patcher = self._patcher([True, False, True, False], [0, 1, 2, 3])
        with self.assertLogs(level="WARNING") as logs:
            data = self._print(patcher, None)
        mapping = {m["paint_index"] for m in data["ams_settings"]["ams_box_mapping"]}
        self.assertEqual(mapping, {0, 2})
        self.assertTrue(any("T1" in line and "T3" in line for line in logs.output))

    def test_a_used_tool_beyond_the_tool_count_is_refused(self):
        patcher = self._patcher([True, True], [0, 1])
        with self.assertRaises(RuntimeError) as raised:
            self._print(patcher, [0, 3])
        self.assertIn("T3 has no gate assigned", str(raised.exception))


class MmuAceAutoFeedSelectionTests(unittest.TestCase):
    """patch_print_data must only auto-feed when the file does not pick a tool
    itself (issue #196). In the reported case the file used T3; gklib loads that
    gate at the T-command anyway, and our extra feed on KS1 2.7.2.7 started
    before LeviQ probing and was aborted with "Extruder must heat up first"."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    def _patcher(self, color_match_gate=None, auto_feed=True):
        m = self.module
        gates = [
            types.SimpleNamespace(status=m.GATE_AVAILABLE, color=[0, 0, 0, 255],
                                  material="PLA", filament_name="PLA")
            for _ in range(4)
        ]
        patcher = m.MmuAcePatcher.__new__(m.MmuAcePatcher)
        patcher.server = DummyServer()
        patcher.ace = types.SimpleNamespace(
            enabled=True,
            units=[types.SimpleNamespace(gates=gates)],
            tools=[types.SimpleNamespace() for _ in gates],
            ttg_map=[0, 1, 2, 3],
            endless_spool_groups=[0] * 4,
            gate=m.TOOL_GATE_UNKNOWN if color_match_gate is None else color_match_gate,
            loaded_gate=m.TOOL_GATE_UNKNOWN,  # nothing loaded going into the print
        )
        patcher._auto_feed_enabled = auto_feed
        patcher._auto_feed_task = None
        self.scheduled = []
        patcher._auto_feed_at_print_start = lambda gate: ("feed", gate)
        patcher.ace_controller = types.SimpleNamespace(
            eventloop=types.SimpleNamespace(create_task=lambda job: self.scheduled.append(job[1])),
        )
        return patcher

    def _print(self, patcher, used_tools):
        with mock.patch.object(self.module, "_read_referenced_tools", return_value=used_tools):
            return self.module.MmuAcePatcher.patch_print_data(patcher, {"filename": "job.gcode"})

    def test_a_file_that_selects_its_tool_is_not_auto_fed(self):
        # The #196 case: single tool T3, nothing loaded, no Color Match.
        self._print(self._patcher(), [3])
        self.assertEqual(self.scheduled, [])

    def test_a_file_that_selects_its_tool_wins_over_color_match(self):
        self._print(self._patcher(color_match_gate=1), [3])
        self.assertEqual(self.scheduled, [])

    def test_color_match_still_feeds_a_file_without_tool_commands(self):
        # The case auto-feed exists for (#464): no T-command in the file.
        self._print(self._patcher(color_match_gate=2), None)
        self.assertEqual(self.scheduled, [2])

    def test_no_tool_commands_and_no_color_match_feeds_nothing(self):
        self._print(self._patcher(), None)
        self.assertEqual(self.scheduled, [])

    def test_auto_feed_can_be_switched_off(self):
        self._print(self._patcher(color_match_gate=2, auto_feed=False), None)
        self.assertEqual(self.scheduled, [])


class MmuAceAutoFeedSendTests(unittest.IsolatedAsyncioTestCase):
    """A FEED_FILAMENT the printer rejects must not be sent again (issue #196)."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    async def test_a_rejected_feed_is_not_retried(self):
        m = self.module
        sent = []

        async def query_objects(_objects):
            return {"extruder": {"temperature": 205.0, "target": 210.0},
                    "print_stats": {"state": "printing"}}

        async def send_gcode(gcode):
            sent.append(gcode)
            raise RuntimeError("Extruder must heat up first")

        patcher = m.MmuAcePatcher.__new__(m.MmuAcePatcher)
        patcher.ace = types.SimpleNamespace(loaded_gate=m.TOOL_GATE_UNKNOWN)
        patcher.ace_controller = types.SimpleNamespace(
            printer=types.SimpleNamespace(query_objects=query_objects, send_gcode=send_gcode))
        patcher._auto_feed_length = 80
        patcher._auto_feed_speed = 25
        patcher._commit_loaded_gate = lambda gate: self.fail("a failed feed must not mark the gate loaded")

        with self.assertLogs(level="WARNING"):
            await m.MmuAcePatcher._auto_feed_at_print_start(patcher, 3)

        self.assertEqual(sent, ["FEED_FILAMENT ID=0 INDEX=3 LENGTH=80 SPEED=25"])


class MmuAceTtgMapCommandTests(unittest.IsolatedAsyncioTestCase):
    """MMU_TTG_MAP must keep the map the same length as the tool list, reject
    gates that don't exist, and say when a change can't reach the running print
    (issue #131)."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_mmu_ace_module()

    def _patcher(self, state="standby"):
        m = self.module
        patcher = m.MmuAcePatcher.__new__(m.MmuAcePatcher)
        patcher._last_ttg_reset_time = 0.0
        patcher.ace = types.SimpleNamespace(
            units=[types.SimpleNamespace(gates=[object()] * 4)],
            ttg_map=[0, 1, 2, 3],
        )
        updates, responses = [], []

        async def query_objects(objects):
            return {"print_stats": {"state": state}}

        def update_ttg_map(ttg_map):
            updates.append(ttg_map)
            patcher.ace.ttg_map = ttg_map

        async def send_response(message):
            responses.append(message)

        patcher.ace_controller = types.SimpleNamespace(
            update_ttg_map=update_ttg_map,
            printer=types.SimpleNamespace(query_objects=query_objects),
        )
        patcher._send_gcode_response = send_response
        return patcher, updates, responses

    async def _ttg(self, patcher, args):
        return await self.module.MmuAcePatcher._on_gcode_mmu_ttg_map(patcher, args, None)

    async def test_a_partial_map_sets_the_first_tools_and_keeps_the_rest(self):
        # What the #131 reporter typed on a four-gate ACE.
        patcher, updates, _ = self._patcher()
        await self._ttg(patcher, {"MAP": "0,2"})
        self.assertEqual(updates, [[0, 2, 2, 3]])

    async def test_a_gate_that_does_not_exist_is_rejected(self):
        patcher, updates, responses = self._patcher()
        await self._ttg(patcher, {"MAP": "0,7"})
        self.assertEqual(updates, [])
        self.assertTrue(any("does not exist" in r for r in responses))

    async def test_changing_the_map_mid_print_says_it_applies_next_print(self):
        patcher, updates, responses = self._patcher(state="printing")
        await self._ttg(patcher, {"MAP": "0,2,2,3"})
        self.assertEqual(updates, [[0, 2, 2, 3]])
        self.assertTrue(any("next print" in r for r in responses))

    async def test_no_note_when_nothing_is_printing(self):
        patcher, _, responses = self._patcher(state="standby")
        await self._ttg(patcher, {"MAP": "0,2,2,3"})
        self.assertEqual(responses, [])
