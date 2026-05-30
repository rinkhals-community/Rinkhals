# K3SysUi Z-offset button shim

LD_PRELOAD shared library that restores the live Z-offset adjust button on the
K3SysUi print page without modifying the K3SysUi binary.

## What was removed

The Anycubic K3SysUi binary still contains the full Z-offset popup machinery:

- The popup widget itself (constructed at startup by
  `MainWindow::AcFilePrintSetZOffsetPageUiInit()`)
- The icon asset (`:/FilePrintPage/Zoffset_Item.svg` in the embedded Qt
  resource bundle)
- The dispatcher in `MainWindow::AcFilePrintPageUiInit::lambda(int)#12`,
  whose case `id == 10` reads the current offset from the device, formats it,
  updates the popup display label, and calls `popup->show()`

What was removed is just the button widget itself on the print page that
emits `clicked()` with id=10.

## What the shim does

1. Hooks `QButtonGroup::addButton(QAbstractButton*, int)` via LD_PRELOAD
   symbol interposition.
2. Detects the print-page button groups by watching for the strict id=0..9
   registration sequence. (K3SysUi also registers buttons at id=10 and id=11,
   but they ship hidden.)
3. After id=9 fires on a print-page group, captures the id=10 template button
   pointer for later use.
4. Constructs a fresh `QPushButton` parented to the top-level main window,
   sized 50x50 at (120, 120), with the embedded SVG icon loaded via
   `QIcon(":/FilePrintPage/Zoffset_Item.svg")`. SVG support is enabled by
   `dlopen("libQt5Svg.so.5")` from the shim's constructor.
5. Connects the button's `clicked(bool)` signal directly to
   `popup->show()` via Qt's string-based `QObject::connect`. The popup widget
   pointer is read from `MainWindow + 0x530` (the offset case 10 uses).
6. Mirrors the print page's visibility: when the print page widget gets a
   `QEvent::Show`/`Hide`, the injected button matches. Implemented by
   registering up to 4 ancestor pointers per template button and installing a
   global event filter on `qApp` that matches Show/Hide events against the
   registered ancestors.

## Status

Working end-to-end on KS1 firmware 2.7.2.1 with Rinkhals develop. Tap the
button on the active print page and the Z-offset popup opens; navigating to
other pages auto-hides the button.

Integrated into the Rinkhals build pipeline:

- Cross-compiled in CI via the `build-shim-zoffset` stage in the root
  `Dockerfile` (uses the same `ghcr.io/jbatonnet/armv7-uclibc:rinkhals` image
  as Moonraker's ARMv7 build). Output is `libzoffset.so` in this directory of
  the SWU bundle.
- Loaded by `files/3-rinkhals/start.sh` via `LD_PRELOAD` when K3SysUi is
  launched, after any binary patches have run on the K3SysUi binary. On by
  default; opt-out by removing the `.so`.
- The shim is inert unless `RINKHALS_ZOFFSET_INJECT=1` is set in the
  environment at K3SysUi launch; `start.sh` sets this for the default-on
  behavior.

Known follow-ups:

- Verify on the other supported printer models (K3, K3V2, K3M, KS1M, K2P).
  The popup widget offset is now discovered dynamically (see "Dynamic offset
  discovery" in `zoffset.cpp`); the assumption that case 10 in lambda(int)#12
  is Z-offset and the icon resource path are still binary-bound and worth
  spot-checking per model.
- The dynamic discovery falls back to KS1 2.7.2.1's known offset (0x530) on
  mismatch, so even when the auto-detect doesn't apply, KS1 keeps working.

## Environment variables

The shim is inert unless one of these is set when K3SysUi launches:

- `RINKHALS_ZOFFSET_LOG=1` - log diagnostics to stderr
- `RINKHALS_ZOFFSET_INJECT=1` - construct and inject the new button (the
  feature itself)
- `RINKHALS_ZOFFSET_UNHIDE=1` - legacy diagnostic: try to un-hide K3SysUi's
  existing id=10 button (does not work alone because of layout suppression;
  retained for debug)

With nothing set the shim does nothing.

## Build and run (on printer, for development)

```sh
# On the printer
mkdir -p /tmp/rinkhals-zoffset
cp zoffset.cpp /tmp/rinkhals-zoffset/
cd /tmp/rinkhals-zoffset
g++ -O2 -fPIC -shared -Wall -nostdlib -fvisibility=hidden \
    -o libzoffset.so zoffset.cpp -lc -lgcc -lstdc++

# Launch K3SysUi with the shim
killall K3SysUi
sleep 2
cd /userdata/app/gk
RINKHALS_ZOFFSET_LOG=1 RINKHALS_ZOFFSET_INJECT=1 \
LD_PRELOAD=/tmp/rinkhals-zoffset/libzoffset.so \
./K3SysUi > /tmp/zoffset.log 2>&1 &
```

## Verified targets

- KS1 / Anycubic firmware 2.7.2.1 / Qt 5.14.2 / ARM 32-bit hardfloat uClibc

## Failure modes and safety

The shim wraps every Qt construction call in a `SIGSEGV`/`sigsetjmp` trap. If
any of the unfamiliar internals (vtable assumptions, structure offsets, sret
ABI) misbehaves on a particular firmware, the affected injection is aborted
and K3SysUi continues running without our additions rather than crashing.
