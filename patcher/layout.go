package main

import "fmt"

// Where the Rinkhals entry goes.
//
// On every firmware the patcher handles, tapping a row in the settings menu
// runs a callback that picks the row through a compiler-generated jump table:
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
// needed, and no other row is touched.
//
// Which row is Support can't be read from the binary: the menu labels are not
// referenced from the callback. It is known per firmware family, from the
// static patches in create-patch.py, and written down in layouts below. To
// keep a wrong assumption from hooking the wrong row, the row's code has to
// match the shape that Support has on every known build of that family. If
// anything is off, the patcher refuses and the binary is left alone.

type layout struct {
	name string
	// callback is the function holding the jump table.
	callback string
	// label is the menu text of the Support row. It must be present, and it
	// becomes "Rinkhals".
	label string
	// supportRow is the row Rinkhals takes over, and rows is how many rows the
	// jump table may have.
	supportRow       int
	minRows, maxRows int
	// calls lists the functions the Support row's code calls, in order. The
	// last one is always the page switch.
	calls []string
	// pageIndex, when >= 0, is the page number the row passes to the page
	// switch ("mov r1, #pageIndex" must be in the row's code).
	pageIndex int
	// onlyRowWithShape requires that no other row matches calls/pageIndex.
	onlyRowWithShape bool
	// waitHide is the function that hides the "please wait" overlay.
	waitHide string
}

const (
	symSetCurrentIndex = "_ZN14QStackedWidget15setCurrentIndexEi"
	symStatusBar       = "_ZN10MainWindow24BottomStatusBarUiDisplayEh"
)

var layouts = []layout{
	{
		// Kobra S1 and S1 Max, Settings > Device: Printer Information, ACE
		// Information, CN Code, Service Support, (Export logs).
		// KS1 2.5.9.9 and later, every KS1M.
		name:             "Kobra S1 device settings",
		callback:         "_ZZN10MainWindow21AcSettingDeviceUiInitEvENKUlRK11QModelIndexE0_clES2_",
		label:            "Service Support",
		supportRow:       3,
		minRows:          4,
		maxRows:          5,
		calls:            []string{symSetCurrentIndex},
		pageIndex:        3,
		onlyRowWithShape: true,
		waitHide:         "_ZN10MainWindow17AcDisplayWaitHideEh",
	},
	{
		// Kobra 3, 3 Max and 3 V2, Settings: five buttons, Support is the last.
		name:       "Kobra 3 settings",
		callback:   "_ZZN10MainWindow19AcSettingPageUiInitEvENKUlvE_clEv",
		label:      "Customer Support",
		supportRow: 4,
		minRows:    5,
		maxRows:    5,
		calls:      []string{symStatusBar, symSetCurrentIndex},
		pageIndex:  -1,
		waitHide:   "_ZN10MainWindow17AcDisplayWaitHideEv",
	},
}

// hook is a validated place to branch to the payload from.
type hook struct {
	layout *layout
	// site is the first instruction of the Support row's code.
	site uint64
	// returnTo is where the payload continues once the Rinkhals UI closes.
	returnTo uint64
	// loadThis are the instructions that put the MainWindow pointer in r0.
	loadThis []uint32
}

// maxRowInsts bounds how much of a row's code we follow. The Support rows are
// 8 to 13 instructions long.
const maxRowInsts = 16

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
		if !ok || !p.hasCString(l.label) {
			continue
		}
		h, err := p.hookForLayout(l, cb, size)
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

func (p *Patcher) hookForLayout(l *layout, cb, size uint64) (*hook, error) {
	rows, err := p.jumpTable(cb, size)
	if err != nil {
		return nil, err
	}
	if len(rows) < l.minRows || len(rows) > l.maxRows {
		return nil, fmt.Errorf("menu has %d rows, expected %d to %d", len(rows), l.minRows, l.maxRows)
	}

	var calls []uint64
	for _, name := range l.calls {
		addr, err := p.function(name)
		if err != nil {
			return nil, err
		}
		calls = append(calls, addr)
	}

	matches := func(row uint64) (*rowCode, error) {
		code, err := p.readRow(row, cb, size)
		if err != nil {
			return nil, err
		}
		return code, p.checkRow(code, calls, l.pageIndex)
	}

	code, err := matches(rows[l.supportRow])
	if err != nil {
		return nil, fmt.Errorf("row %d: %v", l.supportRow, err)
	}
	if l.onlyRowWithShape {
		for i, row := range rows {
			if i == l.supportRow || row == rows[l.supportRow] {
				continue
			}
			if _, err := matches(row); err == nil {
				return nil, fmt.Errorf("rows %d and %d both look like the Support row", i, l.supportRow)
			}
		}
	}

	loadThis, err := p.loadThis(cb)
	if err != nil {
		return nil, err
	}

	return &hook{layout: l, site: code.start, returnTo: code.exitTarget, loadThis: loadThis}, nil
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
// order, and passes the expected page number.
func (p *Patcher) checkRow(code *rowCode, calls []uint64, pageIndex int) error {
	var got []uint64
	sawPage := pageIndex < 0
	for i, inst := range code.insts {
		addr := code.start + uint64(i)*4
		if isBranchLinkAL(inst) {
			got = append(got, branchTarget(inst, addr))
		}
		if pageIndex >= 0 && inst == MovImm(1, uint32(pageIndex)) {
			sawPage = true
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
	if !sawPage {
		return fmt.Errorf("doesn't switch to page %d", pageIndex)
	}
	return nil
}

// loadThis builds the instructions that load the MainWindow pointer into r0.
// The callbacks are lambdas: r0 arrives pointing at the closure, whose first
// field is the captured MainWindow*, and the prologue saves r0 to the stack
// with "str r0, [fp, #-off]". We reload that slot and dereference it.
func (p *Patcher) loadThis(cb uint64) ([]uint32, error) {
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
