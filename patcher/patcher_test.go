package main

import (
	"encoding/binary"
	"strings"
	"testing"
)

// The real check is validate.py, which runs the patcher on stock firmware
// binaries. These tests cover the decisions on small hand-built code, so they
// run anywhere.

const testBase = 0x10000

// testImage builds a minimal ELF: one loadable segment holding the whole file
// at testBase, no sections.
func testImage(size int) []byte {
	img := make([]byte, size)
	copy(img, []byte{0x7f, 'E', 'L', 'F', 1, 1, 1})
	le := binary.LittleEndian
	le.PutUint16(img[16:], 2)        // ET_EXEC
	le.PutUint16(img[18:], 40)       // EM_ARM
	le.PutUint32(img[20:], 1)        // version
	le.PutUint32(img[28:], 52)       // phoff
	le.PutUint16(img[40:], 52)       // ehsize
	le.PutUint16(img[42:], 32)       // phentsize
	le.PutUint16(img[44:], 1)        // phnum
	le.PutUint16(img[46:], 40)       // shentsize
	le.PutUint32(img[52:], 1)        // PT_LOAD
	le.PutUint32(img[56:], 0)        // offset
	le.PutUint32(img[60:], testBase) // vaddr
	le.PutUint32(img[64:], testBase) // paddr
	le.PutUint32(img[68:], uint32(size))
	le.PutUint32(img[72:], uint32(size))
	return img
}

const (
	tCallback = testBase + 0x100
	tRefresh  = testBase + 0x400
	tSwitch   = testBase + 0x800 // QStackedWidget::setCurrentIndex
	tStatus   = testBase + 0x810 // BottomStatusBarUiDisplay
	tOther    = testBase + 0x820
	tExit     = tCallback + 0xF0
)

// k3Menu lays out a Kobra 3 style settings callback: five rows, each calling
// the status bar and then the page switch. rows lets a test replace a row, and
// maxRow sets the highest row the dispatch accepts (4 on the real menu).
func k3Menu(t *testing.T, rows map[int][]uint32, maxRow uint32) *Patcher {
	t.Helper()
	img := testImage(0x1000)
	put := func(addr uint64, words ...uint32) {
		for i, w := range words {
			binary.LittleEndian.PutUint32(img[addr-testBase+uint64(i)*4:], w)
		}
	}
	rowAddr := func(i int) uint64 { return tCallback + 0x40 + uint64(i)*0x20 }

	put(tCallback,
		0xE92D4800,        // push {fp, lr}
		0xE28DB004,        // add fp, sp, #4
		strR0Fp|8,         // str r0, [fp, #-8]
		CmpImm(3, maxRow), // cmp r3, #maxRow
		0x908FF103,        // addls pc, pc, r3, lsl #2
		Branch(tCallback+0x14, tExit))
	for i := 0; i <= int(maxRow); i++ {
		entry := tCallback + 0x18 + uint64(i)*4
		put(entry, Branch(entry, rowAddr(i)))
		code, ok := rows[i]
		if !ok {
			a := rowAddr(i)
			code = []uint32{
				ldrR0Fp | 8,
				BranchLink(a+4, tStatus),
				MovImm(1, uint32(0x10+i)),
				BranchLink(a+12, tSwitch),
				Branch(a+16, tExit),
			}
		}
		put(rowAddr(i), code...)
	}
	put(tExit, 0xE8BD8800) // pop {fp, pc}
	return testPatcher(t, img)
}

// testPatcher wraps an image and registers the symbols the test menu uses.
func testPatcher(t *testing.T, img []byte) *Patcher {
	t.Helper()
	p, err := NewPatcher(img)
	if err != nil {
		t.Fatal(err)
	}
	sym := func(name string, addr, size uint64) {
		p.syms[".symtab/"+name] = symbol{addr: addr, size: size, ok: true}
	}
	sym(layouts[1].callback, tCallback, 0x100)
	sym(symSupportRefresh, tRefresh, 0x200)
	sym(symSetCurrentIndex, tSwitch, 4)
	sym(symStatusBar, tStatus, 4)
	sym("system", tOther, 4)
	sym("_ZN8GobalVar7OsSleepEi", tOther+4, 4)
	sym("_ZN10MainWindow20AcDisplayWaitHandlerEhh", tOther+8, 4)
	sym(layouts[1].waitHide, tOther+12, 4)
	return p
}

// patched returns a Patcher over p's image with its edits applied.
func patched(t *testing.T, p *Patcher) *Patcher {
	t.Helper()
	img := make([]byte, len(p.data))
	p.overlay(0, img)
	return testPatcher(t, img)
}

func TestBranchEncoding(t *testing.T) {
	for _, c := range []struct{ from, to uint64 }{{0x10000, 0x10008}, {0x20000, 0x10000}, {0x10000, 0x3FFFFC}} {
		for _, w := range []uint32{Branch(c.from, c.to), BranchLink(c.from, c.to), BranchEqual(c.from, c.to)} {
			if got := branchTarget(w, c.from); got != c.to {
				t.Errorf("branch 0x%x -> 0x%x decodes to 0x%x", c.from, c.to, got)
			}
		}
	}
	// Known encodings from the static patches: "b" two words ahead, "bl" backwards.
	if w := Branch(0x1000, 0x1008); w != 0xEA000000 {
		t.Errorf("b +8 = %08x", w)
	}
	if w := BranchLink(0x1008, 0x1000); w != 0xEBFFFFFC {
		t.Errorf("bl -8 = %08x", w)
	}
}

