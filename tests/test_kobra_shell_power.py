import subprocess
import time
import unittest

from test_kobra import load_kobra_module


class ShellPowerCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def test_returns_the_stripped_output(self):
        self.assertEqual(self.module.run_shell_power_command('echo 1'), '1')

    def test_a_hanging_command_times_out(self):
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            self.module.run_shell_power_command('sleep 5', timeout=1)
        self.assertLess(time.monotonic() - start, 3)

    def test_default_timeout_is_ten_seconds(self):
        self.assertEqual(self.module.SHELL_POWER_TIMEOUT, 10)


if __name__ == '__main__':
    unittest.main()
