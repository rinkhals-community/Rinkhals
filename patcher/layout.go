package main

import "fmt"

// Where the Rinkhals entry goes.
//
// Rinkhals takes over the Support row of the settings menu. Two things have to
// be found in the binary: which row that is, and the code that runs when it is
// tapped.
//
// Which row: the menu's labels are set by one function, which builds an array
// of strings in row order:
//
//	ldr r1, [pc, #..] ; add r1, pc, r1 ; mov r0, <slot 0> ; bl QString(...)
//	ldr r1, [pc, #..] ; add r1, pc, r1 ; mov r0, <slot 1> ; bl QString(...)
//	...
//
// The Support row is the position of the Support label in that array, and the
// length of the array is the number of rows. So a firmware that adds, removes
// or reorders rows is still handled. (The Kobra 2 Pro is the exception, see
// its layout.)
//
// The code for the row: on most firmware the tap callback picks the row
// through a compiler-generated jump table:
//
//	cmp   rX, #N                  ; N = highest row
//	addls pc, pc, rX, lsl #2      ; rX <= N: pc = (here + 8) + rX * 4
//	b     default
//	b     row0
//	b     row1
//	...
//
// Each row's code runs only for that row, so we replace the first instruction
// of the Support row's code with a branch to our payload. No row check is
// needed, and no other row is touched. The jump table must have as many rows
// as there are labels, and the Support row's code has to make exactly the
// calls it makes on every known build. If anything is off, the patcher refuses
// and the binary is left alone.
//
// The other two shapes are described at pageIsRow and subPage below.

type dispatch int

const (
	// jumpTable: the callback has a jump table and the Support row's code
	// is hooked at its first instruction.
	jumpTable dispatch = iota
	// pageIsRow: the callback has no per-row code, it shows page number
	// "row" for whichever row was tapped. The payload starts with a check
	// for the Support row. Kobra S1 up to 2.5.8.8.
	pageIsRow
	// subPage: one callback serves several menu pages. The Support row's
	// code first checks that the main settings page is showing
	// ("cmp rX, #1; beq ..."), and that conditional branch is what we
	// redirect. Kobra 2 Pro.
	subPage
)

type layout struct {
	name string
	// labels is the function that sets the menu's labels, and label the text
	// of the Support row, which becomes newLabel.
	labels          string
	label, newLabel string
	// fixedRow and fixedRows are used when labels is empty: the row is then
	// known instead of read from the binary.
	fixedRow, fixedRows int
	// callback is the function that runs when a row is tapped.
	callback string
	dispatch dispatch
	// closure is set when callback is a lambda: its first argument then
	// points at a closure whose first field is the MainWindow, instead of at
	// the MainWindow itself.
	closure bool
	// calls lists the functions the Support row's code calls, in order. The
	// last one is always the page switch.
	calls []string
	// waitHide hides the "please wait" overlay; it is called with waitHideArg.
	waitHide    string
	waitHideArg uint32
}

const (
	symSetCurrentIndex = "_ZN14QStackedWidget15setCurrentIndexEi"
	symStatusBar       = "_ZN10MainWindow24BottomStatusBarUiDisplayEh"
	symModelIndexRow   = "_ZNK11QModelIndex3rowEv"
	symWaitHandler     = "_ZN10MainWindow20AcDisplayWaitHandlerEhh"
)

