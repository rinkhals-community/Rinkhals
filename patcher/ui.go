package main

import (
	"bytes"
	"errors"
	"fmt"
	"log"
)

var errAlreadyPatched = errors.New("already patched")

const menuLabel = "Rinkhals"

// PatchUI adds the Rinkhals entry to K3SysUi's settings menu. Everything is
// located and checked first; the binary is only modified once the whole patch
// is known to apply.
func (p *Patcher) PatchUI() error {
	if p.uiAlreadyPatched() {
		return errAlreadyPatched
	}

	h, err := p.findHook()
	if err != nil {
		return err
	}
	log.Printf("%s: Support row at 0x%x, returning to 0x%x", h.layout.name, h.site, h.returnTo)

	if err := p.installPayload(h); err != nil {
		return err
	}
	if err := p.relabel(h.layout.label, menuLabel); err != nil {
		return err
	}
	p.patchIsCustomFirmware()
	return nil
}

// labelOffset returns the file offset of a NUL-terminated string in .rodata.
func (p *Patcher) labelOffset(s string) (uint64, bool) {
	rodata := p.f.Section(".rodata")
	if rodata == nil {
		return 0, false
	}
	idx := bytes.Index(p.data[rodata.Offset:rodata.Offset+rodata.Size], append([]byte(s), 0))
	if idx < 0 {
		return 0, false
	}
	return rodata.Offset + uint64(idx), true
}

func (p *Patcher) hasCString(s string) bool {
	_, ok := p.labelOffset(s)
	return ok
}

// relabel overwrites the start of a menu label with a shorter one. The bytes
// after the new terminator are left as they were, like the static patches do.
func (p *Patcher) relabel(old, new string) error {
	off, ok := p.labelOffset(old)
	if !ok || len(new) > len(old) {
		return fmt.Errorf("can't relabel %q", old)
	}
	return p.writeAt(off, append([]byte(new), 0))
}

// patchIsCustomFirmware makes GobalVar::isCustomFirmware() return 0. On the
// Kobra 3 family it scans /proc/*/cmdline for sshd, adbd and nginx and shows a
// "Non official firmware" warning when it finds one. Other models don't have
// the function.
func (p *Patcher) patchIsCustomFirmware() {
	addr, size, ok := p.symbol("_ZN8GobalVar16isCustomFirmwareEPKc")
	if !ok || size < 8 {
		return
	}
	if p.write32(addr, MovImm(0, 0)) == nil && p.write32(addr+4, movPcLr) == nil {
		log.Printf("isCustomFirmware() at 0x%x now returns 0", addr)
	}
}
