import time
import unittest

from test_kobra import _build_klippy_connection_module, load_kobra_module

# Commands each printer reports through gcode/help, limited to the ones the
# calibration script cares about. KS1 and KS1M are read from their stock
# printer configs (#101); the K3 family defines MOVE_HEAT_POS, the Kobra 2 Pro
# does not.
KS1_2727 = {"TO_THROW_POSITION", "EXIT_THROW_POSITION", "WIPE_ENTER", "WIPE_NOZZLE",
            "WIPE_STOP", "WIPE_STOP1", "WIPE_EXIT", "BED_MESH_CALIBRATE", "SAVE_CONFIG"}
KS1M_2721 = {"TO_THROW_POSITION", "EXIT_THROW_POSITION", "WIPE_ENTER", "WIPE_NOZZLE",
             "WIPE_STOP", "BED_MESH_CALIBRATE", "SAVE_CONFIG"}
K3_FAMILY = {"MOVE_HEAT_POS", "WIPE_NOZZLE", "BED_MESH_CALIBRATE", "SAVE_CONFIG"}
K2P = {"WIPE_NOZZLE", "BED_MESH_CALIBRATE", "SAVE_CONFIG"}

OPTIONAL_MACROS = {"MOVE_HEAT_POS", "TO_THROW_POSITION", "WIPE_ENTER", "WIPE_NOZZLE",
                   "WIPE_STOP", "WIPE_EXIT"}

CASES = [
    ("KS1", KS1_2727), ("KS1M", KS1M_2721), ("K3", K3_FAMILY),
    ("K3M", K3_FAMILY), ("K3V2", K3_FAMILY), ("K2P", K2P),
]


class BedMeshCalibrateScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def script(self, model, commands):
        kobra = self.module.Kobra.__new__(self.module.Kobra)
        kobra.KOBRA_MODEL_CODE = model
        return kobra.build_calibrate_script(commands, 60, 170, 140)

    def every_script(self):
        for model, commands in CASES:
            yield model, commands, self.script(model, commands)
            yield model, None, self.script(model, None)

    # --- invariants that hold for every model, known commands or not --------

    def test_homing_comes_first_and_all_homing_precedes_probing(self):
        """Regression guard for #85: GoKlipper blocks forever at the first probe
        point if BED_MESH_CALIBRATE runs un-homed, with no error at all."""
        for model, commands, script in self.every_script():
            with self.subTest(model=model, commands=commands is not None):
                self.assertEqual(script[0], "G28")
                homing = [i for i, cmd in enumerate(script) if cmd.startswith("G28")]
                self.assertLess(max(homing), script.index("BED_MESH_CALIBRATE"))

    def test_positioning_moves_follow_homing(self):
        for model, commands, script in self.every_script():
            for command in ("WIPE_ENTER", "WIPE_NOZZLE", "WIPE_STOP", "WIPE_EXIT",
                            "MOVE_HEAT_POS", "TO_THROW_POSITION"):
                if command in script:
                    with self.subTest(model=model, command=command):
                        self.assertLess(script.index("G28"), script.index(command))

    def test_script_still_saves_and_cools_down(self):
        for model, commands, script in self.every_script():
            with self.subTest(model=model, commands=commands is not None):
                self.assertEqual(script[-3:], ["TURN_OFF_HEATERS", "M106 S0", "SAVE_CONFIG"])

    def test_nothing_is_sent_that_the_printer_does_not_have(self):
        """GoKlipper answers an unknown command with "ok" and a log warning, so
        a missing macro fails silently (#101). Models on the pre-#190 script
        are exempt: they get exactly what they had before, on purpose."""
        for model, commands in CASES:
            if model in self.module.Kobra.LEGACY_CALIBRATE_MODELS:
                continue
            with self.subTest(model=model):
                script = self.script(model, commands)
                for command in script:
                    if command in OPTIONAL_MACROS:
                        self.assertIn(command, commands)

    # --- #101: the S1 family ---------------------------------------------------

    def test_s1_uses_the_throw_position_not_move_heat_pos(self):
        script = self.script("KS1", KS1_2727)
        self.assertNotIn("MOVE_HEAT_POS", script)
        self.assertIn("TO_THROW_POSITION", script)

    def test_s1_cools_down_parked_on_the_pad(self):
        """The nozzle used to wait out the cooldown at the wiper exit (X83 Y250
        on the S1) and ooze. WIPE_STOP parks it on the silicone pad first."""
        script = self.script("KS1", KS1_2727)
        cooldown = script.index("M109 S140")
        self.assertLess(script.index("WIPE_NOZZLE"), script.index("WIPE_STOP"))
        self.assertLess(script.index("WIPE_STOP"), cooldown)
        self.assertGreater(script.index("WIPE_EXIT"), cooldown)

    def test_s1_max_keeps_the_script_from_before_190(self):
        """On an S1 Max (fw 2.7.1.4) the new sequence never finished: gcode/script
        stayed pending for minutes and the mesh wasn't saved. Until a new
        sequence is tested on one, it gets exactly what it had before, whatever
        gcode/help reports."""
        self.assertEqual(self.script("KS1M", KS1M_2721), self.script("KS1M", None))
        self.assertNotIn("WIPE_STOP", self.script("KS1M", KS1M_2721))

    # --- other models keep what they had ---------------------------------------

    def test_k3_family_keeps_move_heat_pos_and_no_s1_wipe_moves(self):
        for model in ("K3", "K3M", "K3V2"):
            with self.subTest(model=model):
                script = self.script(model, K3_FAMILY)
                self.assertIn("MOVE_HEAT_POS", script)
                for command in ("WIPE_ENTER", "WIPE_STOP", "WIPE_EXIT", "TO_THROW_POSITION"):
                    self.assertNotIn(command, script)

    def test_kobra_2_pro_no_longer_gets_a_move_heat_pos_it_lacks(self):
        self.assertNotIn("MOVE_HEAT_POS", self.script("K2P", K2P))

    # --- #127: hot Z re-home only where it has been checked ---------------------

    def test_z_rehomed_hot_on_the_k3_after_cooldown_before_probing(self):
        script = self.script("K3", K3_FAMILY)
        z_home = script.index("G28 Z")
        self.assertGreater(z_home, script.index("M190 S60"))
        self.assertGreater(z_home, script.index("M109 S140"))
        self.assertLess(z_home, script.index("BED_MESH_CALIBRATE"))

    def test_no_z_rehome_on_models_not_yet_checked(self):
        for model, commands in CASES:
            if model == "K3":
                continue
            with self.subTest(model=model):
                self.assertNotIn("G28 Z", self.script(model, commands))

    # --- when the printer can't list its commands -------------------------------

    def test_unknown_commands_send_exactly_what_we_sent_before(self):
        old_s1 = ["G28", "MOVE_HEAT_POS", "M140 S60", "M109 S170", "M190 S60",
                  "WIPE_ENTER", "WIPE_NOZZLE", "WIPE_EXIT", "M109 S140",
                  "BED_MESH_CALIBRATE", "TURN_OFF_HEATERS", "M106 S0", "SAVE_CONFIG"]
        old_other = [c for c in old_s1 if c not in ("WIPE_ENTER", "WIPE_EXIT")]
        self.assertEqual(self.script("KS1", None), old_s1)
        self.assertEqual(self.script("KS1M", None), old_s1)
        self.assertEqual(self.script("K3", None), old_other)
        self.assertEqual(self.script("K2P", None), old_other)