func TestHooksTheSupportRow(t *testing.T) {
	p := k3Menu(t, nil, 4)
	h, err := p.hookForLayout(&layouts[1], tCallback, 0x100)
	if err != nil {
		t.Fatal(err)
	}
	if want := uint64(tCallback + 0x40 + 4*0x20); h.site != want {
		t.Errorf("hook at 0x%x, want row 4 at 0x%x", h.site, want)
	}
	if h.returnTo != tExit {
		t.Errorf("returns to 0x%x, want 0x%x", h.returnTo, tExit)
	}
	if len(h.loadThis) != 2 || h.loadThis[0] != ldrR0Fp|8 || h.loadThis[1] != ldrR0R0 {
		t.Errorf("loadThis = %x", h.loadThis)
	}

	if err := p.installPayload(h); err != nil {
		t.Fatal(err)
	}
	if p.uiAlreadyPatched() {
		t.Error("the input must stay untouched")
	}
	p = patched(t, p)
	if !p.uiAlreadyPatched() {
		t.Error("payload not recognised after installing it")
	}
	// The hook now branches into AcSupportRefresh, and no other row changed.
	w, _ := p.read32(h.site)
	if to := branchTarget(w, h.site); !isBranchAL(w) || to <= tRefresh || to >= tRefresh+0x200 {
		t.Errorf("hook is %08x, going to 0x%x", w, to)
	}
	row3 := uint64(tCallback + 0x40 + 3*0x20)
	if w, _ := p.read32(row3); w != ldrR0Fp|8 {
		t.Errorf("row 3 was modified: %08x", w)
	}
}

func TestRefusesUnexpectedMenus(t *testing.T) {
	row4 := uint64(tCallback + 0x40 + 4*0x20)
	cases := map[string][]uint32{
		"extra call":   {BranchLink(row4, tOther), BranchLink(row4+4, tStatus), BranchLink(row4+8, tSwitch), Branch(row4+12, tExit)},
		"missing call": {ldrR0Fp | 8, BranchLink(row4+4, tSwitch), Branch(row4+8, tExit)},
		"wrong order":  {BranchLink(row4, tSwitch), BranchLink(row4+4, tStatus), Branch(row4+8, tExit)},
		"conditional":  {BranchLink(row4, tStatus), BranchEqual(row4+4, tExit), BranchLink(row4+8, tSwitch), Branch(row4+12, tExit)},
		"leaves":       {BranchLink(row4, tStatus), BranchLink(row4+4, tSwitch), Branch(row4+8, tOther)},
	}
	for name, code := range cases {
		p := k3Menu(t, map[int][]uint32{4: code}, 4)
		if _, err := p.hookForLayout(&layouts[1], tCallback, 0x100); err == nil {
			t.Errorf("%s: hooked a row that doesn't look like Support", name)
		}
	}

	// A sixth row means the menu changed; Support may no longer be row 4.
	p := k3Menu(t, nil, 5)
	if _, err := p.hookForLayout(&layouts[1], tCallback, 0x100); err == nil {
		t.Error("hooked a menu with six rows")
	}
}

func TestPageIndexAndUniqueRow(t *testing.T) {
	p := k3Menu(t, nil, 4)
	sw, _ := p.function(symSetCurrentIndex)
	st, _ := p.function(symStatusBar)
	row := func(i int) *rowCode {
		c, err := p.readRow(tCallback+0x40+uint64(i)*0x20, tCallback, 0x100)
		if err != nil {
			t.Fatal(err)
		}
		return c
	}
	if err := p.checkRow(row(3), []uint64{st, sw}, 0x13); err != nil {
		t.Errorf("row 3 switches to page 0x13: %v", err)
	}
	if err := p.checkRow(row(3), []uint64{st, sw}, 3); err == nil {
		t.Error("accepted the wrong page number")
	}

	// With onlyRowWithShape, a second row of the same shape is ambiguous.
	l := layouts[1]
	l.onlyRowWithShape = true
	if _, err := p.hookForLayout(&l, tCallback, 0x100); err == nil || !strings.Contains(err.Error(), "both look like") {
		t.Errorf("ambiguous rows not refused: %v", err)
	}
}

func TestPayloadMustFit(t *testing.T) {
	p := k3Menu(t, nil, 4)
	h, err := p.hookForLayout(&layouts[1], tCallback, 0x100)
	if err != nil {
		t.Fatal(err)
	}
	p.syms[".symtab/"+symSupportRefresh] = symbol{addr: tRefresh, size: 0x120, ok: true}
	if err := p.installPayload(h); err == nil {
		t.Error("wrote a payload past the end of AcSupportRefresh")
	}
	if len(p.edits) != 0 {
		t.Errorf("%d edits left behind although the payload didn't fit", len(p.edits))
	}
}

func TestRefusesTruncatedBinary(t *testing.T) {
	img := testImage(0x1000)
	if _, err := NewPatcher(img[:0x800]); err == nil {
		t.Error("accepted a binary shorter than its headers say")
	}
}
