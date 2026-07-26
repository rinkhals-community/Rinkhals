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
    return None


class BedMeshCalibrateScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = _find_calibrate_script()
        self.assertIsNotNone(self.script, "calibrate_script list not found in kobra.py")

    def test_script_homes_before_probing(self):
        """Regression guard for issue #85.

        GoKlipper does not raise "Must home axis first"; given an un-homed
        printer it blocks inside BED_MESH_CALIBRATE at the first probe point,
        and because Moonraker forwards gcode with no timeout the UI shows no
        error at all - the printer simply sits there. Verified on a KS1
        (fw 2.7.2.7): homed, the same command probes the full 5x5 mesh.
        """
        self.assertIn("G28", self.script, "calibration script must home the printer")
        self.assertIn("BED_MESH_CALIBRATE", self.script)
        self.assertLess(
            self.script.index("G28"),
            self.script.index("BED_MESH_CALIBRATE"),
            "homing must come before probing",
        )

    def test_homing_precedes_any_positioning_move(self):
        """Wiping moves assume a known position, so they must follow homing."""
        home_index = self.script.index("G28")
        for command in ("WIPE_ENTER", "WIPE_NOZZLE", "WIPE_EXIT", "MOVE_HEAT_POS"):
            if command in self.script:
                self.assertLess(
                    home_index,
                    self.script.index(command),
                    f"{command} moves the toolhead and must come after homing",
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
