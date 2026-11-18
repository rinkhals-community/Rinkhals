import os
import subprocess
import tempfile
import unittest

from test_kobra import load_kobra_module


class LightPowerCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def write_cfg(self, text):
        f = tempfile.NamedTemporaryFile('w', suffix='.cfg', delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_reads_the_gpio_from_the_led_pin_section(self):
        # As in the Kobra S1 stock printer.cfg.
        path = self.write_cfg("[other]\ngpio: 5\n\n[led_pin]\ngpio:117\n\n#[output_pin power_pin]\n#pin:PB4\n")
        self.assertEqual(self.module.read_led_gpio(path), 117)

    def test_no_gpio_without_the_section_or_the_file(self):
        self.assertIsNone(self.module.read_led_gpio(self.write_cfg("[other]\ngpio: 5\n")))
        self.assertIsNone(self.module.read_led_gpio(self.write_cfg("[led_pin]\n# gpio: 117\n[next]\ngpio: 3\n")))
        self.assertIsNone(self.module.read_led_gpio('/nonexistent/printer.cfg'))

    def test_without_a_gpio_the_command_is_the_goklipper_request_only(self):
        command = self.module.led_power_command(1, None)
        self.assertIn('"method":"led/set_led","params":{"S":1}', command)
        self.assertNotIn('/sys/class/gpio', command)

    def test_with_a_gpio_it_falls_back_when_gklib_is_not_running(self):
        for state in (0, 1):
            command = self.module.led_power_command(state, 117)
            self.assertIn('"params":{"S":%d}' % state, command)
            self.assertIn('echo %d > /sys/class/gpio/gpio117/value' % state, command)
            # Valid shell either way.
            subprocess.run(['sh', '-n', '-c', command], check=True)


if __name__ == '__main__':
    unittest.main()
