package main

import (
	"bytes"
	"debug/elf"
	"encoding/binary"
	"fmt"
)

// Patcher analyses one ELF binary and collects the changes to make to it.
//
// The printers have little free memory (the kernel killed an early version of
// this program for holding a whole binary and its symbol table in memory), so
// data is expected to be a read-only file mapping: nothing is copied, symbols
// are looked up straight from the mapped tables, and patches are kept as a
// short list of edits that main applies to a copy of the file.
type Patcher struct {
	data  []byte
	f     *elf.File
	edits []edit
	syms  map[string]symbol
}

type edit struct {
	off  uint64
	data []byte
}

type symbol struct {
	addr, size uint64
	index      int
	ok         bool
}

func NewPatcher(data []byte) (*Patcher, error) {
	f, err := elf.NewFile(bytes.NewReader(data))
	if err != nil {
		return nil, fmt.Errorf("parse ELF: %w", err)
	}
	if f.Machine != elf.EM_ARM || f.Class != elf.ELFCLASS32 || f.ByteOrder != binary.LittleEndian {
		return nil, fmt.Errorf("not a 32-bit little-endian ARM binary")
	}
	// A truncated file can keep valid headers. Make sure everything the headers
	// describe is really there, so we never patch a partial binary.
	for _, s := range f.Sections {
		if s.Type != elf.SHT_NOBITS && s.Offset+s.Size > uint64(len(data)) {
			return nil, fmt.Errorf("section %s runs past the end of the file (truncated binary?)", s.Name)
		}
	}
	for _, prog := range f.Progs {
		if prog.Off+prog.Filesz > uint64(len(data)) {
			return nil, fmt.Errorf("a program segment runs past the end of the file (truncated binary?)")
		}
	}
	return &Patcher{data: data, f: f, syms: map[string]symbol{}}, nil
}

// lookup scans a symbol table section for name, without loading the table.
func (p *Patcher) lookup(table string, name string) symbol {
	key := table + "/" + name
	if s, ok := p.syms[key]; ok {
		return s
	}
	var found symbol
	if tab := p.f.Section(table); tab != nil && int(tab.Link) < len(p.f.Sections) {
		str := p.f.Sections[tab.Link]
		syms := p.data[tab.Offset : tab.Offset+tab.Size]
		strs := p.data[str.Offset : str.Offset+str.Size]
		// Elf32_Sym: name(4) value(4) size(4) info(1) other(1) shndx(2)
		for i := 0; i+16 <= len(syms); i += 16 {
			n := int(binary.LittleEndian.Uint32(syms[i:]))
			if n+len(name) >= len(strs) || strs[n+len(name)] != 0 || string(strs[n:n+len(name)]) != name {
				continue
			}
			found = symbol{
				addr:  uint64(binary.LittleEndian.Uint32(syms[i+4:])),
				size:  uint64(binary.LittleEndian.Uint32(syms[i+8:])),
				index: i / 16,
				ok:    true,
			}
			break
		}
	}
	p.syms[key] = found
	return found
}

// symbol returns the address and size of a function defined in the binary.
func (p *Patcher) symbol(name string) (addr, size uint64, ok bool) {
	s := p.lookup(".symtab", name)
	return s.addr, s.size, s.ok && s.addr != 0
}

// function returns the address to call for name: the function itself when the
// binary defines it, otherwise its PLT stub.
func (p *Patcher) function(name string) (uint64, error) {
	if addr, _, ok := p.symbol(name); ok {
		return addr, nil
	}
	return p.pltStub(name)
}

