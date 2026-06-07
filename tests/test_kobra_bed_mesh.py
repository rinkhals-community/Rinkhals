import ast
import unittest
from pathlib import Path

KOBRA_PATH = (
    Path(__file__).resolve().parents[1]
    / "files/4-apps/home/rinkhals/apps/40-moonraker/kobra.py"
)


def _find_calibrate_script():
    """Return the literal string entries of the `calibrate_script = [...]` list.

    The list is built deep inside a wrapped Moonraker request handler, so
    exercising it end-to-end needs the whole server mocked. The invariant worth
    protecting is purely the command ordering, so read it out of the AST.
    """
    tree = ast.parse(KOBRA_PATH.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "calibrate_script" not in targets:
            continue
        if not isinstance(node.value, ast.List):
            continue
        entries = []
        for element in node.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                entries.append(element.value)
            elif isinstance(element, ast.JoinedStr):
                # f-string such as f"M140 S{bed_temp}" - keep the literal prefix
                prefix = ""
                for part in element.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        prefix += part.value
                    else:
                        break
                entries.append(prefix.strip())
        return entries
    return []


class BedMeshCalibrateScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = _find_calibrate_script()
        self.assertTrue(self.script, "calibrate_script list not found in kobra.py")

    def test_script_homes_before_probing(self):
        """Regression guard for issue #85.

        GoKlipper does not raise "Must home axis first"; given an un-homed
        printer it blocks inside BED_MESH_CALIBRATE at the first probe point,
        and because Moonraker forwards gcode with no timeout the UI shows no
        error at all - the printer simply sits there. Verified on a KS1
        (fw 2.7.2.7): homed, the same command probes the full 5x5 mesh.
        """
        homing = [i for i, cmd in enumerate(self.script) if cmd.startswith("G28")]
        self.assertTrue(homing, "calibration script must home the printer")
        self.assertIn("BED_MESH_CALIBRATE", self.script)
        self.assertLess(
            max(homing),
            self.script.index("BED_MESH_CALIBRATE"),
            "all homing must come before probing",
        )

    def test_homing_precedes_any_positioning_move(self):
        """Wiping moves assume a known position, so they must follow homing."""
        first_home = min(
            i for i, cmd in enumerate(self.script) if cmd.startswith("G28")
        )
        for command in ("WIPE_ENTER", "WIPE_NOZZLE", "WIPE_EXIT", "MOVE_HEAT_POS"):
            if command in self.script:
                self.assertLess(
                    first_home,
                    self.script.index(command),
                    f"{command} moves the toolhead and must come after homing",
                )

    def test_z_homed_after_temperature_reached(self):
        """Z is re-homed only after the target temperatures are reached.

        The bed warps as it heats, so a Z zero taken cold drifts. The script
        homes X and Y first, waits for the hotend and bed to reach temperature
        (M109 / M190), then re-homes Z so the mesh is probed against the hot
        geometry.
        """
        z_home = min(
            i for i, cmd in enumerate(self.script) if cmd.startswith("G28 Z")
        )
        self.assertTrue(
            any(self.script[i].startswith("M190") for i in range(z_home)),
            "bed must reach temperature (M190) before Z is homed",
        )
        self.assertTrue(
            any(self.script[i].startswith("M109") for i in range(z_home)),
            "hotend must reach temperature (M109) before Z is homed",
        )
        self.assertLess(
            z_home,
            self.script.index("BED_MESH_CALIBRATE"),
            "Z homing must still precede probing",
        )

    def test_script_still_saves_and_cools_down(self):
        """The tail of the sequence must be preserved."""
        for command in ("TURN_OFF_HEATERS", "SAVE_CONFIG"):
            self.assertIn(command, self.script)
        self.assertLess(
            self.script.index("BED_MESH_CALIBRATE"),
            self.script.index("SAVE_CONFIG"),
            "the mesh must be probed before it is saved",
        )


if __name__ == "__main__":
    unittest.main()
