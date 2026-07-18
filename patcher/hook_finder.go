package main

import (
	"fmt"
)

// HookTarget describes where we will inject our jump
type HookTarget struct {
	Address                uint64
	ReturnAddress          uint64
	SetCurrentIndexAddress uint64
	ThisInstructions       []uint32
	IsS1Mode               bool
	S1RowRegister          string
	// CaseBody is set when Address points directly at the row-3 (Service
	// Support) case body of a jump-table dispatch. The row is already selected,
	// so the payload needs no row guard (and no setCurrentIndex re-dispatch).
	CaseBody bool
}

// FindHookTargets generically discovers all valid UI hook injection sites
func (p *Patcher) FindHookTargets() ([]*HookTarget, error) {
	// Candidate callback functions
	candidates := []struct {
		Symbol string
		IsS1   bool
	}{
		{"_ZZN10MainWindow26AcSettingGeneralPageUiInitEvENKUlRK11QModelIndexE0_clES2_", true}, // KS1 General Page
		{"_ZZN10MainWindow21AcSettingDeviceUiInitEvENKUlRK11QModelIndexE0_clES2_", true},      // KS1 Device Page
		{"_ZZN10MainWindow19AcSettingPageUiInitEvENKUlvE_clEv", false},
		{"_ZN10MainWindow23AcSettingListBtnReleaseEi", false}, // K2P
	}

	var results []*HookTarget
	// Jump-table case-body hooks are the correct strategy for modern S1 firmware;
	// when we find one we use ONLY it and ignore any guard-path matches (e.g. a
	// vestigial General-page callback that still exists but no longer hosts the
	// Service Support row). create-patch.py likewise hooks exactly one callback.
	var caseBodyResults []*HookTarget
	// jumpTableDetected records that this is jump-table S1 firmware. On such
	// firmware the guard path mis-fires (the KS1M #53 bug), so if we can't
	// produce a validated case-body hook we refuse to patch rather than falling
	// back to the guard path.
	var jumpTableDetected bool

	displayStatusBar, _, _ := p.FindSymbol("_ZN10MainWindow24BottomStatusBarUiDisplayEh")
	if displayStatusBar == 0 {
		displayStatusBar = p.FindPltSymbol("_ZN10MainWindow24BottomStatusBarUiDisplayEh")
	}
	qStackedWidgetSetCurrentIndex, _, _ := p.FindSymbol("_ZN14QStackedWidget15setCurrentIndexEi")
	if qStackedWidgetSetCurrentIndex == 0 {
		qStackedWidgetSetCurrentIndex = p.FindPltSymbol("_ZN14QStackedWidget15setCurrentIndexEi")
	}

	for _, cand := range candidates {
		addr, fnSize, err := p.FindSymbol(cand.Symbol)
		if err != nil || addr == 0 {
			continue // Symbol not in this firmware
		}

		callbackAddr := addr
		callbackSize := fnSize
		isS1 := cand.IsS1

		offset, err := p.AddrToOffset(callbackAddr)
		if err != nil {
			continue
		}

		s := NewScanner(p.fileData)

		// Newer S1 firmware (KS1 2.7.0.7+, all KS1M 2.6.6+) dispatches the tapped
		// row through a jump table. Prefer hooking the row-3 (Service Support)
		// case body directly - no row guard - which is the correct strategy for
		// these builds (the guard/bl-scan path below mis-fires on them, the KS1M
		// #53 bug). Only falls through to the guard path if no jump table exists.
		//
		// Gated + validated: only when the "Service Support" string was actually
		// relabeled (there is a row to repurpose) AND the case at the assumed row
		// is a legitimate short setCurrentIndex nav case. The row index isn't
		// derivable from the string, so this fails safe on an unexpected layout.
		if isS1 {
			if caseAddr, retAddr, ok := p.findJumpTableCaseBody(callbackAddr, callbackSize, 3); ok {
				// This IS jump-table firmware. Hook only via the case body; never
				// fall through to the guard path for it (that mis-fires). Emit the
				// hook only when gated (Service Support was relabeled) AND the case
				// shape validates; otherwise skip safely.
				jumpTableDetected = true
				if p.serviceSupportRelabeled && p.isSettingsNavCase(caseAddr, qStackedWidgetSetCurrentIndex, 16) {
					if this := p.thisFromStackStore(offset); len(this) > 0 {
						caseBodyResults = append(caseBodyResults, &HookTarget{
							Address:          caseAddr,
							ReturnAddress:    retAddr,
							ThisInstructions: this,
							IsS1Mode:         true,
							CaseBody:         true,
						})
					}
				}
				continue
			}
		}

		var patchJumpAddress uint64
		var patchReturnAddress uint64
		var thisInstructions []uint32

		var foundBl uint64
		var foundBls []uint64

		maxScan := offset + callbackSize

		for cur := offset; cur < maxScan; cur += 4 {
			inst := s.ReadInstruction(cur)
			vma := callbackAddr + (cur - offset)

			if displayStatusBar != 0 && inst == BranchLink(vma, displayStatusBar) {
				foundBls = append(foundBls, cur)
			}
			// Some models jump right to setCurrentIndex if displayStatusBar isn't used
			if qStackedWidgetSetCurrentIndex != 0 && inst == BranchLink(vma, qStackedWidgetSetCurrentIndex) {
				foundBls = append(foundBls, cur)
			}
		}

		if len(foundBls) > 0 {
			if isS1 {
				foundBl = foundBls[len(foundBls)-1]
			} else {
				foundBl = foundBls[0]
			}
		}

		if foundBl != 0 {
			patchJumpAddress = callbackAddr + (foundBl - offset)
			patchReturnAddress = patchJumpAddress + 4

			// 1. Try to find the 'this' pointer stored on the stack first
			strInstructionOffset := p.FindStrR0Fp(offset, 20)
			if strInstructionOffset != 0 {
				strInstruction := s.ReadInstruction(strInstructionOffset)
				thisOffset := strInstruction & 0xFFF
				thisInstructions = []uint32{
					0xE51B0000 | thisOffset, // ldr r0, [fp, #-offset]
					0xE5900000,              // ldr r0, [r0]
				}
			}

			// 2. Fall back to finding 'mov r0, r4' (or r5/r6) where 'this' is parked.
			if len(thisInstructions) == 0 {
				searchBl := foundBls[0] // Typically look before the FIRST bl (usually displayStatusBar)
				for i := 1; i <= 10; i++ {
					prevAddr := searchBl - uint64(i*4)
					inst := s.ReadInstruction(prevAddr)

					// If it's mov r0, rx
					if (inst & 0xFFFFFF00) == 0xE1A00000 {
						thisInstructions = append(thisInstructions, inst)
						break
					}
					// If it's ldr r0, [...]
					if (inst&0xFFF00000) == 0xE5900000 || (inst&0xFFF00000) == 0xE5100000 {
						thisInstructions = append(thisInstructions, inst)
						break
					}
				}
			}

			if len(thisInstructions) > 0 {
				// Derive which register holds the row() result for the guard's
				// "cmp <reg>, #3". It varies per firmware (r3 on the General
				// page, r1 on early Device-page builds); hardcoding was wrong for
				// the General-page ones. Fall back to r1 if it can't be derived.
				s1RowRegister := "r1"
				if isS1 {
					if reg, ok := p.deriveRowRegister(callbackAddr, callbackSize); ok {
						s1RowRegister = reg
					}
				}

				results = append(results, &HookTarget{
					Address:                patchJumpAddress,
					SetCurrentIndexAddress: qStackedWidgetSetCurrentIndex,
					ReturnAddress:          patchReturnAddress,
					ThisInstructions:       thisInstructions,
					IsS1Mode:               isS1,
					S1RowRegister:          s1RowRegister,
				})
			}
		}
	}

	// A jump-table case-body hook, when present, is the authoritative one.
	if len(caseBodyResults) > 0 {
		return caseBodyResults, nil
	}

	// Jump-table firmware, but no validated case-body hook (missing Service
	// Support string or an unexpected case shape). Fail safe: refuse to patch
	// rather than using the guard path, which mis-fires on jump-table layouts.
	if jumpTableDetected {
		return nil, fmt.Errorf("jump-table S1 firmware but no validated case-body hook (gate/shape check failed); refusing to patch")
	}

	if len(results) == 0 {
		return nil, fmt.Errorf("could not find any valid hook targets in the UI button callbacks")
	}

	return results, nil
}