// pltStub finds the PLT entry that jumps to an imported function. The entry is
// located by position (20-byte header, 12 bytes per entry, in .rel.plt order)
// and then proven: its three instructions are decoded and must load the GOT
// slot that the function's relocation fills in.
func (p *Patcher) pltStub(name string) (uint64, error) {
	dyn := p.lookup(".dynsym", name)
	plt, rel := p.f.Section(".plt"), p.f.Section(".rel.plt")
	if !dyn.ok || plt == nil || rel == nil {
		return 0, fmt.Errorf("%s: not imported by this binary", name)
	}
	symIdx := dyn.index
	relData := p.data[rel.Offset : rel.Offset+rel.Size]
	for i := 0; i+8 <= len(relData); i += 8 {
		gotSlot := uint64(binary.LittleEndian.Uint32(relData[i:]))
		info := binary.LittleEndian.Uint32(relData[i+4:])
		if int(info>>8) != symIdx {
			continue
		}
		stub := plt.Addr + 20 + uint64(i/8)*12
		if stub+12 > plt.Addr+plt.Size {
			return 0, fmt.Errorf("%s: PLT entry outside .plt", name)
		}
		// add ip, pc, #a ; add ip, ip, #b ; ldr pc, [ip, #c]!
		i0, e0 := p.read32(stub)
		i1, e1 := p.read32(stub + 4)
		i2, e2 := p.read32(stub + 8)
		if e0 != nil || e1 != nil || e2 != nil ||
			i0&0xFFFFF000 != 0xE28FC000 || i1&0xFFFFF000 != 0xE28CC000 || i2&0xFFFFF000 != 0xE5BCF000 {
			return 0, fmt.Errorf("%s: unexpected PLT entry layout at 0x%x", name, stub)
		}
		if got := stub + 8 + uint64(decodeImm(i0)) + uint64(decodeImm(i1)) + uint64(i2&0xFFF); got != gotSlot {
			return 0, fmt.Errorf("%s: PLT entry at 0x%x loads 0x%x, expected GOT slot 0x%x", name, stub, got, gotSlot)
		}
		return stub, nil
	}
	return 0, fmt.Errorf("%s: no PLT relocation", name)
}

// offset converts a virtual address to a file offset.
func (p *Patcher) offset(vma uint64) (uint64, error) {
	for _, prog := range p.f.Progs {
		if prog.Type == elf.PT_LOAD && vma >= prog.Vaddr && vma < prog.Vaddr+prog.Filesz {
			return prog.Off + (vma - prog.Vaddr), nil
		}
	}
	return 0, fmt.Errorf("address 0x%x is not in the file", vma)
}

// address converts a file offset to a virtual address.
func (p *Patcher) address(off uint64) (uint64, error) {
	for _, prog := range p.f.Progs {
		if prog.Type == elf.PT_LOAD && off >= prog.Off && off < prog.Off+prog.Filesz {
			return prog.Vaddr + (off - prog.Off), nil
		}
	}
	return 0, fmt.Errorf("file offset 0x%x is not loaded", off)
}

func (p *Patcher) read32(vma uint64) (uint32, error) {
	off, err := p.offset(vma)
	if err != nil {
		return 0, err
	}
	if off+4 > uint64(len(p.data)) {
		return 0, fmt.Errorf("address 0x%x is past the end of the file", vma)
	}
	return binary.LittleEndian.Uint32(p.data[off:]), nil
}

func (p *Patcher) write32(vma uint64, val uint32) error {
	return p.write(vma, binary.LittleEndian.AppendUint32(nil, val))
}

// write records a change at a virtual address. The mapped file is not
// touched, so reads keep returning the original bytes.
func (p *Patcher) write(vma uint64, b []byte) error {
	off, err := p.offset(vma)
	if err != nil {
		return err
	}
	return p.writeAt(off, b)
}

func (p *Patcher) writeAt(off uint64, b []byte) error {
	if off+uint64(len(b)) > uint64(len(p.data)) {
		return fmt.Errorf("write at offset 0x%x runs past the end of the file", off)
	}
	p.edits = append(p.edits, edit{off, append([]byte(nil), b...)})
	return nil
}

// overlay copies the patched contents of [off, off+len(buf)) into buf.
func (p *Patcher) overlay(off uint64, buf []byte) {
	copy(buf, p.data[off:])
	end := off + uint64(len(buf))
	for _, e := range p.edits {
		eEnd := e.off + uint64(len(e.data))
		if eEnd <= off || e.off >= end {
			continue
		}
		from, to := max(off, e.off), min(end, eEnd)
		copy(buf[from-off:to-off], e.data[from-e.off:to-e.off])
	}
}

// cString returns the NUL-terminated string at vma, up to max bytes.
func (p *Patcher) cString(vma uint64, max int) string {
	off, err := p.offset(vma)
	if err != nil {
		return ""
	}
	end := off
	for end < uint64(len(p.data)) && end-off < uint64(max) && p.data[end] != 0 {
		end++
	}
	return string(p.data[off:end])
}
