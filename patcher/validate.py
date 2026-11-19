#!/usr/bin/env python3
"""Check rinkhals-patcher against the static patches.

For every stock binary in a directory, run the patcher and compare its output
with what the static patch for that build produces. The static patches are the
reference: each was checked by hand and most have run on printers.

    go build -o rinkhals-patcher . && ./validate.py [directory]

The directory holds stock binaries named like the patches: K3SysUi.KS1_2.7.2.7,
gkapi.KS1_2.7.2.7. build/prepare-version.sh leaves them in
files/3-rinkhals/opt/rinkhals/patches, which is the default. They are
Anycubic's files, so they are not in the repository.

Results, per binary:
  identical   same bytes as the static patch
  equivalent  differs only where it can't matter (see explain())
  declined    the patcher refused; the static patch covers this build
  DIFFERENT   anything else

validate.expected records the result for every known build. The script fails
if a build gives another result, or if a build that isn't listed is not
identical.
"""
import base64, hashlib, os, re, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PATCHES = os.path.join(HERE, '..', 'files', '3-rinkhals', 'opt', 'rinkhals', 'patches')
PATCHER = os.path.join(HERE, 'rinkhals-patcher')
LABELS = [b'Customer Support\0', b'Service Support\0']
NEW_LABEL = b'Rinkhals\0'


def md5(data):
    return hashlib.md5(data).hexdigest()


def apply_static(script, stock):
    """Apply a generated patch script (base64 blob + dd lines) in memory."""
    text = open(script).read()
    before = re.search(r'# Before MD5: (\w+)', text).group(1)
    after = re.search(r'# After MD5: (\w+)', text).group(1)
    if md5(stock) != before:
        return None, 'stock binary is not the build this patch targets'
    blob = base64.b64decode(re.search(r"echo '([^']+)' \| base64 -d", text).group(1))
    out = bytearray(stock)
    for skip, seek, count in re.findall(r'dd if=\S+ skip=(\d+) ibs=1 of=\S+ seek=(\d+) obs=1 count=(\d+)', text):
        skip, seek, count = int(skip), int(seek), int(count)
        out[seek:seek + count] = blob[skip:skip + count]
    if md5(out) != after:
        return None, 'could not reproduce the static patch'
    return bytes(out), None


def run_patcher(path):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out')
        r = subprocess.run([PATCHER, '--binary', path, '--output', out], capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr.strip().splitlines()[-1].split(': not patched: ')[-1]
        return open(out, 'rb').read(), None


def file_offset(elf, vma):
    phoff, phentsize, phnum = struct.unpack_from('<I', elf, 28)[0], *struct.unpack_from('<HH', elf, 42)
    for i in range(phnum):
        p_type, p_offset, p_vaddr, _, p_filesz = struct.unpack_from('<IIIII', elf, phoff + i * phentsize)
        if p_type == 1 and p_vaddr <= vma < p_vaddr + p_filesz:
            return p_offset + vma - p_vaddr
    return None


def vma_of(elf, off):
    phoff, phentsize, phnum = struct.unpack_from('<I', elf, 28)[0], *struct.unpack_from('<HH', elf, 42)
    for i in range(phnum):
        p_type, p_offset, p_vaddr, _, p_filesz = struct.unpack_from('<IIIII', elf, phoff + i * phentsize)
        if p_type == 1 and p_offset <= off < p_offset + p_filesz:
            return p_vaddr + off - p_offset
    return None


def branch_target(word, vma):
    imm = word & 0xFFFFFF
    if imm & 0x800000:
        imm -= 0x1000000
    return vma + 8 + imm * 4


def lands_at(elf, vma):
    """Follow no-ops and unconditional branches from vma to the first real
    instruction."""
    for _ in range(8):
        off = file_offset(elf, vma)
        if off is None:
            return None
        word = struct.unpack_from('<I', elf, off)[0]
        if word in (0xE1A00000, 0xE320F000):  # nop
            vma += 4
        elif word >> 24 == 0xEA:    # b
            vma = branch_target(word, vma)
        else:
            return vma
    return None


def explain(stock, ours, ref):
    """Return None if every difference from the static patch is harmless.

    Two kinds are:
    - Bytes of the old menu label after the new label's terminator. The static
      generator also rewrites a leftover "Support" there; nothing reads it.
    - The payload's final branch going straight to where the Support row's code
      ends up, where the static patch goes to a no-op or a branch on the way
      there.
    """
    diffs = [i for i in range(len(ref)) if ours[i] != ref[i]]
    tails = set()
    for label in LABELS:
        at = stock.find(label)
        if at >= 0:
            tails.update(range(at + len(NEW_LABEL), at + len(label)))
    rest = [i for i in diffs if i not in tails]
    if not rest:
        return None
    word = rest[0] & ~3
    if all(word <= i < word + 4 for i in rest):
        a, b = struct.unpack_from('<I', ours, word)[0], struct.unpack_from('<I', ref, word)[0]
        vma = vma_of(stock, word)
        if a >> 24 == 0xEA and b >> 24 == 0xEA and vma is not None:
            ours_to, ref_to = lands_at(stock, branch_target(a, vma)), lands_at(stock, branch_target(b, vma))
            if ours_to is not None and ours_to == ref_to:
                return None
    return '%d bytes differ, first at 0x%x' % (len(rest), rest[0])


def check(path):
    name = os.path.basename(path)
    stock = open(path, 'rb').read()
    ours, why = run_patcher(path)
    script = os.path.join(PATCHES, name + '.sh')
    if not os.path.exists(script):
        return ('declined', why) if ours is None else ('DIFFERENT', 'patched a binary that has no static patch')
    ref, problem = apply_static(script, stock)
    if ref is None:
        return 'SKIPPED', problem
    if ours is None:
        return 'declined', why
    if ours == ref:
        return 'identical', ''
    if len(ours) != len(ref):
        return 'DIFFERENT', 'size changed'
    why = explain(stock, ours, ref)
    return ('equivalent', '') if why is None else ('DIFFERENT', why)


def version_key(name):
    target, build = name.split('.', 1)
    model, version = build.split('_')
    return target, model, [int(x) for x in version.split('.')]


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else PATCHES
    expected = {}
    for line in open(os.path.join(HERE, 'validate.expected')):
        line = line.split('#')[0].split()
        if line:
            expected[line[0]] = line[1]

    names = [n for n in os.listdir(directory) if re.fullmatch(r'(K3SysUi|gkapi)\.K[A-Z0-9]+_[0-9.]+', n)]
    if not names:
        sys.exit('no stock binaries in %s' % directory)

    failed = 0
    for name in sorted(names, key=version_key):
        result, detail = check(os.path.join(directory, name))
        want = expected.get(name, 'identical')
        ok = result == want
        failed += not ok
        print('%-4s %-24s %-10s %s' % ('ok' if ok else 'FAIL', name, result, detail if ok else '(expected %s) %s' % (want, detail)))
    print('%d binaries, %d failed' % (len(names), failed))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
