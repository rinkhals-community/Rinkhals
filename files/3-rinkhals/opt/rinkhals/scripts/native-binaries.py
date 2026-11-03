"""Prepare native patches without consuming the last verified stock executable.

Only gkapi/K3SysUi and their own staging names are managed. No damaged-file
archives are created. Call after stopping the native processes, under the
startup lock; restore after launching them from their expected filenames.
"""
import argparse
import ctypes
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


TARGETS = ('gkapi', 'K3SysUi')


def regular(path):
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def digest(path):
    if not regular(path):
        return None
    value = hashlib.md5()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            value.update(block)
    return value.hexdigest()


def sync_directory(directory):
    fd = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def discard_stage(path):
    # Never follow links or recursively remove a directory at a staging name.
    try:
        if not regular(path):
            path.lstat()
            raise ValueError('Unsafe staging path: ' + str(path))
        path.unlink()
    except FileNotFoundError:
        pass


def stage_copy(source, destination, expected):
    discard_stage(destination)
    with source.open('rb') as inp, destination.open('xb') as out:
        shutil.copyfileobj(inp, out, length=65536)
        out.flush()
        os.fchmod(out.fileno(), 0o755)
        os.fsync(out.fileno())
    if digest(destination) != expected:
        raise ValueError('Copied executable checksum mismatch: ' + str(source))


def publish(stage, destination):
    os.replace(str(stage), str(destination))
    sync_directory(destination.parent)


def exchange(first, second):
    # Unlike a hard link + replace, RENAME_EXCHANGE moves the running inode's
    # dentry too: /proc/PID/exe continues to name .patch, not "gkapi (deleted)".
    # Both public names always exist, including after an interrupted restore.
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError:
        raise OSError('libc renameat2 is unavailable; native patching refused')
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(first), -100, os.fsencode(second), 2) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    sync_directory(first.parent)


def check_exchange(directory):
    # Probe the actual filesystem before changing either executable. Refuse an
    # unsupported kernel/libc/filesystem instead of using a two-rename fallback.
    first = directory / '.rinkhals-exchange-probe-a'
    second = directory / '.rinkhals-exchange-probe-b'
    try:
        for path in (first, second):
            discard_stage(path)
            with path.open('xb') as stream:
                stream.write(b'probe')
        exchange(first, second)
    finally:
        for path in (first, second):
            discard_stage(path)


class NativeBinary:
    def __init__(self, directory, name, patch):
        self.target = directory / name
        self.original = directory / (name + '.original')
        self.patched = directory / (name + '.patch')
        self.stage = directory / ('.' + name + '.rinkhals-stage')
        self.backup_stage = directory / ('.' + name + '.rinkhals-original-stage')
        self.patch = patch
        text = patch.read_text()
        hashes = []
        for kind in ('Before', 'After'):
            matches = re.findall(r'^# ' + kind + r' MD5: ([a-f0-9]{32})\s*$', text, re.M)
            if len(matches) != 1:
                raise ValueError('Missing/ambiguous checksum in ' + str(patch))
            hashes.append(matches[0])
        self.before, self.after = hashes

    def preflight(self):
        # A firmware change can replace .original ONLY when the current stock
        # executable matches the new firmware's patch profile. Never trust .1.
        for path in (self.target, self.original, self.patched):
            if path.exists() or path.is_symlink():
                if not regular(path):
                    raise ValueError('Not a regular executable: ' + str(path))
        if digest(self.original) != self.before and digest(self.target) != self.before:
            raise ValueError('No verified stock original for ' + str(self.target))

    def ensure_original(self):
        if digest(self.original) != self.before:
            if digest(self.target) != self.before:
                raise ValueError('Stock executable changed: ' + str(self.target))
            stage_copy(self.target, self.backup_stage, self.before)
            publish(self.backup_stage, self.original)
        # Also flush an existing legacy .original before relying on it.
        with self.original.open('rb') as stream:
            os.fsync(stream.fileno())
        sync_directory(self.original.parent)

    def prepare(self):
        self.ensure_original()
        stage_copy(self.original, self.stage, self.before)
        subprocess.run(['sh', str(self.patch), str(self.stage)], check=True)
        if digest(self.stage) != self.after:
            raise ValueError('Patched executable checksum mismatch: ' + str(self.target))
        with self.stage.open('rb') as stream:
            os.fsync(stream.fileno())
        publish(self.stage, self.target)

    def restore(self):
        self.ensure_original()
        if digest(self.target) == self.after:
            # Install a complete stock copy at .patch first, then atomically
            # exchange names. The running executable becomes .patch and the
            # normal path becomes stock, with no missing-name interval.
            stage_copy(self.original, self.stage, self.before)
            publish(self.stage, self.patched)
            exchange(self.target, self.patched)
        elif digest(self.target) != self.before:
            stage_copy(self.original, self.stage, self.before)
            publish(self.stage, self.target)
        if self.patched.exists() and digest(self.patched) != self.after:
            self.patched.unlink()
        for path in (self.stage, self.backup_stage):
            discard_stage(path)
        sync_directory(self.target.parent)


def manage(action, directory, patches, model, version):
    if not all(re.fullmatch(r'[A-Za-z0-9_.-]+', s) for s in (model, version)):
        raise ValueError('Invalid model or firmware version')
    binaries = []
    for name in TARGETS:
        patch = patches / ('%s.%s_%s.sh' % (name, model, version))
        if patch.is_file():
            binaries.append(NativeBinary(directory, name, patch))
    # Validate both originals before preparing either native executable.
    for binary in binaries:
        binary.preflight()
    if binaries:
        check_exchange(directory)
    for binary in binaries:
        getattr(binary, action)()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'restore'))
    parser.add_argument('--directory', type=Path, default=Path('/userdata/app/gk'))
    parser.add_argument('--patch-directory', type=Path, default=Path('/opt/rinkhals/patches'))
    parser.add_argument('--model', required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    try:
        manage(args.action, args.directory, args.patch_directory, args.model, args.version)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Native executable preparation/recovery failed: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
