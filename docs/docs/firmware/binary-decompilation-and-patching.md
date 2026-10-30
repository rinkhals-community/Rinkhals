---
title: Binary decompilation and patching
---

I use [Ghidra](https://github.com/NationalSecurityAgency/ghidra) and [Binary Ninja](https://github.com/NationalSecurityAgency/ghidra) to work on binary decompilation / patching.

I find Binary Ninja is good to quickly load binaries and browse them when you already know what you want or the file structure.

Ghidra has more tools to explore and understand how things work. It also has a scripts system to automate some tasks, like for Go decompilation as described below.

## General

In Anycubic Kobra firmwares, there are a few main binaries:

- **K3SysUi** responsible for the screen UI, written in C/C++
- **gklib** the reimplementation of Klipper (aka. GoKlipper), written in Go
- **gkapi** the API / MQTT / internal orchestrator, written in Go
- **gkcam** reponsible for the attached USB camera and cloud streaming, written in C++

## Go decompilation

!!! note

    [https://cujo.com/blog/reverse-engineering-go-binaries-with-ghidra/](https://cujo.com/blog/reverse-engineering-go-binaries-with-ghidra/) explains quite well why Go decompilation is complex

While C++ decompiles quite well, Go is quite bad as you will get unnamed functions and many strings that are concatenated together, without references.

I took the scripts from the link above and adapted them for newer versions of Go used for Anycubic products.

??? info "Here are the scripts"

    :octicons-download-16: [find_dynamic_strings.py](../assets/attachments/binary-decompilation-and-patching/find_dynamic_strings.py)

    :octicons-download-16: [find_static_strings.py](../assets/attachments/binary-decompilation-and-patching/find_static_strings.py)

    :octicons-download-16: [go_func.py](../assets/attachments/binary-decompilation-and-patching/go_func.py)

    :octicons-download-16: [type_extract.py](../assets/attachments/binary-decompilation-and-patching/type_extract.py)

Once downloaded, place the scripts in Ghidra directory, then:

- Window > Script Manager
- Click the icon on the top right to specify the script location
- You’ll see the scripts in a “goscripts” directory in the list
- You can now double click on a script to run it

<div class="grid cards" markdown>
![](../assets/binary-decompilation-and-patching/binary-decompilation-and-patching-1.png)

![](../assets/binary-decompilation-and-patching/binary-decompilation-and-patching-2.png)
</div>

Then after Ghidra analysis is complete, I usually run `go_func.py` then `find_dynamic_strings.py` and `find_static_strings.py`.

## Binary patching in Rinkhals

Rinkhals injects a menu entry in the UI process in order to provide a touch UI experience to manage apps, updates and more. I chose to replace the “Support” menu item to avoid people having issues with Rinkhals calling Anycubic support.

To do that, patch scripts are provided in every Rinkhals release for supported firmware versions.

This is the patch generation process (in `/3-rinkhals/opt/rinkhals/patches/create-patches.py`)
- Using `pwntools` this script will dynamically patch a binary to generate a new patched one
- Then it will compare the original binary with the patch and generate a diff
- The diff is then formatted as a patch script that checks for the right input and then apply the patch
## Recoverable native executable preparation

`start.sh` uses `native-binaries.py` for `gkapi` and `K3SysUi`. The native
processes must be stopped before preparation. A boot-local `native-start.lock`
serializes the entire startup, including launch and restoration. An abruptly
killed startup leaves the lock for the remainder of that boot; reboot clears
`/tmp`. Do not remove the lock while a startup could still be running.

The helper reads the generated profile's Before/After MD5 values and validates
both targets before changing either. It retains one verified stock `.original`
per executable across boots. A legacy `.original` is reused if its hash matches.
After a firmware change it is replaced only from a current executable matching
the new profile. Unknown bytes are never adopted as an original; `.1` is not a
recovery source. If neither source matches, preparation fails for manual recovery.

Copies are written to private staging names in the same directory, checked and
`fsync`ed before publication. Each namespace change is followed by directory
`fsync`. Patches must exit successfully and produce the expected After MD5 before
the normal executable name is replaced. The original is never consumed by a
rename. Recovery can therefore restart after another interrupted copy.

After launching the modified native process, a complete stock copy is staged at
`.patch`, then Linux `renameat2(RENAME_EXCHANGE)` swaps it with the normal name.
This preserves the running executable's dentry under `.patch` while restoring the
stock name without an absent-name interval. A hard link followed by replacement
is not equivalent: `/proc/PID/exe` would report the old name as deleted, contrary
to the native binaries' location expectations. A filesystem capability probe is
performed before executable changes; there is no unsafe two-rename fallback.
Python `ctypes`, a libc exporting `renameat2`, and filesystem/kernel support for
`RENAME_EXCHANGE` are required. Python is already used earlier in this startup.

Damaged files are not archived. Staging leftovers and an invalid `.patch` are
removed after successful restoration; the verified `.original` is retained.
An error leaves the disable marker in place. If verified stock recovery also
fails, startup stops without launching unverified native executables. The
existing loader's disable-marker policy is unchanged: this does not automatically
enable Rinkhals after an interrupted boot. Before operator re-enable, the normal
name can contain either the complete stock or complete patched executable.

### Validation limits

`tests/test_native_binaries.py` uses synthetic data, partial-copy failures,
checksum/patch errors, namespace/durability failure points and abrupt subprocess
exits, including two interruptions during recovery. A Linux host executable test
checks the running inode's `/proc/PID/exe` name through the exchange. No firmware
binary, production configuration or printer is used as a test fixture.

These are process-crash tests, not electrical power-cut tests or an eMMC cache
model. Before release, maintainers must verify the bundled Python/libc capability,
actual filesystem durability behavior, native location checks, stock fallback,
firmware upgrade and repeated power-loss recovery on supported hardware. The
reported 8-MiB truncation in issue #198 is evidence motivating the change, not
proof of its historical cause. This proposal does not repair an already-damaged
printer without a matching good original.
