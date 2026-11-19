#!/usr/bin/env python3
"""Check rinkhals-patcher against the recorded results, or record new ones.

files/3-rinkhals/opt/rinkhals/patches/patches.txt lists, for every firmware
Rinkhals has been checked on, the MD5 of the stock K3SysUi and gkapi and the
MD5 the patcher must turn each into. start.sh refuses a patched binary that
doesn't match, so a change to the patcher that alters its output for a known
firmware has to show up here first.

    go build -o rinkhals-patcher . && ./validate.py [--add] [directory]

The directory holds stock binaries named K3SysUi.<MODEL>_<VERSION> and
gkapi.<MODEL>_<VERSION>, for example K3SysUi.KS1_2.7.2.7. They are Anycubic's
files, so they are not in the repository; build/prepare-version.sh downloads
them into build/tmp/patches, which is the default directory.

Without --add, every binary is run through the patcher and compared with its
line in patches.txt. Anything else than "ok" fails the run:
  ok          the patcher's output (or its refusal) is the recorded one
  CHANGED     the patcher now produces something else for this stock binary
  STOCK?      the file isn't the stock binary patches.txt knows for this build
  NEW         the build isn't in patches.txt

With --add, NEW builds and builds recorded as "unverified" get their line
written. Read the patcher's log line for a new build before committing it: it
says which menu it found and where the Support row is. Then check the result
on a printer.
"""
import hashlib, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(ROOT, 'files', '3-rinkhals', 'opt', 'rinkhals', 'patches', 'patches.txt')
DEFAULT_DIRECTORY = os.path.join(ROOT, 'build', 'tmp', 'patches')
PATCHER = os.path.join(HERE, 'rinkhals-patcher')


def md5(data):
    return hashlib.md5(data).hexdigest()


def version_key(key):
    target, model, version = key
    return target != 'K3SysUi', model, [int(x) for x in version.split('.')]


def read_manifest():
    header, rows = [], {}
    for line in open(MANIFEST):
        if line.startswith('#') or not line.strip():
            header.append(line)
            continue
        target, model, version, stock, result = line.split()
        rows[(target, model, version)] = (stock, result)
    return header, rows


def write_manifest(header, rows):
    with open(MANIFEST, 'w') as f:
        f.writelines(header)
        for key in sorted(rows, key=version_key):
            f.write('%-7s %-4s %-8s %s %s\n' % (key + rows[key]))


def run_patcher(path):
    """Return (MD5 of the patched binary or 'unpatched', what the patcher said)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out')
        r = subprocess.run([PATCHER, '--binary', path, '--output', out], capture_output=True, text=True)
        said = r.stderr.strip().splitlines()
        if r.returncode != 0:
            return 'unpatched', said[-1].split(': not patched: ')[-1] if said else ''
        return md5(open(out, 'rb').read()), said[0] if said else ''


def main():
    args = [a for a in sys.argv[1:] if a != '--add']
    add = '--add' in sys.argv[1:]
    directory = args[0] if args else DEFAULT_DIRECTORY

    names = sorted(n for n in os.listdir(directory) if re.fullmatch(r'(K3SysUi|gkapi)\.K[A-Z0-9]+_[0-9.]+', n))
    if not names:
        sys.exit('no stock binaries in %s' % directory)
    header, rows = read_manifest()

    failed = added = 0
    keys = []
    for name in names:
        target, build = name.split('.', 1)
        keys.append((target,) + tuple(build.split('_')))
    for key, name in sorted(zip(keys, names), key=lambda x: version_key(x[0])):
        path = os.path.join(directory, name)
        stock = md5(open(path, 'rb').read())
        known = rows.get(key)
        if known and known[0] != stock:
            status, detail = 'STOCK?', 'expected %s, this file is %s' % (known[0], stock)
        else:
            result, detail = run_patcher(path)
            if known and known[1] == result:
                status = 'ok'
                detail = 'unpatched: ' + detail if result == 'unpatched' else ''
            elif known and known[1] != 'unverified':
                status, detail = 'CHANGED', 'recorded %s, now %s (%s)' % (known[1], result, detail)
            elif add:
                rows[key] = (stock, result)
                added += 1
                status = 'added'
            else:
                status = 'NEW'
                detail = '%s (%s)' % (result, detail)
        failed += status not in ('ok', 'added')
        print('%-7s %-24s %s' % (status, name, detail))

    if added:
        write_manifest(header, rows)
    missing = sorted(set(rows) - set(keys), key=version_key)
    print('%d binaries, %d failed, %d added; %d builds in patches.txt had no binary here' % (len(names), failed, added, len(missing)))
    for key in missing:
        print('  not checked: %s.%s_%s' % key)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
