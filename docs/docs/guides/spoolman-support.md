---
title: Spoolman support
---

Rinkhals can track filament usage in [Spoolman](https://github.com/Donkie/Spoolman) in two ways:

- **Per ACE gate** — bind each gate to a spool once, and the active spool follows the gate the
  printer loads, including at print start and at colour changes mid-print.
- **Per filament from the slicer** — a single active spool set by an `M555` in your filament
  start gcode. Use this when you have no ACE.

Both need Spoolman itself declared first. Pick one: on a printer with an ACE, loading a gate
sets the active spool from the gate mapping, which overrides anything `M555` set.

## Connect Spoolman

Add to `moonraker.custom.conf`:

```ini
[spoolman]
server: http://spoolman.domain:7912
sync_rate: 5
```

Restart Moonraker. Check the connection with:

```
http://<printer-ip>/server/spoolman/status
```

`spoolman_connected: true` means you are ready.

## Per ACE gate

Once `[spoolman]` is configured, the spool picker appears in Mainsail and Fluidd — Rinkhals
reports Happy Hare's `spoolman_support` as `readonly` whenever Spoolman is set up, and `off`
when it is not. There is nothing else to enable.

In **Mainsail**: *MMU* panel → *Edit Filaments* → pick a gate → **Choose Spool**.
In **Fluidd**: the equivalent dialog under the MMU widget.

The gate keeps its spool through the ACE's status polls, through a Moonraker restart and
through a reboot. From then on, whenever the printer loads that gate, Spoolman's active spool
follows and filament is debited to the right spool.

You can do the same from the console or a macro:

```
MMU_SET_SPOOL GATE=0 SPOOLID=12
MMU_SET_SPOOL GATE=1 SPOOLID=7
```

Write no space after `=`. `SPOOLID=-1` clears a gate's assignment, and `MMU_GATE_MAP RESET=1`
clears them all.

### Gates with no spool assigned

When the printer loads a gate you have not mapped, Spoolman's active spool is
**cleared** rather than left pointing at the previous gate's spool. Filament used
from an unmapped gate is therefore not tracked at all, instead of being charged to
whichever spool happened to be active before it.

If you map every gate you print from, this never comes up. If you mix mapped and
unmapped gates in one print, expect gaps in the usage figures rather than wrong ones.

### When an assignment is forgotten

An assignment is dropped when a **different** RFID product is inserted in that gate, since
that is clear evidence the spool it referred to is gone.

Rinkhals can also drop an assignment when a gate has read **empty** for a while, but that is
**off by default**, so an assignment never disappears without you doing something. To turn it
on, set the number of seconds in `moonraker.custom.conf`:

```ini
[mmu_ace]
spool_forget_after: 300
```

`0` (the default, or any negative value) never drops an assignment on a timer.

### Limitation: spools the ACE cannot tell apart

An assignment is remembered per gate and matched on the spool's RFID SKU. Two cases where that
is not enough:

- **Untagged spools** (third-party rolls, or anything the ACE reports without RFID data) have no
  SKU at all, so nothing distinguishes one from another. The assignment follows the *gate*. If
  you swap one untagged spool for another, re-pick the spool in the UI.
- **Stock Anycubic tags** carry a *product* code, not a per-spool serial — every roll of
  "Highspeed PLA Black" reports the same SKU. Two rolls of the same product are
  indistinguishable to the ACE.

Nothing in what the ACE reports can resolve either case, so Rinkhals does not guess. The
mapped spool's name and colour are shown per gate in the UI, so a stale assignment is visible
rather than silent — check it after swapping a spool. If you write your own RFID tags with a
unique SKU per physical roll, neither case applies and the default `spool_forget_after: 0` is a good fit.

### Assigning gates automatically

Rinkhals can map an unassigned gate for you, by matching what the ACE reports against your
Spoolman inventory. It is **off by default**, because a wrong match is silent: the matched spool
becomes the active spool when that gate loads, so the next print's usage is charged to it without
you having confirmed the match. Turn it on in `moonraker.custom.conf`:

```ini
[mmu_ace]
spool_auto_match: unique
```

| Value | Behaviour |
|---|---|
| `off` | Never match. Gates are only ever assigned by you. **Default.** |
| `unique` | Assign when exactly one Spoolman spool matches. If several match, leave the gate alone and log the candidates so you can pick. |
| `latest` | As `unique`, but when several match, take the one Spoolman used most recently. |

Two things are tried, in order.

**1. The RFID SKU, against Spoolman's `article_number`.** When the hub reports a SKU and a
filament in your library carries that exact string as its article number, that is the match and
colour is never consulted. Prefer this path where you can: an Anycubic tag's SKU — `AHPETK-102`,
say — names the product outright, so a hit is right by construction, and it does not depend on
your having typed a colour that agrees with the hub's to the byte.

Spoolman will not fill `article_number` in for you, so this tier does nothing until you set it.
It lives on the *filament*, not the spool: Spoolman UI → *Filaments* → edit → **Article number**.
The string to paste is the SKU the gate reports. Run `MMU_GATE_SKUS` in the console to list it
for every gate, along with the material, colour and assigned spool:

```
MMU_GATE_SKUS: Gate #0 (unit 0 gate 0): SKU OPENSPOOL - PLA FFFFFF, spool 3
MMU_GATE_SKUS: Gate #1 (unit 0 gate 1): SKU AHPLBR-107 - PLA 6B4226, no spool assigned
MMU_GATE_SKUS: Gate #2 (unit 0 gate 2): SKU no tag - PETG F8C1B8, spool 7
MMU_GATE_SKUS: Gate #3 (unit 0 gate 3): SKU AHPETK-102 - PETG 000000, no spool assigned
```

`no tag` is an untagged gate, and `OPENSPOOL` (an OpenSpool tag, read by custom ACE firmware)
is skipped as described below; neither can use this tier.

**2. Material and colour**, when the first tier finds nothing. It has to exist as a fallback,
because the SKU is absent or uninformative more often than not:

- an untagged gate has no SKU at all
- OpenSpool tags all report the literal string `OPENSPOOL` — the hub uses the payload's
  `protocol` field as the SKU and discards its `spool_id`. Rinkhals skips that value rather than
  matching on it, since it would pair any two OpenSpool rolls regardless of what is on them.
  This only applies if the ACE runs custom firmware that reads non-Anycubic tags, such as
  [OpenCubic](https://github.com/Jupsi/OpenCubic); stock firmware reads Anycubic tags only, and
  reports any other spool as untagged
- a stock Anycubic SKU is a *product* code, shared by every roll of that product — enough to
  identify the product, not the roll

Colour is matched exactly, not approximately — on a real inventory the nearest non-match to one
gate was only ΔE 3.41 (a transparent PETG against a matte white), which is well inside the
variation between two hand-entered hex values. Any tolerance wide enough to be useful is wide
enough to be wrong. Spoolman's own colour search defaults to a *similar-colour* match; Rinkhals
asks for an exact one.

**Archived spools are never matched.** Archiving a spool is how you retire it, so debiting one
would be wrong. Archive a roll when it runs out and it drops out of matching without your
having to unassign anything.

**Ambiguity is refused, not guessed.** Whichever tier matched, two rolls of the same product —
or of the same material and colour — cannot be told apart by any means: not by the printer, not
by Spoolman, not by looking at them. With
`unique` the gate stays unassigned and the log names the candidates. `latest` will pick one;
it is a guess, but a contained one, since the candidates are interchangeable rolls of the same
filament, so a wrong choice misattributes grams between two identical spools rather than
debiting something unrelated.

For matching to work, your Spoolman colours have to match what the ACE reports. Note that
colour and material belong to the **filament**, not the spool — Spoolman models a filament as
the product and a spool as one physical roll of it, so several rolls share one colour. Set the
filament's `color_hex` to the value shown in the MMU panel for that gate and every roll of it
matches.

That relationship is also where most ambiguity comes from: one filament with three rolls is
three candidates, and they are genuinely interchangeable.

#### Two things that will stop it working

**The ACE has to know what the filament is.** Matching uses the material and colour the *hub*
reports. A tagged spool supplies those itself. An untagged one does not until you set them on
the ACE screen — until then the gate reports no material and a black colour, and is skipped
rather than matched, since `#000000` would collide with every real black spool in your
inventory.

**A tag does not always read.** The same spool can be identified in one slot and not another,
depending on where the tag sits relative to the antenna. When it fails the gate looks exactly
like an untagged one, so if a tagged spool is not being matched, check whether the hub
actually read it — re-seating or rotating the spool usually fixes it.

#### When it runs, and when it leaves you alone

Matching is attempted when the spool in a gate **changes** — one goes in, or one is swapped for
another — and at startup for any gate that is not already mapped. It is deliberately not
attempted on every status refresh: the refresh runs continuously during a print, and the answer
for a given spool cannot change between one refresh and the next, so re-asking would cost a
Spoolman round trip per gate to be told the same thing.

**Clearing a gate yourself sticks.** If you unassign a gate — `SPOOLID=-1`, or *reset spool* in
the UI — the matcher will not put a spool back in it. Without that rule a wrong match could not
be corrected at all: you would clear the gate and the next refresh would re-apply exactly the
mapping you had just rejected. The clear is remembered the same way an assignment is, so it
survives a restart, and it is dropped by the same evidence: once a *different* spool is in that
gate, the gate is matchable again. Taking the spool out and putting it back also counts, so
that is the way to ask for another attempt.

`MMU_GATE_MAP RESET=1` is the exception — that means start over, so every gate becomes
matchable again.

## Per filament from the slicer

For a single active spool driven by the slicer, add to `printer.custom.cfg`:

```
[gcode_macro SET_SPOOL]
gcode:
    {{ action_call_remote_method("spoolman_set_active_spool", params) }}

[gcode_macro M555]
gcode:
    SET_SPOOL spool_id={{ params.S }}
```

and per filament, in Orca's filament start gcode:

```gcode
; filament start gcode
M555 S5
```

Note `spool_id` in lower case, and `S5` rather than `S=5`. Those are Moonraker's own parameter
name and the form that does not need a workaround: `SPOOL_ID=` only works because Rinkhals
patches `set_active_spool` to accept it, and `M555 S=5` yields `params.S == "=5"`, which is why
`kobra.py` has to strip a leading `=`. Both spellings work today; these are the ones that would
still work without the compatibility shims.

This sets one active spool for the whole printer, and is the right choice on a printer with
no ACE.

**Do not combine it with per-gate mapping.** With an ACE present, every load sets the active
spool from the gate's mapping — or clears it, if that gate has none — so whatever `M555` set
is replaced as soon as the printer loads a gate.

## Troubleshooting

| Symptom | Cause |
|---|---|
| No **Choose Spool** button | `[spoolman]` is not in `moonraker.custom.conf`, or Moonraker was not restarted. Check `/server/spoolman/status`. |
| "No matching spool" when typing an ID | The ID does not exist in your Spoolman instance. The UI only accepts IDs Spoolman reports. |
| Assignment disappears after a spool swap | Expected on untagged or same-product spools — see the limitation above. |
| Auto-match does not reassign a gate I cleared | Working as intended — a deliberate clear is remembered. Take the spool out and back in, assign it yourself, or `MMU_GATE_MAP RESET=1`. |
| Auto-match never assigns a gate | Check `spool_auto_match` is set, then run `grep -i auto-match app-moonraker.log` — every outcome says which it was. Nothing at all means it was never attempted: the gate is already assigned, you cleared it deliberately, or the spool has not changed since the last attempt. |
| Auto-match logs "found several spools [a, b] ... leaving it unassigned" | Several rolls share that article number, or that material and colour — often one filament with several spools. Pick one yourself, or set `spool_auto_match: latest`. |
| Auto-match logs "found no Spoolman spool" | Nothing in the library matches. Check the filament's `article_number`, or its material and colour against what the MMU panel shows for that gate. |
| Usage debited to the wrong spool | Check the gate's mapped spool in the UI; `grep -i spoolman` in `app-moonraker.log` shows every activation. |
| Usage not tracked during part of a print | That stretch ran from a gate with no spool assigned — see above. |

Originally discussed on
[Discord](https://discord.com/channels/1332498592539345069/1332500553833517148/1354581748977238107).