var layouts = []layout{
	{
		// Kobra S1 and S1 Max, Settings > Device: Printer Information, ACE
		// Information, CN Code, Service Support, (Export logs).
		// KS1 2.5.9.9 and later, every KS1M.
		name:        "Kobra S1 device settings",
		labels:      "_ZN10MainWindow24AcSettingDeviceUiReflashEv",
		label:       "Service Support",
		newLabel:    "Rinkhals",
		callback:    "_ZZN10MainWindow21AcSettingDeviceUiInitEvENKUlRK11QModelIndexE0_clES2_",
		dispatch:    jumpTable,
		closure:     true,
		calls:       []string{symSetCurrentIndex},
		waitHide:    "_ZN10MainWindow17AcDisplayWaitHideEh",
		waitHideArg: 4,
	},
	{
		// Kobra S1 up to 2.5.8.8, Settings > General: Sound, Language, Sleep
		// Time, Service Support, System Restore.
		name:        "Kobra S1 general settings",
		labels:      "_ZN10MainWindow27AcSettingGeneralPageReflashEv",
		label:       "Service Support",
		newLabel:    "Rinkhals",
		callback:    "_ZZN10MainWindow26AcSettingGeneralPageUiInitEvENKUlRK11QModelIndexE0_clES2_",
		dispatch:    pageIsRow,
		closure:     true,
		waitHide:    "_ZN10MainWindow17AcDisplayWaitHideEh",
		waitHideArg: 4,
	},
	{
		// Kobra 3, 3 Max and 3 V2, Settings: Network, Print Settings, General
		// Settings, Device Informations, Customer Support.
		name:        "Kobra 3 settings",
		labels:      "_ZN10MainWindow16AcSettingRefreshEv",
		label:       "Customer Support",
		newLabel:    "Rinkhals",
		callback:    "_ZZN10MainWindow19AcSettingPageUiInitEvENKUlvE_clEv",
		dispatch:    jumpTable,
		closure:     true,
		calls:       []string{symStatusBar, symSetCurrentIndex},
		waitHide:    "_ZN10MainWindow17AcDisplayWaitHideEv",
		waitHideArg: 4,
	},
	{
		// Kobra 2 Pro, Settings: Support is the fifth of six rows. Its two
		// firmware builds were compiled differently (one optimised, one not)
		// and the labels are set in more than one way, so the row is written
		// down here. The model has had no firmware since 3.1.4. The label is
		// seven letters, hence "Rinkhal". There is no separate function to
		// hide the wait overlay; AcDisplayWaitHandler(0) does it.
		name:        "Kobra 2 Pro settings",
		label:       "Support",
		newLabel:    "Rinkhal",
		fixedRow:    4,
		fixedRows:   6,
		callback:    "_ZN10MainWindow23AcSettingListBtnReleaseEi",
		dispatch:    subPage,
		calls:       []string{symStatusBar, symSetCurrentIndex},
		waitHide:    symWaitHandler,
		waitHideArg: 0,
	},
}

// hook is a validated place to branch to the payload from.
type hook struct {
	layout *layout
	// site is the instruction that becomes a branch to the payload, and
	// ifEqual says the branch is a "beq" replacing a "beq" (subPage).
	site    uint64
	ifEqual bool
	// guard, when set, makes the payload start with a row check (pageIsRow).
	guard *guard
	// returnTo is where the payload continues once the Rinkhals UI closes.
	returnTo uint64
	// loadThis are the instructions that put the MainWindow pointer in r0.
	loadThis []uint32
	// labelAt is the file offset of the Support label.
	labelAt uint64
}

// guard is the row check at the start of the payload: run the instruction the
// hook replaced, and unless reg holds row, go back to where the hook was.
type guard struct {
	replaced uint32
	reg      uint32
	row      int
	resume   uint64
}

// maxRowInsts bounds how much of a row's code we follow. The Support rows are
// 6 to 13 instructions long.
const maxRowInsts = 16

// maxRows bounds the size of a menu we believe in.
const maxRows = 16

// rowCode is the straight-line code of one row, up to its closing branch.
type rowCode struct {
	start      uint64
	insts      []uint32 // without the closing branch
	exitTarget uint64   // where the closing "b" goes
}

// findHook picks the layout this binary uses and validates the Support row.
func (p *Patcher) findHook() (*hook, error) {
	var tried []string
	for i := range layouts {
		l := &layouts[i]
		cb, size, ok := p.symbol(l.callback)
		if !ok {
			continue
		}
		h, err := p.hookForLayout(l, cb, size)
		if err == errNotThisMenu {
			continue
		}
		if err != nil {
			tried = append(tried, fmt.Sprintf("%s: %v", l.name, err))
			continue
		}
		return h, nil
	}
	if len(tried) == 0 {
		return nil, fmt.Errorf("no known settings menu in this binary")
	}
	return nil, fmt.Errorf("settings menu doesn't look as expected (%s)", tried[0])
}