// deriveRowRegister finds which register the guard must compare against #3 - the
// one holding QModelIndex::row()'s result. The compiler emits
// "bl QModelIndex::row; mov rX, r0", so we locate the row() call and read the
// destination of the following mov. This replaces the hardcoded r1, which was
// only correct for early Device-page builds (the General page uses r3).
func (p *Patcher) deriveRowRegister(callbackAddr, callbackSize uint64) (string, bool) {
	row, _, _ := p.FindSymbol("_ZNK11QModelIndex3rowEv")
	if row == 0 {
		row = p.FindPltSymbol("_ZNK11QModelIndex3rowEv")
	}
	if row == 0 {
		return "", false
	}
	s := NewScanner(p.fileData)
	base, err := p.AddrToOffset(callbackAddr)
	if err != nil {
		return "", false
	}
	for cur := base; cur+4 <= base+callbackSize; cur += 4 {
		vma := callbackAddr + (cur - base)
		if s.ReadInstruction(cur) != BranchLink(vma, row) {
			continue
		}
		// row() returns in r0; the next 1-2 instructions stash it with
		// "mov rX, r0" (Rm=0, no shift -> 0xE1A0_X000).
		for k := uint64(1); k <= 2; k++ {
			next := s.ReadInstruction(cur + k*4)
			if (next & 0xFFFF0FFF) == 0xE1A00000 {
				return fmt.Sprintf("r%d", (next>>12)&0xF), true
			}
		}
		return "", false
	}
	return "", false
}

// FindStrR0Fp searches for "str r0, [fp, #-xx]"
func (p *Patcher) FindStrR0Fp(start uint64, maxInst int) uint64 {
	s := NewScanner(p.fileData)
	for cur := start; cur < start+uint64(maxInst*4); cur += 4 {
		inst := s.ReadInstruction(cur)
		if (inst & 0xFFFFF000) == 0xE50B0000 {
			return cur
		}
	}
	return 0
}

func (p *Patcher) FindPltSymbol(name string) uint64 {
	syms, err := p.elfFile.DynamicSymbols()
	if err != nil {
		return 0
	}
	var symIdx int = -1
	for i, s := range syms {
		if s.Name == name {
			symIdx = i + 1
			break
		}
	}
	if symIdx == -1 {
		return 0
	}

	plt := p.elfFile.Section(".plt")
	if plt == nil {
		return 0
	}

	relPlt := p.elfFile.Section(".rel.plt")
	if relPlt != nil {
		data, _ := relPlt.Data()
		for i := 0; i < len(data); i += 8 {
			info := uint32(data[i+4]) | uint32(data[i+5])<<8 | uint32(data[i+6])<<16 | uint32(data[i+7])<<24
			idx := int(info >> 8)
			if idx == symIdx {
				return plt.Addr + 20 + uint64(i/8)*12
			}
		}
	}
	return 0
}
