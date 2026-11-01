import types
import unittest

from test_kobra import DummyServer, load_kobra_module


class KobraPrintEndStateTests(unittest.TestCase):
    """GoKlipper reports standby once the file is consumed, while its
    end-of-print routine is still running. Moonraker must keep seeing
    printing until GoKlipper reports complete itself (#184)."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_kobra_module()

    def setUp(self):
        self.kobra = self.module.Kobra.__new__(self.module.Kobra)
        self.kobra.status_patchers = []
        self.kobra.server = DummyServer()
        self.kobra.is_goklipper_running = lambda: True

    def push(self, state=None, progress=None):
        """Send one GoKlipper status push and return the print_stats.state
        Moonraker ends up with. Moonraker runs patch_status() at least twice on
        the same dict (once when the update arrives, once per subscriber), so
        the state logic has to be stable when it sees its own output."""
        status = {}
        if state is not None:
            status['print_stats'] = {'state': state}
        if progress is not None:
            status['virtual_sdcard'] = {'progress': progress}
        for _ in range(2):
            status = self.kobra.patch_status(status, is_subscription_update=True)
        return status.get('print_stats', {}).get('state')

    def fake_klippy_connection(self):
        """Capture what the hold timeout pushes. Like the real connection, the
        push goes back through patch_status()."""
        pushed = []
        connection = types.SimpleNamespace(
            _process_status_update=lambda eventtime, status: pushed.append(
                self.kobra.patch_status(status, is_subscription_update=True)
            )
        )
        self.kobra.server.lookup_component = lambda name, default=None: connection
        return pushed

    def test_standby_after_file_consumed_holds_printing_until_complete(self):
        self.assertEqual(self.push('printing', 0.5), 'printing')
        self.assertEqual(self.push('standby', 1.0), 'printing')
        self.assertIsNotNone(self.kobra._end_of_print_hold_task)
        # The S1 keeps sending standby during its ~25 s end routine.
        self.assertEqual(self.push('standby', 1.0), 'printing')
        self.assertEqual(self.push('complete', 1.0), 'complete')
        self.assertIsNone(self.kobra._end_of_print_hold_task)

    def test_standby_without_progress_uses_last_seen_progress(self):
        # Models that only send changed fields report progress 1.0 on its own,
        # then standby without it.
        self.push('printing', 0.5)
        self.push(progress=1.0)
        self.assertEqual(self.push('standby'), 'printing')
        self.assertEqual(self.push('complete'), 'complete')

    def test_standby_before_file_is_consumed_is_debounced_not_held(self):
        self.push('printing', 0.4)
        self.assertEqual(self.push('standby', 0.4), 'printing')
        self.assertIsNotNone(self.kobra._delayed_standby_task)
        self.assertIsNone(self.kobra._end_of_print_hold_task)

    def test_new_print_forgets_previous_progress(self):
        self.push('printing', 0.5)
        self.push('standby', 1.0)
        self.push('complete')
        self.assertEqual(self.push('standby'), 'standby')
        # Next print starts without sending progress yet.
        self.assertEqual(self.push('printing'), 'printing')
        self.assertEqual(self.push('standby'), 'printing')
        self.assertIsNone(self.kobra._end_of_print_hold_task)

    def test_hold_timeout_reports_complete(self):
        pushed = self.fake_klippy_connection()
        self.push('printing', 0.5)
        self.push('standby', 1.0)
        self.kobra._release_end_of_print_hold()
        self.assertEqual(pushed[-1]['print_stats']['state'], 'complete')
        self.assertIsNone(self.kobra._end_of_print_hold_task)
        # Later standby pushes are no longer held.
        self.assertEqual(self.push('standby'), 'standby')

    def test_hold_timeout_after_complete_does_nothing(self):
        pushed = self.fake_klippy_connection()
        self.push('printing', 0.5)
        self.push('standby', 1.0)
        self.push('complete')
        self.kobra._release_end_of_print_hold()
        self.assertEqual(pushed, [])

    def test_error_ends_hold(self):
        self.push('printing', 0.5)
        self.push('standby', 1.0)
        self.assertEqual(self.push('error'), 'error')
        self.assertIsNone(self.kobra._end_of_print_hold_task)

    def test_progress_drop_ends_hold(self):
        # A new print while still holding must stop the old timeout.
        self.push('printing', 0.5)
        self.push('standby', 1.0)
        self.push(progress=0.0)
        self.assertIsNone(self.kobra._end_of_print_hold_task)


if __name__ == "__main__":
    unittest.main()
