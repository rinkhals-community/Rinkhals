# rinkhals-patcher

Patches Anycubic's `K3SysUi` and `gkapi` on the printer, at every startup. It
finds the places to change in the binary itself, so there is no patch file per
firmware version.

## What it patches

- **K3SysUi**: the Support row of the settings menu becomes "Rinkhals" and
  opens the Rinkhals touch UI. Handled: Kobra 2 Pro, Kobra 3, 3 Max and 3 V2,
  Kobra S1 and S1 Max. See `layout.go` for how the row is found and checked.
- **gkapi**: the orcaSim server moves off port 80.

It refuses anything it can't verify, writes nothing in that case, and never
modifies its input.

## Known firmware and patches.txt

`files/3-rinkhals/opt/rinkhals/patches/patches.txt` lists every firmware
Rinkhals has been checked on, with the MD5 of each stock binary and the MD5 the
patcher must turn it into. `start.sh` uses it at startup:

- **Firmware in the list:** the binary must be the stock one, and the patched
  copy must have the recorded MD5. Otherwise the binary starts unpatched.
- **Firmware not in the list** (only reached with `.enable-rinkhals`): the
  patcher runs with nothing to compare its output with.

The recorded results were first taken when the patcher's output was compared
with the hand-checked static patches Rinkhals shipped before (the `.sh` files
in `patches/`, up to release 20261118_02_test). For the 42 builds whose
firmware we had: every `gkapi` and 17 `K3SysUi` came out byte-identical, 22
`K3SysUi` differed only in unreachable bytes after the new label or in a return
that skips a no-op or a jump to the same place, and 3 (KS1 2.5.9.9 and 2.6.0.0,
KS1M 2.1.6) hook the first instruction of the Support row where the static
patch hooked five instructions later behind a row check that is always true
there. Four builds are listed as `unverified` because their firmware is not
archived anywhere (K3 2.4.6.4, K3 V2 1.1.2.5 and 1.1.2.7, KS1 2.7.0.7).

## Checking it

    go test ./...
    go build -o rinkhals-patcher . && ./validate.py [directory of stock binaries]

`validate.py` runs the patcher on stock binaries and compares the result with
`patches.txt`. Run it after any change here: a different result for a known
firmware means printers on that firmware would start unpatched.

## Adding a firmware

Add the version to `files/3-rinkhals/manifest.json` and run
`build/prepare-version.sh`, which downloads the firmware and calls
`validate.py --add`. Read what the patcher logs for the new build (which menu
it found, where the Support row is), then test on a printer: the Rinkhals entry
must be where Support was and open the Rinkhals menu, and every other row must
still do what it did.

If the patcher refuses a new firmware, the menu changed in a way it doesn't
know. `layout.go` describes the menu shapes it handles.
