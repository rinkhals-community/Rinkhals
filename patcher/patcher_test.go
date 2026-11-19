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
	tRefresh  = testBase + 0x400 // AcSupportRefresh, where the payload goes
	tLabels   = testBase + 0x600 // the function that sets the menu labels
	tSwitch   = testBase + 0x900 // QStackedWidget::setCurrentIndex
	tStatus   = testBase + 0x910 // BottomStatusBarUiDisplay
	tOther    = testBase + 0x920
	tString   = testBase + 0x930 // QString from a literal
	tRowOf    = testBase + 0x940 // QModelIndex::row
	tStrings  = testBase + 0xA00 // the labels, 0x10 apart
	tExit     = tCallback + 0xF0

	cbSize     = 0x100
	labelsSize = 0x300
)

// labelAt is the file offset of the i-th menu label.
func labelAt(i int) uint64 { return tStrings - testBase + uint64(i)*0x10 }

func layoutNamed(t *testing.T, name string) *layout {
	t.Helper()
	for i := range layouts {
		if layouts[i].name == name {
			l := layouts[i]
			return &l
		}
	}
	t.Fatalf("no layout %q", name)
	return nil
}

type image struct {
	t   *testing.T
	img []byte
}

func newImage(t *testing.T) *image { return &image{t, testImage(0x1000)} }

func (m *image) put(addr uint64, words ...uint32) {
	for i, w := range words {
		binary.LittleEndian.PutUint32(m.img[addr-testBase+uint64(i)*4:], w)
	}
}

// labels writes the function that sets the menu labels: one QString per row,
// built from the strings in order, like the compiler lays out an array
// initialiser. A second array follows after a gap, as on the real General
// page, to check it isn't counted.
func (m *image) labels(order []int) {
	pool := uint64(tLabels + 0x280)
	emit := func(a uint64, slot, str int) {
		lit := pool + uint64(slot)*4
		strAddr := tStrings + uint64(str)*0x10
		m.put(lit, uint32(strAddr)-uint32(a+4+8))
		m.put(a,
			0xE59F1000|uint32(lit-a-8), // ldr r1, [pc, #lit]
			0xE08F1001,                 // add r1, pc, r1
			0xE1A00005,                 // mov r0, r5
			BranchLink(a+12, tString),
			0xE2855004, // add r5, r5, #4
		)
	}
	for i, str := range order {
		emit(tLabels+0x10+uint64(i)*0x20, i, str)
	}
	far := uint64(tLabels + 0x10 + uint64(len(order))*0x20 + 0x40)
	emit(far, len(order), 14)
	emit(far+0x20, len(order)+1, 15)
}

// k3Menu lays out a Kobra 3 style settings callback: a jump table and one
// piece of code per row, each calling the status bar and then the page
// switch. rows lets a test replace a row's code.
func (m *image) k3Menu(count int, rows map[int][]uint32) {
	rowAddr := func(i int) uint64 { return tCallback + 0x40 + uint64(i)*0x18 }
	m.put(tCallback,
		0xE92D4800,                 // push {fp, lr}
		0xE28DB004,                 // add fp, sp, #4
		strR0Fp|8,                  // str r0, [fp, #-8]
		CmpImm(3, uint32(count-1)), // cmp r3, #highest row
		0x908FF103,                 // addls pc, pc, r3, lsl #2
		Branch(tCallback+0x14, tExit))
	for i := 0; i < count; i++ {
		entry := tCallback + 0x18 + uint64(i)*4
		m.put(entry, Branch(entry, rowAddr(i)))
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
		m.put(rowAddr(i), code...)
	}
	m.put(tExit, 0xE8BD8800) // pop {fp, pc}
}

func k3Row(i int) uint64 { return tCallback + 0x40 + uint64(i)*0x18 }

// patcher wraps the image and registers the symbols the test code uses.
func (m *image) patcher() *Patcher { return testPatcher(m.t, m.img) }

