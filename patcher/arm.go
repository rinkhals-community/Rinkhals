package main

// ARM32 (A32, little-endian) instruction encoders and decoders. Only what the
// patcher needs; every encoding here is checked against the static patches by
// validate.sh.

const (
	condEQ = 0x0
	condAL = 0xE
)

func branchWord(cond, link uint32, from, to uint64) uint32 {
	// The PC reads as the instruction address + 8, and the offset is stored >> 2.
	offset := int32(to) - int32(from) - 8
	return cond<<28 | 0x0A000000 | link<<24 | uint32(offset>>2)&0x00FFFFFF
}

// Branch encodes "b to" placed at from.
func Branch(from, to uint64) uint32 { return branchWord(condAL, 0, from, to) }

// BranchLink encodes "bl to" placed at from.
func BranchLink(from, to uint64) uint32 { return branchWord(condAL, 1, from, to) }

// BranchEqual encodes "beq to" placed at from.
func BranchEqual(from, to uint64) uint32 { return branchWord(condEQ, 0, from, to) }

// MovImm encodes "mov rd, #imm" for an 8-bit immediate.
func MovImm(rd, imm uint32) uint32 { return 0xE3A00000 | rd<<12 | imm&0xFF }

// CmpImm encodes "cmp rn, #imm" for an 8-bit immediate.
func CmpImm(rn, imm uint32) uint32 { return 0xE3500000 | rn<<16 | imm&0xFF }

const (
	movPcLr   = 0xE1A0F00E // mov pc, lr
	ldrR0Pc   = 0xE59F0000 // ldr r0, [pc]
	ldrR0R0   = 0xE5900000 // ldr r0, [r0]
	ldrR0Fp   = 0xE51B0000 // ldr r0, [fp, #-imm12]
	strR0Fp   = 0xE50B0000 // str r0, [fp, #-imm12]
	maskImm12 = 0xFFFFF000
)

// isBranch reports whether inst is B (not BL) with any condition.
func isBranch(inst uint32) bool { return inst&0x0F000000 == 0x0A000000 }

// isBranchAL reports whether inst is an unconditional B.
func isBranchAL(inst uint32) bool { return inst&0xFF000000 == 0xEA000000 }

// isBranchLinkAL reports whether inst is an unconditional BL.
func isBranchLinkAL(inst uint32) bool { return inst&0xFF000000 == 0xEB000000 }

// branchTarget decodes the destination of a B/BL at addr.
func branchTarget(inst uint32, addr uint64) uint64 {
	imm := int64(inst & 0x00FFFFFF)
	if imm&0x00800000 != 0 {
		imm -= 0x01000000
	}
	return uint64(int64(addr) + 8 + imm*4)
}

// writesPC reports whether a data-processing or load instruction has pc as its
// destination, i.e. it is some other kind of jump we don't model.
func writesPC(inst uint32) bool {
	if inst&0x0C000000 == 0x00000000 || inst&0x0C100000 == 0x04100000 { // data processing / ldr
		return (inst>>12)&0xF == 0xF
	}
	return false
}

// decodeImm decodes an ARM "modified immediate" (8 bits rotated right by 2*rot).
func decodeImm(inst uint32) uint32 {
	imm8 := inst & 0xFF
	rot := ((inst >> 8) & 0xF) * 2
	return imm8>>rot | imm8<<(32-rot)
}