// errNotThisMenu means the Support label isn't on this layout's menu.
var errNotThisMenu = fmt.Errorf("the Support row is not on this menu")

func (p *Patcher) hookForLayout(l *layout, cb, size uint64) (*hook, error) {
	labelAt, ok := p.labelOffset(l.label)
	if !ok {
		return nil, errNotThisMenu
	}
	return p.hookWithLabel(l, cb, size, labelAt)
}

// hookWithLabel is hookForLayout once the Support label has been located.
func (p *Patcher) hookWithLabel(l *layout, cb, size, labelAt uint64) (*hook, error) {
	row, count := l.fixedRow, l.fixedRows
	if l.labels != "" {
		var err error
		if row, count, err = p.labelRow(l.labels, labelAt); err != nil {
			return nil, err
		}
	}

	var calls []uint64
	for _, name := range l.calls {
		addr, err := p.function(name)
		if err != nil {
			return nil, err
		}
		calls = append(calls, addr)
	}

	h := &hook{layout: l, labelAt: labelAt}
	var code *rowCode
	if l.dispatch == pageIsRow {
		if err := p.hookPageSwitch(h, cb, size, row); err != nil {
			return nil, err
		}
	} else {
		rows, err := p.jumpTable(cb, size)
		if err != nil {
			return nil, err
		}
		if len(rows) != count {
			return nil, fmt.Errorf("menu has %d labels but %d rows of code", count, len(rows))
		}
		start := rows[row]
		h.site = start
		if l.dispatch == subPage {
			if h.site, start, err = p.mainPageBranch(start, cb, size); err != nil {
				return nil, fmt.Errorf("row %d: %v", row, err)
			}
			h.ifEqual = true
		}
		if code, err = p.readRow(start, cb, size); err == nil {
			err = p.checkRow(code, calls)
		}
		if err != nil {
			return nil, fmt.Errorf("row %d: %v", row, err)
		}
		h.returnTo = code.exitTarget
	}

	var err error
	if l.closure {
		h.loadThis, err = p.thisFromClosure(cb)
	} else {
		h.loadThis, err = thisFromCall(code)
	}
	if err != nil {
		return nil, err
	}
	return h, nil
}

// labelRow reads the Support row's number, and the number of rows, from the
// function that sets the menu's labels. See the top of this file.
func (p *Patcher) labelRow(name string, labelAt uint64) (row, count int, err error) {
	fn, size, ok := p.symbol(name)
	if !ok {
		return 0, 0, errNotThisMenu
	}
	label, err := p.address(labelAt)
	if err != nil {
		return 0, 0, err
	}

	// Every "string literal in r1, then a call" in the function.
	type literalCall struct{ at, callee, str uint64 }
	var calls []literalCall
	for a := fn; a+16 <= fn+size; a += 4 {
		ldr, _ := p.read32(a)
		add, _ := p.read32(a + 4)
		// ldr r1, [pc, #imm] ; add r1, pc, r1
		if ldr&0xFFFFF000 != 0xE59F1000 || add != 0xE08F1001 {
			continue
		}
		rel, err := p.read32(a + 8 + uint64(ldr&0xFFF))
		if err != nil {
			continue
		}
		str := uint64(uint32(rel) + uint32(a+4+8))
		for _, at := range []uint64{a + 8, a + 12} {
			if bl, _ := p.read32(at); isBranchLinkAL(bl) {
				calls = append(calls, literalCall{at, branchTarget(bl, at), str})
				break
			}
		}
	}

	at := -1
	for i, c := range calls {
		if c.str != label {
			continue
		}
		if at >= 0 {
			return 0, 0, fmt.Errorf("the Support label is set twice")
		}
		at = i
	}
	if at < 0 {
		return 0, 0, errNotThisMenu
	}

	// The array is the run of calls to the same function around the label's,
	// one every eight instructions or so.
	const maxGap = 9 * 4
	sameRun := func(a, b literalCall) bool { return a.callee == b.callee && b.at-a.at <= maxGap }
	first, last := at, at
	for first > 0 && sameRun(calls[first-1], calls[first]) {
		first--
	}
	for last+1 < len(calls) && sameRun(calls[last], calls[last+1]) {
		last++
	}
	row, count = at-first, last-first+1
	if count < 2 || count > maxRows {
		return 0, 0, fmt.Errorf("found %d menu labels, which can't be right", count)
	}
	return row, count, nil
}