func testPatcher(t *testing.T, img []byte) *Patcher {
	t.Helper()
	p, err := NewPatcher(img)
	if err != nil {
		t.Fatal(err)
	}
	sym := func(name string, addr, size uint64) {
		p.syms[".symtab/"+name] = symbol{addr: addr, size: size, ok: true}
	}
	for _, l := range layouts {
		sym(l.callback, tCallback, cbSize)
		if l.labels != "" {
			sym(l.labels, tLabels, labelsSize)
		}
		sym(l.waitHide, tOther+12, 4)
	}
	sym(symSupportRefresh, tRefresh, 0x200)
	sym(symSetCurrentIndex, tSwitch, 4)
	sym(symStatusBar, tStatus, 4)
	sym(symModelIndexRow, tRowOf, 4)
	sym("system", tOther, 4)
	sym("_ZN8GobalVar7OsSleepEi", tOther+4, 4)
	sym(symWaitHandler, tOther+8, 4)
	return p
}

// patched returns a Patcher over p's image with its edits applied.
func patched(t *testing.T, p *Patcher) *Patcher {
	t.Helper()
	img := make([]byte, len(p.data))
	p.overlay(0, img)
	return testPatcher(t, img)
}

// payloadWords returns the payload's code, from its entry to the final branch.
func payloadWords(t *testing.T, p *Patcher, h *hook) []uint32 {
	t.Helper()
	w, _ := p.read32(h.site)
	var words []uint32
	for a := branchTarget(w, h.site); a < tRefresh+0x200; a += 4 {
		inst, _ := p.read32(a)
		words = append(words, inst)
		if isBranchAL(inst) && branchTarget(inst, a) == h.returnTo {
			return words
		}
	}
	t.Fatal("payload never returns")
	return nil
}

func TestBranchEncoding(t *testing.T) {
	for _, c := range []struct{ from, to uint64 }{{0x10000, 0x10008}, {0x20000, 0x10000}, {0x10000, 0x3FFFFC}} {
		for _, w := range []uint32{Branch(c.from, c.to), BranchLink(c.from, c.to), BranchEqual(c.from, c.to), BranchNotEqual(c.from, c.to)} {
			if got := branchTarget(w, c.from); got != c.to {
				t.Errorf("branch 0x%x -> 0x%x decodes to 0x%x", c.from, c.to, got)
			}
		}
	}
	// Known encodings: "b" two words ahead, "bl" backwards.
	if w := Branch(0x1000, 0x1008); w != 0xEA000000 {
		t.Errorf("b +8 = %08x", w)
	}
	if w := BranchLink(0x1008, 0x1000); w != 0xEBFFFFFC {
		t.Errorf("bl -8 = %08x", w)
	}
}

