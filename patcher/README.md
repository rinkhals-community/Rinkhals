# rinkhals-patcher

Patches Anycubic's `K3SysUi` and `gkapi` on the printer, for firmware Rinkhals
has no static patch for. It makes the same changes as
`files/3-rinkhals/opt/rinkhals/scripts/create-patch.py`, but finds the patch
locations in the binary instead of being told them per version.

`start.sh` uses the static patch for the running firmware when there is one.
The patcher only runs when there isn't, which today means a firmware that was
started with `.enable-rinkhals`.

## What it patches

- **K3SysUi**: the Support row of the settings menu becomes "Rinkhals" and
  opens the Rinkhals touch UI. Handled: Kobra 3, 3 Max and 3 V2, and Kobra S1
  and S1 Max from the firmware that moved Service Support to the Device page.
  See `layout.go` for how the row is found and checked.
- **gkapi**: the orcaSim server moves off port 80.

It refuses anything it can't verify, writes nothing in that case, and never
modifies its input. The Kobra 2 Pro and Kobra S1 firmware up to 2.5.8.8 are
refused on purpose; the static patches cover them.

## Checking it

    go test ./...
    go build -o rinkhals-patcher . && ./validate.py [directory of stock binaries]

`validate.py` compares the patcher's output with the static patch for every
stock binary it is given. Run it after any change here, and when adding
support for a new firmware: if the patcher's output for the new build isn't
identical to the new static patch, one of the two is wrong.