// jumpTable finds the row dispatch in a callback and returns where each row's
// code starts. The callback must contain exactly one dispatch.
func (p *Patcher) jumpTable(cb, size uint64) ([]uint64, error) {
	var rows []uint64
	found := 0
	for addr := cb + 4; addr+4 <= cb+size; addr += 4 {
		inst, err := p.read32(addr)
		if err != nil {
			return nil, err
		}
		// addls pc, pc, rX, lsl #2
		if inst&0xFFFFFFF0 != 0x908FF100 {
			continue
		}
		// preceded by cmp rX, #N on the same register
		prev, err := p.read32(addr - 4)
		if err != nil {
			return nil, err
		}
		if prev&0xFFF0FF00 != 0xE3500000 || (prev>>16)&0xF != inst&0xF {
			continue
		}
		found++
		rows = nil
		for i := uint64(0); i <= uint64(prev&0xFF); i++ {
			entry := addr + 8 + i*4
			b, err := p.read32(entry)
			if err != nil {
				return nil, err
			}
			target := branchTarget(b, entry)
			if !isBranchAL(b) || target < cb || target >= cb+size {
				return nil, fmt.Errorf("jump table entry %d is not a branch into the callback", i)
			}
			rows = append(rows, target)
		}
	}
	if found != 1 {
		return nil, fmt.Errorf("found %d row dispatches, expected 1", found)
	}
	return rows, nil
}

// readRow follows a row's code to its closing unconditional branch. It refuses
// anything that isn't straight-line code, so we know every instruction between
// the hook and the return.
func (p *Patcher) readRow(start, cb, size uint64) (*rowCode, error) {
	code := &rowCode{start: start}
	for i := uint64(0); i < maxRowInsts; i++ {
		addr := start + i*4
		inst, err := p.read32(addr)
		if err != nil {
			return nil, err
		}
		if isBranchAL(inst) {
			code.exitTarget = branchTarget(inst, addr)
			if code.exitTarget < cb || code.exitTarget >= cb+size {
				return nil, fmt.Errorf("leaves the callback")
			}
			return code, nil
		}
		if isBranch(inst) || writesPC(inst) || (inst&0x0F000000 == 0x0B000000 && !isBranchLinkAL(inst)) {
			return nil, fmt.Errorf("has a conditional or computed jump")
		}
		code.insts = append(code.insts, inst)
	}
	return nil, fmt.Errorf("is longer than %d instructions", maxRowInsts)
}

// checkRow verifies that a row's code makes exactly the expected calls, in
// order.
func (p *Patcher) checkRow(code *rowCode, calls []uint64) error {
	var got []uint64
	for i, inst := range code.insts {
		if isBranchLinkAL(inst) {
			got = append(got, branchTarget(inst, code.start+uint64(i)*4))
		}
	}
	if len(got) != len(calls) {
		return fmt.Errorf("makes %d calls, expected %d", len(got), len(calls))
	}
	for i := range got {
		if got[i] != calls[i] {
			return fmt.Errorf("call %d goes to 0x%x, expected 0x%x", i, got[i], calls[i])
		}
	}
	return nil
}