func TestHooksTheSupportRow(t *testing.T) {
	m := newImage(t)
	m.labels([]int{0, 1, 2, 3, 4})
	m.k3Menu(5, nil)
	p := m.patcher()
	h, err := p.hookWithLabel(layoutNamed(t, "Kobra 3 settings"), tCallback, cbSize, labelAt(4))
	if err != nil {
		t.Fatal(err)
	}
	if h.site != k3Row(4) {
		t.Errorf("hook at 0x%x, want row 4 at 0x%x", h.site, k3Row(4))
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
	if w, _ := p.read32(k3Row(3)); w != ldrR0Fp|8 {
		t.Errorf("row 3 was modified: %08x", w)
	}
}

// The row comes from where the Support label sits among the menu's labels, so
// a menu that gained, lost or reordered rows is followed.
func TestFollowsTheLabel(t *testing.T) {
	l := layoutNamed(t, "Kobra 3 settings")
	for _, c := range []struct {
		order []int
		want  int
	}{
		{[]int{0, 1, 2, 3, 4}, 4},
		{[]int{0, 4, 1, 2, 3}, 1},
		{[]int{4, 0, 1}, 0},
		{[]int{0, 1, 2, 3, 5, 6, 4, 7}, 6},
	} {
		m := newImage(t)
		m.labels(c.order)
		m.k3Menu(len(c.order), nil)
		h, err := m.patcher().hookWithLabel(l, tCallback, cbSize, labelAt(4))
		if err != nil {
			t.Errorf("%v: %v", c.order, err)
		} else if h.site != k3Row(c.want) {
			t.Errorf("%v: hooked 0x%x, want row %d at 0x%x", c.order, h.site, c.want, k3Row(c.want))
		}
	}
}

func TestRefusesWhenLabelsAndRowsDisagree(t *testing.T) {
	l := layoutNamed(t, "Kobra 3 settings")
	hookFor := func(order []int, rows int) error {
		m := newImage(t)
		m.labels(order)
		m.k3Menu(rows, nil)
		_, err := m.patcher().hookWithLabel(l, tCallback, cbSize, labelAt(4))
		return err
	}
	if err := hookFor([]int{0, 1, 2, 3, 4}, 6); err == nil || !strings.Contains(err.Error(), "5 labels but 6 rows") {
		t.Errorf("five labels, six rows of code: %v", err)
	}
	if err := hookFor([]int{0, 1, 4, 3, 4}, 5); err == nil || !strings.Contains(err.Error(), "twice") {
		t.Errorf("label used for two rows: %v", err)
	}
	if err := hookFor([]int{0, 1, 2, 3, 5}, 5); err != errNotThisMenu {
		t.Errorf("label not on this menu: %v", err)
	}
	// A label only set outside the array (here: the second, distant one) is a
	// one-row "menu".
	m := newImage(t)
	m.labels([]int{0, 1, 2, 3, 5})
	m.k3Menu(5, nil)
	if _, err := m.patcher().hookWithLabel(l, tCallback, cbSize, labelAt(14)); err == nil {
		t.Error("accepted a label from a different array")
	}
}

func TestRefusesUnexpectedRows(t *testing.T) {
	row4 := k3Row(4)
	cases := map[string][]uint32{
		"extra call":   {BranchLink(row4, tOther), BranchLink(row4+4, tStatus), BranchLink(row4+8, tSwitch), Branch(row4+12, tExit)},
		"missing call": {ldrR0Fp | 8, BranchLink(row4+4, tSwitch), Branch(row4+8, tExit)},
		"wrong order":  {BranchLink(row4, tSwitch), BranchLink(row4+4, tStatus), Branch(row4+8, tExit)},
		"conditional":  {BranchLink(row4, tStatus), BranchEqual(row4+4, tExit), BranchLink(row4+8, tSwitch), Branch(row4+12, tExit)},
		"leaves":       {BranchLink(row4, tStatus), BranchLink(row4+4, tSwitch), Branch(row4+8, tOther)},
	}
	for name, code := range cases {
		m := newImage(t)
		m.labels([]int{0, 1, 2, 3, 4})
		m.k3Menu(5, map[int][]uint32{4: code})
		if _, err := m.patcher().hookWithLabel(layoutNamed(t, "Kobra 3 settings"), tCallback, cbSize, labelAt(4)); err == nil {
			t.Errorf("%s: hooked a row that doesn't look like Support", name)
		}
	}
}

// Kobra S1 up to 2.5.8.8: no per-row code, the payload checks the row itself.
func TestPageIsRow(t *testing.T) {
	const call = tCallback + 0x40
	build := func(order []int, code ...uint32) *Patcher {
		m := newImage(t)
		m.labels(order)
		m.put(tCallback, 0xE92D4810, 0xE28DB008, strR0Fp|0x10)
		m.put(call-16, code...)
		return m.patcher()
	}
	good := []uint32{BranchLink(call-16, tRowOf), 0xE1A03000, 0xE1A01003, 0xE1A00004, BranchLink(call, tSwitch), 0xE1A00000}
	l := layoutNamed(t, "Kobra S1 general settings")

	p := build([]int{0, 1, 2, 4, 3}, good...)
	h, err := p.hookWithLabel(l, tCallback, cbSize, labelAt(4))
	if err != nil {
		t.Fatal(err)
	}
	if h.site != call-4 || h.returnTo != call+4 {
		t.Errorf("hook at 0x%x returning to 0x%x", h.site, h.returnTo)
	}
	if err := p.installPayload(h); err != nil {
		t.Fatal(err)
	}
	p = patched(t, p)
	words := payloadWords(t, p, h)
	w, _ := p.read32(h.site)
	at := branchTarget(w, h.site)
	if words[0] != 0xE1A00004 || words[1] != CmpImm(3, 3) || words[2] != BranchNotEqual(at+8, call) {
		t.Errorf("payload starts with %08x %08x %08x, want the replaced mov, cmp r3, #3 and bne to the page switch", words[0], words[1], words[2])
	}

	bad := append([]uint32(nil), good...)
	bad[2] = 0xE3A01002 // mov r1, #2: not the tapped row
	if _, err := build([]int{0, 1, 2, 4, 3}, bad...).hookWithLabel(l, tCallback, cbSize, labelAt(4)); err == nil {
		t.Error("hooked a page switch that isn't given the row")
	}
	twice := append(append([]uint32(nil), good...), BranchLink(call+8, tSwitch))
	if _, err := build([]int{0, 1, 2, 4, 3}, twice...).hookWithLabel(l, tCallback, cbSize, labelAt(4)); err == nil {
		t.Error("hooked a callback with two page switches")
	}
}

// Kobra 2 Pro: the row's code checks the menu page first, and that branch is
// what gets redirected. "this" is wherever the row's own code takes it from.
func TestSubPage(t *testing.T) {
	l := layoutNamed(t, "Kobra 2 Pro settings")
	show := uint64(tCallback + 0xC0)
	for name, c := range map[string]struct {
		head     []uint32 // start of row 4, up to the beq
		loadThis uint32
	}{
		"optimised":   {[]uint32{0xE5952474, 0xE3520001}, 0xE1A00005},                       // ldr r2, [r5, #0x474]; cmp r2, #1 / mov r0, r5
		"unoptimised": {[]uint32{ldrR0Fp | 0x3038, 0xE5933474, 0xE3530001}, ldrR0Fp | 0x38}, // ldr r3, [fp, #-0x38]; ldr r3, [r3, #0x474]; cmp r3, #1
	} {
		m := newImage(t)
		beq := k3Row(4) + uint64(len(c.head))*4
		row := append(append([]uint32(nil), c.head...), BranchEqual(beq, show), Branch(beq+4, tExit))
		m.k3Menu(6, map[int][]uint32{4: row})
		m.put(show, MovImm(1, 0), c.loadThis, BranchLink(show+8, tStatus), MovImm(1, 15), BranchLink(show+16, tSwitch), Branch(show+20, tExit))
		p := m.patcher()
		h, err := p.hookWithLabel(l, tCallback, cbSize, 0x800)
		if err != nil {
			t.Errorf("%s: %v", name, err)
			continue
		}
		if h.site != beq || !h.ifEqual || h.returnTo != tExit {
			t.Errorf("%s: hook at 0x%x (ifEqual %v) returning to 0x%x", name, h.site, h.ifEqual, h.returnTo)
		}
		if len(h.loadThis) != 1 || h.loadThis[0] != c.loadThis {
			t.Errorf("%s: loadThis = %x", name, h.loadThis)
		}
		if err := p.installPayload(h); err != nil {
			t.Fatal(err)
		}
		if w, _ := patched(t, p).read32(beq); w>>24 != 0x0A {
			t.Errorf("%s: the hook must stay conditional, got %08x", name, w)
		}
	}

	// Seven rows instead of six: the row is fixed for this model, so refuse.
	m := newImage(t)
	m.k3Menu(7, nil)
	if _, err := m.patcher().hookWithLabel(l, tCallback, cbSize, 0x800); err == nil {
		t.Error("hooked a Kobra 2 Pro menu with seven rows")
	}
}

func TestPayloadMustFit(t *testing.T) {
	m := newImage(t)
	m.labels([]int{0, 1, 2, 3, 4})
	m.k3Menu(5, nil)
	p := m.patcher()
	h, err := p.hookWithLabel(layoutNamed(t, "Kobra 3 settings"), tCallback, cbSize, labelAt(4))
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
