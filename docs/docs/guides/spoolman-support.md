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

### What the gate is called

A gate is named from its RFID tag where the tag allows it: a stock Anycubic tag, or a
hand-written one with a configured vendor code, parses to a vendor, a series and a colour name
(see [Tags that carry the Spoolman ID](#tags-that-carry-the-spoolman-id)). Where the tag says
nothing - an untagged spool, a third-party tag, a vendor code that is not configured - a gate
with a spool assigned is named from Spoolman instead: the spool's **vendor**, and its
**filament name** with the vendor put in front unless the name already starts with it. The
colour and the material always come from the tag.

Rinkhals reads the spool again every ten minutes, so a rename in Spoolman reaches the gate
without a restart. If Spoolman cannot be reached, or the spool is gone from it, the gate keeps
the tag's own description and is looked up again a minute later.

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
  "Basic PLA Black" reports the same SKU. Two rolls of the same product are
  indistinguishable to the ACE.

OpenSpool tags read by recent [OpenCubic](https://github.com/Jupsi/OpenCubic) firmware are not
in this group: their `OS-<spool_id>` or `OS-<chip UID>` SKU is unique per roll, so swap
detection and remembering the assignment work for them (see
[Tags that carry the Spoolman ID](#tags-that-carry-the-spoolman-id)). Older firmware reports the
same `OPENSPOOL` for every OpenSpool tag, which does fall under the second case.

Nothing in what the ACE reports can resolve the other cases, so Rinkhals does not guess. The
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
MMU_GATE_SKUS: Gate #0 (unit 0 gate 0): SKU OS-24 - PLA FFFFFF, spool 24
MMU_GATE_SKUS: Gate #1 (unit 0 gate 1): SKU AHPLBR-107 - PLA 6B4226, no spool assigned
MMU_GATE_SKUS: Gate #2 (unit 0 gate 2): SKU no tag - PETG F8C1B8, spool 7
MMU_GATE_SKUS: Gate #3 (unit 0 gate 3): SKU AHPETK-102 - PETG 000000, no spool assigned
```

`no tag` is an untagged gate, and `OPENSPOOL` (an OpenSpool tag on older custom ACE firmware)
is skipped as described below; neither can use this tier. An `OS-…` SKU is unique per roll, so
it is not an article number either: to bind those, see
[Tags that carry the Spoolman ID](#tags-that-carry-the-spoolman-id).

**2. Material and colour**, when the first tier finds nothing. It has to exist as a fallback,
because the SKU is absent or uninformative more often than not:

- an untagged gate has no SKU at all
- OpenSpool tags are only readable on custom ACE firmware such as
  [OpenCubic](https://github.com/Jupsi/OpenCubic); stock firmware reads Anycubic tags only, and
  reports any other spool as untagged. What the hub reports as the SKU depends on the version:
    - **ACE 1 Pro CFW v1.1.2 / ACE 2 Pro CFW v1.0.7 or newer** (OpenCubic v1.0.3-beta.2 or
      newer): `OS-<spool_id>` when the tag's payload has a `spool_id` of 1 to 16 characters from
      `A-Z a-z 0-9 . _ -`; otherwise `OS-<chip UID>` in upper-case hex, for example
      `OS-04A1B2C3D4E5F6`; otherwise the literal `OPENSPOOL`. The SKU field holds at most 19
      characters, so a `spool_id` is only reported when `OS-` plus the ID fits that.
    - **Older firmware** always reports `OPENSPOOL` — the hub used the payload's `protocol`
      field as the SKU and discarded its `spool_id`.

  `OPENSPOOL` is skipped rather than matched on, since it would pair any two OpenSpool rolls
  regardless of what is on them. The `OS-` forms are unique per roll but are not an
  `article_number` either, so they are not a match for this tier; use
  [`sku_spool_id`](#tags-that-carry-the-spoolman-id) for those
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

### Tags that carry the Spoolman ID

If a tag already states which Spoolman spool it belongs to, Rinkhals can simply read that
instead of searching for it. This is **off by default**, and independent of `spool_auto_match`:
you can trust your own tags without also letting Rinkhals guess from the inventory.

`sku_spool_id` is a comma-separated list of the SKU formats your tags use:

```ini
[mmu_ace]
sku_spool_id: openspool, spoolkid_ac
```

| Format | SKU | Example | Written by |
|---|---|---|---|
| `openspool` | `OS-<digits>` | `OS-24` is Spoolman spool 24 | OpenCubic firmware on the ACE, for an OpenSpool tag whose `spool_id` is a number. `OS-04A1B2C3D4E5F6` contains letters, so it is a chip UID and is not read as an ID. |
| `spoolkid_ac` | `SM<digits>` | `SM8` is Spoolman spool 8 | [SpoolKid](#spoolkid-tags), in its Anycubic ACE tag format. Stock ACE firmware is enough. |
| `anycubic_style` | `<vendor>H<material><colour>-<digits>` | `THPLBK-25` is Spoolman spool 25 | You, with a tag-writing app. See [Writing your own tags](#writing-your-own-tags). |

Two more values stand on their own:

| Value | Meaning |
|---|---|
| `off` | Read nothing. **Default.** |
| `all` | Every format above. This also turns on any format added in a later Rinkhals release, so list the formats by name if you want to choose each new one yourself. |

Names are not case-sensitive, and the order does not matter. A name Rinkhals does not know is
skipped with a warning in the Moonraker log, and the rest of the list still applies. The formats
cannot overlap (`OS-` then digits, `SM` then digits, and a SKU with an `H` and a dash), so at most
one of them reads any SKU. A SKU that starts with `OS-` is only ever read by `openspool`.

Stock Anycubic SKUs — those with an empty or `A` vendor code, such as `AHPLBK-105` or
`HPL18-105` — are **never** read as an ID, whatever formats are on, including `all`. The number after their dash is a product or batch
code (101 to 108), not a per-roll serial, and taking it as a spool ID is the behaviour that was
removed in [#107](https://github.com/rinkhals-community/Rinkhals/issues/107). `OPENSPOOL` carries
nothing and is ignored.

An ID read off a tag is checked against Spoolman before it is used. Rinkhals binds the gate only
if **all** of these hold, and otherwise leaves it as it was and says why in the Moonraker log
(at INFO):

- the spool exists
- the spool is not archived
- the spool's filament material is the same as the gate's (ignoring case)

A gate that reports no material, or `unknown`, is never bound this way, as there is nothing to
check against. If Spoolman cannot be reached, the gate is tried again later. A refusal (spool
missing, archived, or of another material) is checked again after 5 minutes, on the next ACE
status change (not while the printer sits idle), so fixing the spool in Spoolman binds the gate
without reinserting it.

The ID is bound the same way an assignment you make yourself is, so it is remembered with the
tag's SKU, survives a restart, and is dropped when a different spool is put in the gate. A tag
with an ID is never guessed for: even with `spool_auto_match` on, a refused tag leaves the gate
unassigned rather than falling back to the inventory. `spool_auto_match` only runs for gates
whose tag carries no ID.

A tag moved to another gate takes its spool with it: when the gate that held it now reads empty
or a different roll, the new gate takes the spool over. Your own choices win over the tag: a gate
you have assigned is left alone, a gate you have cleared stays cleared until the spool in it
changes, and if another gate still holds the roll the spool was bound with (a duplicate tag, say),
this gate is left unassigned, a warning is logged, and it is looked at again after 5 minutes.

#### SpoolKid tags

SpoolKid writes RFID tags from your phone, with the filament data taken
straight from Spoolman. Of the tag formats it offers, only its Anycubic ACE one sets a SKU, and
that SKU is `SM` followed by the Spoolman spool ID: spool 8 is `SM8`. The ACE reads these tags
with its stock firmware. Turn the format on with:

```ini
[mmu_ace]
sku_spool_id: spoolkid_ac
```

- The ID is a plain decimal number straight after `SM`, with no dash: `SM-8` is not read. A
  leading zero is allowed (`SM08` is spool 8), and `SM0` is not an ID.
- An `SM` SKU says nothing about the filament, so the gate is named from the Spoolman spool
  instead (see [What the gate is called](#what-the-gate-is-called)). The spool is checked
  against the material the ACE reads off the tag.
- Because every roll gets its own ID, two rolls of the same filament in the ACE bind to their
  own Spoolman spools. Matching by `article_number` cannot tell those apart.
- Rinkhals cannot tell a SpoolKid tag from another brand's tag whose SKU happens to look like
  `SM<digits>`. With `spoolkid_ac` (or `all`) on, such a SKU is read as a spool ID too: the
  material check refuses most wrong IDs, and a tag with an ID is never auto-matched instead. If
  you use spools whose own tags have SKUs like that, leave `spoolkid_ac` off.

#### Writing your own tags

This is the `anycubic_style` format. With the Android *ACE RFID* app you can write NTAG215 tags
with a SKU of your choosing. Use the same layout Anycubic does, with your Spoolman spool ID after
the dash:

```
<vendor>H<material><colour>-<Spoolman spool ID>
```

The first `H` ends the vendor code: everything before it is the vendor, everything after it is
the filament code. The `H` is required. A SKU without one, such as `ATPLBK-25`, is not this
format and is not read.

- **Vendor** is 1 to 3 upper-case letters with no `H` in them. Empty or `A` means stock Anycubic
  (Anycubic sometimes leaves the `A` off, as in `HPL18-105`), and those are never read as an ID,
  so pick something else.
- **Material and colour** are the codes Anycubic uses, material first, then colour.
- **Spoolman spool ID** is a plain decimal number.

For example `THPLBK-25` is vendor `T`, `PL` basic PLA, `BK` black, Spoolman spool 25, and
`ATHPLBK-25` is the same with the two-letter vendor `AT`. Set `sku_spool_id: anycubic_style` to
have those read. The filament code is also what Rinkhals uses to name the filament in the UI. The
material codes are:

| Code | Material |
|---|---|
| `PL` | PLA Basic |
| `HS` | PLA High Speed |
| `PLP` | PLA Plus |
| `PE` | PETG |
| `PET` | PETG Translucent |
| `AS` | ASA |
| `YG` | PLA Matte |
| `SC` | PLA Silk |
| `TP` | TPU |

The colour codes are Anycubic's too (`BK` black, `BW` white, `RR` red, `DB` blue, and so on). An
unknown colour code is not an error; the colour is just not named.

The vendor code is your own. Teach Rinkhals the ones you use with `sku_vendor_prefixes`, a
comma-separated list of `CODE=Name`:

```ini
[mmu_ace]
sku_spool_id: anycubic_style
sku_vendor_prefixes: AT=Atomic, T=Tinmorry, V=Verbantin
```

With that, `ATHPLBK-25` is shown as Atomic basic PLA black, `THPLBR-1` as Tinmorry basic PLA
brown, and `VHPLVY-14` as Verbantin basic PLA yellow, bound to Spoolman spools 25, 1 and 14.
A code is 1 to 3 letters (case does not matter), and a code that contains `H` or is `A` (Anycubic, built in)
is refused with a warning, as is any entry that is not `CODE=Name`. A vendor code only changes
the name shown; the ID is read whether or not the code is listed.

`sku_vendor_prefixes` only matters if you write `anycubic_style` tags. OpenSpool and SpoolKid
SKUs carry no vendor code, and stock Anycubic tags are named without it, so leave it out if
you don't use hand-written tags.

The material check is what makes this safe to do by hand: a typo in the ID that lands on an
existing spool of a different material is refused rather than bound.

The `article_number` step of `spool_auto_match` is the wrong tool for these tags. Spoolman's
article number belongs to a *filament*, shared by all its rolls, whereas a tag like `THPLBR-1`
names one roll.

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
