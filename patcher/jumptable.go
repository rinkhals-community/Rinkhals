package main

// Jump-table / switch dispatch analysis for the newer S1 (KS1/KS1M) firmware.
//
// On KS1 2.7.0.7+ and all KS1M 2.6.6+, the Device-settings row callback does not
// run the tapped row through a linear "if (row()==3)" check. Instead the compiler
// emits an ARM switch dispatch:
//
//     cmp   rX, #N                  ; N = highest case index
//     addls pc, pc, rX, lsl #2      ; if rX <= N: PC = (here+8) + rX*4
//     b     default                 ; rX > N
//     b     case0
//     b     case1
//     ...
//     b     caseN
//
// Rinkhals repurposes the "Service Support" row, which is row 3 on these builds
// (row0 Printer Info, row1 ACE Info, row2 CN Code, row3 Service Support,
// row4 Export logs). Because each case body only runs for its own row, we hook
// the row-3 case body DIRECTLY and need no row guard - this is create-patch.py's
// s1CaseAlreadySelected mode, and it is what fixes the KS1M "white squares" bug
// (discussion #53) where a row()==3 guard against the wrong register never
// matched and Rinkhals never launched.

// DecodeBranchTarget decodes an ARM B/BEQ/... branch (opcode bits 27..24 == 0xA,
// any condition) at instAddr and returns its absolute target. ok is false if the
// instruction is not a plain branch (BL has bit 24 set, opcode 0xB).
func DecodeBranchTarget(inst uint32, instAddr uint64) (target uint64, ok bool) {
	if (inst & 0x0F000000) != 0x0A000000 {
		return 0, false
	}
	imm24 := int64(inst & 0x00FFFFFF)
	if imm24&0x00800000 != 0 { // sign-extend 24-bit
		imm24 |= ^int64(0x00FFFFFF)
	}
	// ARM PC reads as instruction address + 8, and the offset is <<2.
	return uint64(int64(instAddr) + 8 + imm24*4), true
}

// findJumpTableCaseBody scans a callback for the switch dispatch above and, for
// the given case index, returns the address of that case body (hook site) and
// the address the case body branches to when it finishes (the shared switch
// epilogue = our return site). ok is false if no such dispatch is found.
func (p *Patcher) findJumpTableCaseBody(callbackAddr, callbackSize uint64, caseIndex uint64) (hookAddr, returnAddr uint64, ok bool) {
	s := NewScanner(p.fileData)
	base, err := p.AddrToOffset(callbackAddr)
	if err != nil {
		return 0, 0, false
	}
	end := base + callbackSize

	for cur := base + 4; cur+4 <= end; cur += 4 {
		inst := s.ReadInstruction(cur)

		// Match "add pc, pc, rX, lsl #2" (any condition). Encoding with cond and
		// Rm masked out is 0x008FF100 (Rd=Rn=pc, shifter = <Rm> lsl #2).
		if (inst & 0x0FFFFFF0) != 0x008FF100 {
			continue
		}
		rm := uint64(inst & 0xF)

		// Sanity: the preceding instruction must be "cmp rX, #imm" on the same
		// register, with imm >= caseIndex (so our case index is in range). This
		// avoids matching an unrelated "add pc, pc, ..." computed jump.
		prev := s.ReadInstruction(cur - 4)
		if (prev&0x0FF0F000) != 0x03500000 || uint64((prev>>16)&0xF) != rm || uint64(prev&0xFF) < caseIndex {
			continue
		}

		dispatchVMA := callbackAddr + (cur - base)

		// Table of branch instructions starts at dispatchVMA + 8 (ARM PC). The
		// slot at +4 is the default (rX > N); case i is at +8 + i*4.
		entryVMA := dispatchVMA + 8 + caseIndex*4
		entryOff, err := p.AddrToOffset(entryVMA)
		if err != nil {
			continue
		}
		caseAddr, isBranch := DecodeBranchTarget(s.ReadInstruction(entryOff), entryVMA)
		if !isBranch {
			continue
		}

		ret, ok2 := p.findCaseExit(caseAddr, 64)
		if !ok2 {
			continue
		}
		return caseAddr, ret, true
	}
	return 0, 0, false
}

// thisFromStackStore derives the instructions that reload the lambda's captured
// "this" (a MainWindow*) for use in the payload's AcDisplayWait* calls. The
// callback stores its closure arg with "str r0, [fp, #-off]" in its prologue;
// the closure's first word is the captured this, so we reload the slot and
// dereference. Returns nil if the store isn't found.
func (p *Patcher) thisFromStackStore(callbackOffset uint64) []uint32 {
	strOff := p.FindStrR0Fp(callbackOffset, 20)
	if strOff == 0 {
		return nil
	}
	s := NewScanner(p.fileData)
	thisOffset := s.ReadInstruction(strOff) & 0xFFF
	return []uint32{
		0xE51B0000 | thisOffset, // ldr r0, [fp, #-thisOffset]
		0xE5900000,              // ldr r0, [r0]
	}
}

// isSettingsNavCase validates that a jump-table case body is a legitimate
// settings page-nav case: a SHORT body that calls QStackedWidget::setCurrentIndex
// before branching to the switch epilogue. The row index (3) is not derivable
// from the "Service Support" string (it isn't referenced by any locatable code -
// the labels come from Qt translation/resources), so this shape check is our
// fail-safe: if the case at the assumed row isn't a nav case (an unexpected menu
// layout), we refuse to hook it rather than corrupting the binary.
func (p *Patcher) isSettingsNavCase(caseAddr, setCurrentIndex uint64, maxInst int) bool {
	if setCurrentIndex == 0 {
		return false // can't confirm a page switch without the symbol
	}
	s := NewScanner(p.fileData)
	off, err := p.AddrToOffset(caseAddr)
	if err != nil {
		return false
	}
	sawNav := false
	for i := 0; i < maxInst; i++ {
		cur := off + uint64(i*4)
		vma := caseAddr + uint64(i*4)
		inst := s.ReadInstruction(cur)
		if inst == BranchLink(vma, setCurrentIndex) {
			sawNav = true
		}
		// First unconditional B ends the case. Require the nav call to have
		// appeared before it, and the whole case to fit in the window.
		if (inst & 0xFF000000) == 0xEA000000 {
			return sawNav
		}
	}
	return false // no short exit found -> not a simple nav case
}

// findCaseExit disassembles forward from a switch case body and returns the
// target of the first unconditional branch (B, condition AL) - the point where
// the case rejoins the shared switch epilogue. This is where our payload returns
// to so the normal cleanup runs.
func (p *Patcher) findCaseExit(caseAddr uint64, maxInst int) (uint64, bool) {
	s := NewScanner(p.fileData)
	off, err := p.AddrToOffset(caseAddr)
	if err != nil {
		return 0, false
	}
	for i := 0; i < maxInst; i++ {
		cur := off + uint64(i*4)
		inst := s.ReadInstruction(cur)
		if (inst & 0xFF000000) == 0xEA000000 { // unconditional B (cond AL)
			return DecodeBranchTarget(inst, caseAddr+uint64(i*4))
		}
	}
	return 0, false
}