// mainPageBranch handles the subPage shape. The Support row's code starts by
// loading the number of the menu page that is showing and comparing it with 1,
// the main settings page:
//
//	ldr rX, [...]        ; one or two loads
//	cmp rX, #1
//	beq <show Support>   ; <- site
//
// It returns the beq and where it goes.
func (p *Patcher) mainPageBranch(start, cb, size uint64) (site, target uint64, err error) {
	for i := uint64(0); i < 4; i++ {
		addr := start + i*4
		inst, err := p.read32(addr)
		if err != nil {
			return 0, 0, err
		}
		if inst&0xFFF0FFFF == 0xE3500001 { // cmp rX, #1
			beq, err := p.read32(addr + 4)
			if err != nil {
				return 0, 0, err
			}
			target := branchTarget(beq, addr+4)
			if beq&0xFF000000 != 0x0A000000 || target < cb || target >= cb+size {
				return 0, 0, fmt.Errorf("no branch for the main settings page")
			}
			return addr + 4, target, nil
		}
		if inst&0xFE500000 != 0xE4100000 || writesPC(inst) { // ldr
			break
		}
	}
	return 0, 0, fmt.Errorf("doesn't start by checking which menu page is showing")
}

// hookPageSwitch handles the pageIsRow shape. The callback ends with
//
//	bl  QModelIndex::row
//	mov r3, r0
//	mov r1, r3
//	mov r0, r4               ; <- site
//	bl  QStackedWidget::setCurrentIndex
//	...                      ; <- returnTo
//
// so at the site the row is in r3 (and r1). The payload runs the replaced
// "mov r0, r4" and goes back to the page switch for every row but Support.
func (p *Patcher) hookPageSwitch(h *hook, cb, size uint64, row int) error {
	switchPage, err := p.function(symSetCurrentIndex)
	if err != nil {
		return err
	}
	rowOf, err := p.function(symModelIndexRow)
	if err != nil {
		return err
	}
	var call uint64
	for addr := cb; addr+4 <= cb+size; addr += 4 {
		if inst, _ := p.read32(addr); isBranchLinkAL(inst) && branchTarget(inst, addr) == switchPage {
			if call != 0 {
				return fmt.Errorf("switches pages in more than one place")
			}
			call = addr
		}
	}
	if call < cb+16 || call+8 > cb+size {
		return fmt.Errorf("no page switch found")
	}
	const (
		movR3R0 = 0xE1A03000
		movR1R3 = 0xE1A01003
		movR0R4 = 0xE1A00004
	)
	want := []uint32{BranchLink(call-16, rowOf), movR3R0, movR1R3, movR0R4}
	for i, w := range want {
		if inst, _ := p.read32(call - 16 + uint64(i)*4); inst != w {
			return fmt.Errorf("page switch isn't called with the tapped row")
		}
	}
	h.site = call - 4
	h.guard = &guard{replaced: movR0R4, reg: 3, row: row, resume: call}
	h.returnTo = call + 4
	return nil
}

// thisFromClosure builds the instructions that load the MainWindow pointer
// into r0 in a lambda: r0 arrives pointing at the closure, whose first field
// is the captured MainWindow*, and the prologue saves r0 to the stack with
// "str r0, [fp, #-off]". We reload that slot and dereference it.
func (p *Patcher) thisFromClosure(cb uint64) ([]uint32, error) {
	for i := uint64(0); i < 10; i++ {
		inst, err := p.read32(cb + i*4)
		if err != nil {
			return nil, err
		}
		if inst&maskImm12 == strR0Fp {
			return []uint32{ldrR0Fp | inst&0xFFF, ldrR0R0}, nil
		}
	}
	return nil, fmt.Errorf("callback doesn't save its closure pointer to the stack")
}

// thisFromCall finds how a member function's row code loads the MainWindow
// pointer: the row's first call is to another MainWindow method, so whatever
// it puts in r0 just before is "this". Accepted are a copy from a callee-saved
// register and a reload from the stack frame, both of which still hold when
// the payload runs.
func thisFromCall(code *rowCode) ([]uint32, error) {
	for i, inst := range code.insts {
		if !isBranchLinkAL(inst) {
			continue
		}
		for j := i - 1; j >= 0 && j >= i-2; j-- {
			prev := code.insts[j]
			movFromSaved := prev&0xFFFFFFF0 == 0xE1A00000 && prev&0xF >= 4 && prev&0xF <= 11
			if movFromSaved || prev&maskImm12 == ldrR0Fp {
				return []uint32{prev}, nil
			}
		}
		break
	}
	return nil, fmt.Errorf("can't tell where the row keeps the MainWindow pointer")
}
