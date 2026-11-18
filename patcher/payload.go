package main

import (
	"bytes"
	"fmt"
)

// The payload lives in MainWindow::AcSupportRefresh(), the function that fills
// the stock Support page. That page is no longer reachable once its menu row
// opens Rinkhals, so the function is made to return immediately and the rest
// of its body is ours.
const symSupportRefresh = "_ZN10MainWindow16AcSupportRefreshEv"

var payloadCommands = [][]byte{
	[]byte("/useremain/rinkhals/.current/opt/rinkhals/ui/rinkhals-ui.sh & echo $! > /tmp/rinkhals/rinkhals-ui.pid\x00"),
	[]byte("timeout -t 2 strace -qqq -e trace=none -p $(cat /tmp/rinkhals/rinkhals-ui.pid) 2> /dev/null\x00"),
	[]byte("rm -f /tmp/rinkhals/rinkhals-ui.pid\x00"),
}

// uiAlreadyPatched reports whether AcSupportRefresh already holds our payload.
func (p *Patcher) uiAlreadyPatched() bool {
	addr, _, ok := p.symbol(symSupportRefresh)
	if !ok {
		return false
	}
	first, err := p.read32(addr)
	off, err2 := p.offset(addr + 4)
	if err != nil || err2 != nil || first != movPcLr {
		return false
	}
	return bytes.HasPrefix(p.data[off:], payloadCommands[0])
}

// assembler writes words one after another and keeps the first error.
type assembler struct {
	p    *Patcher
	addr uint64
	end  uint64
	err  error
}

func (a *assembler) word(w uint32) {
	if a.err != nil {
		return
	}
	if a.addr+4 > a.end {
		a.err = fmt.Errorf("payload doesn't fit in AcSupportRefresh")
		return
	}
	a.err = a.p.write32(a.addr, w)
	a.addr += 4
}

func (a *assembler) bl(target uint64)  { a.word(BranchLink(a.addr, target)) }
func (a *assembler) b(target uint64)   { a.word(Branch(a.addr, target)) }
func (a *assembler) beq(target uint64) { a.word(BranchEqual(a.addr, target)) }

// system emits system(str): the string address sits in a literal word that the
// code jumps over.
func (a *assembler) system(str, system uint64) {
	a.word(ldrR0Pc)
	a.b(a.addr + 8)
	a.word(uint32(str))
	a.bl(system)
}

// installPayload writes the payload and points the hook at it. If it returns
// an error, the edits it made so far are dropped.
//
//	system("rinkhals-ui.sh & echo $! > pid")
//	do { OsSleep(100) } while (system("timeout -t 2 strace -p $(cat pid)") == 15)
//	system("rm -f pid")
//	this->AcDisplayWaitHandler(1, 4); this->AcDisplayWaitHide(4)
//	continue after the Support row
//
// strace exits when the UI process does; timeout kills it with SIGTERM (15)
// while the UI is still up, which keeps the loop going.
func (p *Patcher) installPayload(h *hook) (err error) {
	before := len(p.edits)
	defer func() {
		if err != nil {
			p.edits = p.edits[:before]
		}
	}()
	base, size, ok := p.symbol(symSupportRefresh)
	if !ok || size == 0 {
		return fmt.Errorf("AcSupportRefresh not found")
	}
	need := func(name string) (uint64, error) { return p.function(name) }
	system, err := need("system")
	if err != nil {
		return err
	}
	osSleep, err := need("_ZN8GobalVar7OsSleepEi")
	if err != nil {
		return err
	}
	waitHandler, err := need("_ZN10MainWindow20AcDisplayWaitHandlerEhh")
	if err != nil {
		return err
	}
	waitHide, err := need(h.layout.waitHide)
	if err != nil {
		return err
	}

	end := base + size
	if err := p.write32(base, movPcLr); err != nil {
		return err
	}

	// Command strings first, then the code, word-aligned.
	addr := base + 4
	var strs []uint64
	for _, cmd := range payloadCommands {
		if addr+uint64(len(cmd)) > end {
			return fmt.Errorf("payload doesn't fit in AcSupportRefresh")
		}
		if err := p.write(addr, cmd); err != nil {
			return err
		}
		strs = append(strs, addr)
		addr += uint64(len(cmd))
	}
	entry := (addr + 4) &^ 3

	a := &assembler{p: p, addr: entry, end: end}
	a.system(strs[0], system)
	loop := a.addr
	a.word(MovImm(0, 100))
	a.bl(osSleep)
	a.system(strs[1], system)
	a.word(CmpImm(0, 15))
	a.beq(loop)
	a.system(strs[2], system)

	for _, inst := range h.loadThis {
		a.word(inst)
	}
	a.word(MovImm(2, 4))
	a.word(MovImm(1, 1))
	a.bl(waitHandler)

	for _, inst := range h.loadThis {
		a.word(inst)
	}
	a.word(MovImm(1, 4))
	a.bl(waitHide)

	a.b(h.returnTo)
	if a.err != nil {
		return a.err
	}
	return p.write32(h.site, Branch(h.site, entry))
}
