"""Synthetic executable fixtures only; never run against printer paths.

Abrupt-exit tests exercise real filesystem operations, including partial
copies. They are process-crash tests, not a model of eMMC power-loss behavior.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'files/3-rinkhals/opt/rinkhals/scripts/native-binaries.py'
SPEC = importlib.util.spec_from_file_location('native_binaries', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
GOOD = b'original synthetic executable\n' * 4096
PATCHED = b'X' + GOOD[1:]
BEFORE = hashlib.md5(GOOD).hexdigest()
AFTER = hashlib.md5(PATCHED).hexdigest()

# Crash before/after each durability/namespace boundary. This wrapper lives in
# the child test process; production code has no fault-injection environment.
CRASH_RUNNER = r'''
import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('native', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
count = [0]
stop = int(sys.argv[5])
def tick():
    count[0] += 1
    if count[0] == stop:
        os._exit(73)
for name in ('replace', 'fsync', 'link', 'unlink'):
    original = getattr(m.os, name)
    def wrap(*args, _fn=original, **kwargs):
        tick(); result = _fn(*args, **kwargs); tick(); return result
    setattr(m.os, name, wrap)
original_exchange = m.exchange
def exchange(*args):
    tick(); original_exchange(*args); tick()
m.exchange = exchange
def copy(inp, out, length=65536):
    while True:
        block = inp.read(4096)
        if not block: break
        out.write(block); out.flush(); tick()
m.shutil.copyfileobj = copy
m.manage(sys.argv[4], Path(sys.argv[2]), Path(sys.argv[3]), 'K3', 'test')
print(count[0])
'''


class NativeBinaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'native'
        self.patches = self.root / 'patches'
        self.directory.mkdir(); self.patches.mkdir()
        self.target = self.directory / 'gkapi'
        self.original = self.directory / 'gkapi.original'
        self.target.write_bytes(GOOD)
        self.profile = self.patches / 'gkapi.K3_test.sh'
        self.write_patch("printf X | dd of=\"$1\" bs=1 count=1 conv=notrunc 2>/dev/null\n")

    def write_patch(self, body):
        self.profile.write_text('#!/bin/sh\n# Before MD5: ' + BEFORE + '\n# After MD5: ' + AFTER + '\n' + body)

    def run_action(self, action):
        MODULE.manage(action, self.directory, self.patches, 'K3', 'test')

    def test_prepare_restore_preserves_original_and_launched_inode(self):
        self.run_action('prepare')
        self.assertEqual(self.target.read_bytes(), PATCHED)
        self.assertEqual(self.original.read_bytes(), GOOD)
        inode = self.target.stat().st_ino
        with self.target.open('rb') as launched:
            self.run_action('restore')
            self.assertEqual(launched.read(), PATCHED)
        self.assertEqual((self.directory / 'gkapi.patch').stat().st_ino, inode)
        self.assertEqual(self.target.read_bytes(), GOOD)
        original_inode = self.original.stat().st_ino
        self.run_action('prepare'); self.run_action('restore')
        self.assertEqual(self.original.stat().st_ino, original_inode)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ['gkapi', 'gkapi.original', 'gkapi.patch'])

    def test_legacy_interrupted_copy_does_not_destroy_original(self):
        self.original.write_bytes(GOOD)
        self.target.write_bytes(PATCHED[:8192])
        self.run_action('prepare'); self.run_action('restore')
        self.assertEqual(self.target.read_bytes(), GOOD)
        self.assertEqual(self.original.read_bytes(), GOOD)

    def test_recovery_does_not_archive_damaged_files(self):
        self.original.write_bytes(GOOD)
        self.target.write_bytes(b"damaged target")
        (self.directory / "gkapi.patch").write_bytes(b"damaged patch")
        self.run_action("restore")
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ["gkapi", "gkapi.original"])
        self.assertEqual(self.target.read_bytes(), GOOD)

    def test_missing_target_recovers_legacy_original(self):
        self.original.write_bytes(GOOD); self.target.unlink()
        self.run_action('restore')
        self.assertEqual(self.target.read_bytes(), GOOD)

    def test_unknown_original_and_target_fail_without_mutation(self):
        self.target.write_bytes(b'unknown')
        self.original.write_bytes(b'older unknown backup')
        with self.assertRaises(ValueError): self.run_action('prepare')
        self.assertEqual(self.target.read_bytes(), b'unknown')
        self.assertEqual(self.original.read_bytes(), b'older unknown backup')

    def test_new_firmware_replaces_stale_backup_only_from_verified_stock(self):
        self.original.write_bytes(b'old firmware')
        self.run_action('prepare'); self.run_action('restore')
        self.assertEqual(self.original.read_bytes(), GOOD)

    def test_patch_failure_and_wrong_output_never_publish(self):
        for body in ('exit 1\n', 'printf broken > "$1"\n'):
            with self.subTest(body=body):
                self.write_patch(body)
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    self.run_action('prepare')
                self.assertEqual(self.target.read_bytes(), GOOD)
                self.assertEqual(self.original.read_bytes(), GOOD)
                self.run_action('restore')
                self.assertFalse((self.directory / '.gkapi.rinkhals-stage').exists())

    def test_all_targets_preflight_before_any_mutation(self):
        (self.patches / 'K3SysUi.K3_test.sh').write_text(self.profile.read_text())
        (self.directory / 'K3SysUi').write_bytes(b'unknown UI firmware')
        with self.assertRaises(ValueError): self.run_action('prepare')
        self.assertFalse(self.original.exists())
        self.assertEqual(self.target.read_bytes(), GOOD)

    def test_reject_symlinks_and_missing_profile_hashes(self):
        self.original.symlink_to(self.target)
        with self.assertRaises(ValueError): self.run_action('prepare')
        self.original.unlink()
        self.profile.write_text('#!/bin/sh\nexit 0\n')
        with self.assertRaises(ValueError): self.run_action('prepare')
        self.assertEqual(self.target.read_bytes(), GOOD)

    def test_copy_failure_preserves_only_good_source(self):
        original_copy = MODULE.shutil.copyfileobj
        def failing_copy(inp, out, length):
            out.write(inp.read(8))
            raise OSError('synthetic ENOSPC')
        MODULE.shutil.copyfileobj = failing_copy
        try:
            with self.assertRaises(OSError): self.run_action('prepare')
        finally:
            MODULE.shutil.copyfileobj = original_copy
        self.assertEqual(self.target.read_bytes(), GOOD)
        self.run_action('prepare'); self.run_action('restore')
        self.assertEqual(self.original.read_bytes(), GOOD)

    def test_unsupported_exchange_refuses_before_changing_executables(self):
        original_exchange = MODULE.exchange
        def unsupported(*args):
            raise OSError('synthetic unsupported filesystem')
        MODULE.exchange = unsupported
        try:
            with self.assertRaises(OSError): self.run_action('prepare')
        finally:
            MODULE.exchange = original_exchange
        self.assertEqual(self.target.read_bytes(), GOOD)
        self.assertFalse(self.original.exists())

    def test_fsync_failure_does_not_publish_backup_or_patch(self):
        real_sync = MODULE.os.fsync
        def fail(fd):
            raise OSError('synthetic I/O failure')
        MODULE.os.fsync = fail
        try:
            with self.assertRaises(OSError): self.run_action('prepare')
        finally:
            MODULE.os.fsync = real_sync
        self.assertEqual(self.target.read_bytes(), GOOD)
        self.assertFalse(self.original.exists())

    @unittest.skipUnless(Path('/bin/sleep').is_file() and Path('/proc/self/exe').exists(), 'Linux host required')
    def test_exchange_keeps_running_executable_named_patch(self):
        # Host utility only, not a printer binary. /proc tracks the launched
        # dentry; a hard-link-and-replace implementation fails this assertion.
        import shutil
        shutil.copyfile('/bin/sleep', self.target)
        self.target.chmod(0o755)
        patched = self.directory / 'gkapi.patch'
        patched.write_bytes(GOOD)
        process = subprocess.Popen([str(self.target), '30'])
        try:
            # Popen waits for successful exec before returning.
            self.assertEqual(os.readlink('/proc/%d/exe' % process.pid), str(self.target))
            MODULE.exchange(self.target, patched)
            self.assertEqual(os.readlink('/proc/%d/exe' % process.pid), str(patched))
            self.assertEqual(self.target.read_bytes(), GOOD)
            self.assertIsNone(process.poll())
        finally:
            process.terminate(); process.wait(timeout=5)

    def crash_action(self, action, step):
        return subprocess.run([sys.executable, '-c', CRASH_RUNNER, str(SCRIPT), str(self.directory), str(self.patches), action, str(step)], capture_output=True, text=True)

    def reset_files(self):
        for path in self.directory.iterdir(): path.unlink()
        self.target.write_bytes(GOOD)

    def assert_recoverable(self):
        self.assertTrue(self.target.read_bytes() == GOOD or self.original.exists() and self.original.read_bytes() == GOOD)
        # If present, the public executable is complete, never a partial copy.
        self.assertIn(self.target.read_bytes(), (GOOD, PATCHED))

    def test_abrupt_exit_at_every_prepare_and_restore_boundary(self):
        for action in ('prepare', 'restore'):
            self.reset_files()
            if action == 'restore': self.run_action('prepare')
            result = self.crash_action(action, 0)
            self.assertEqual(result.returncode, 0, result.stderr)
            steps = int(result.stdout.strip())
            for step in range(1, steps + 1):
                with self.subTest(action=action, step=step):
                    self.reset_files()
                    if action == 'restore': self.run_action('prepare')
                    self.assertEqual(self.crash_action(action, step).returncode, 73)
                    self.assert_recoverable()
                    self.run_action('restore')
                    self.assertEqual(self.target.read_bytes(), GOOD)
                    self.run_action('prepare'); self.run_action('restore')
                    self.assertEqual(self.original.read_bytes(), GOOD)

    def test_repeated_crashes_during_recovery_of_legacy_partial_file(self):
        self.original.write_bytes(GOOD); self.target.write_bytes(PATCHED[:8192])
        completed = self.crash_action('restore', 0)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for step in range(1, int(completed.stdout.strip()) + 1):
            with self.subTest(step=step):
                self.reset_files()
                self.original.write_bytes(GOOD); self.target.write_bytes(PATCHED[:8192])
                for _ in range(2):
                    result = self.crash_action('restore', step)
                    self.assertIn(result.returncode, (0, 73), result.stderr)
                    self.assertEqual(self.original.read_bytes(), GOOD)
                self.run_action('restore')
                self.assertEqual(self.target.read_bytes(), GOOD)


if __name__ == '__main__':
    unittest.main()