class _GcodeRequest:
    """Enough of Moonraker's WebRequest for the gcode/script wrapper, which
    switches .endpoint to gcode/help and back."""

    def __init__(self, script):
        self.endpoint = "gcode/script"
        self._args = {"script": script}

    def get_endpoint(self):
        return self.endpoint

    def get_args(self):
        return self._args

    def get_str(self, name, default=None):
        return self._args.get(name, default)


class BedMeshCalibrateRequestTests(unittest.IsolatedAsyncioTestCase):
    """The wrapper must ask the printer for its commands, build the script from
    them, and hand the request on as a normal gcode/script call."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    async def _calibrate(self, model, help_reply):
        conn_module = _build_klippy_connection_module()
        calls = []

        async def printer(me, web_request):
            endpoint = web_request.get_endpoint()
            calls.append((endpoint, dict(web_request.get_args())))
            if endpoint == "gcode/help":
                if isinstance(help_reply, Exception):
                    raise help_reply
                return help_reply
            return {}

        conn_module.KlippyConnection.request = printer
        kobra = self.module.Kobra.__new__(self.module.Kobra)
        kobra.KOBRA_MODEL_CODE = model
        kobra._goklipper_pid = 1234
        kobra._goklipper_next_check = time.time() + 100
        kobra.patch_bed_mesh()

        request = _GcodeRequest("BED_MESH_CALIBRATE")
        await conn_module.KlippyConnection.request(conn_module.KlippyConnection(), request)
        return calls, request

    async def test_script_is_built_from_what_the_printer_reports(self):
        calls, request = await self._calibrate("KS1", {name: "" for name in KS1_2727})
        self.assertEqual([endpoint for endpoint, _ in calls], ["gcode/help", "gcode/script"])
        sent = calls[-1][1]["script"].split("\n")
        self.assertIn("WIPE_STOP", sent)
        self.assertNotIn("MOVE_HEAT_POS", sent)
        self.assertEqual(request.endpoint, "gcode/script")

    async def test_a_failed_command_list_falls_back_to_the_old_script(self):
        calls, request = await self._calibrate("KS1", RuntimeError("gklib busy"))
        sent = calls[-1][1]["script"].split("\n")
        self.assertEqual(calls[-1][0], "gcode/script")
        self.assertIn("MOVE_HEAT_POS", sent)
        self.assertNotIn("WIPE_STOP", sent)
        self.assertEqual(request.endpoint, "gcode/script")


if __name__ == "__main__":
    unittest.main()
