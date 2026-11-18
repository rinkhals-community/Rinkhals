package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"log"
)

// PatchGkapi moves gkapi's orcaSim server (an OctoPrint-compatible API for
// slicers) off port 80, which Rinkhals needs for Mainsail or Fluidd.
//
// orcaSim.Start listens on the Go string ":80". Its literal pool holds that
// string's address right before the address of "localhost:7125" (the upstream
// it proxies to). We repoint the ":80" literal 9 bytes into "localhost:7125",
// at ":71": same length, so only the pointer changes.
func (p *Patcher) PatchGkapi() error {
	start, end, err := p.goFunction("printerApi/service/orcaSim.Start")
	if err != nil {
		return err
	}

	idx := bytes.Index(p.data, []byte("localhost:7125"))
	if idx < 0 {
		return fmt.Errorf("\"localhost:7125\" not found")
	}
	upstream, err := p.address(uint64(idx))
	if err != nil {
		return err
	}

	// Find the "localhost:7125" literal in the first 200 words of orcaSim.Start.
	for i := uint64(1); i < 200 && start+i*4 < end; i++ {
		word, err := p.read32(start + i*4)
		if err != nil {
			return err
		}
		if uint64(word) != upstream {
			continue
		}
		portAddr := start + i*4 - 4
		port, err := p.read32(portAddr)
		if err != nil {
			return err
		}
		if uint64(port) == upstream+9 {
			return errAlreadyPatched
		}
		if s := p.cString(uint64(port), 3); s != ":80" {
			return fmt.Errorf("expected the \":80\" literal before \"localhost:7125\", found %q", s)
		}
		log.Printf("orcaSim.Start+0x%x: \":80\" -> \":71\"", portAddr-start)
		return p.write32(portAddr, uint32(upstream+9))
	}
	return fmt.Errorf("orcaSim.Start doesn't reference \"localhost:7125\"")
}

// goFunction finds a function in a Go binary's .gopclntab and returns where it
// starts and ends. The table is walked in place; debug/gosym would build an
// index of every function in memory, which the printers can't spare.
//
// Layout (Go 1.18 and later, 32-bit): a header of magic, 2 pad bytes, the
// instruction size quantum, the pointer size, then six words: function count,
// file count, text start, and the offsets of the name table, compilation
// units, file table, pc table and function table. The function table is
// (entry offset, _func offset) pairs, and a _func starts with its entry offset
// and the offset of its name.
func (p *Patcher) goFunction(name string) (start, end uint64, err error) {
	sec := p.f.Section(".gopclntab")
	if sec == nil {
		return 0, 0, fmt.Errorf("not a Go binary")
	}
	tab := p.data[sec.Offset : sec.Offset+sec.Size]
	le := binary.LittleEndian
	if len(tab) < 40 || (le.Uint32(tab) != 0xFFFFFFF0 && le.Uint32(tab) != 0xFFFFFFF1) || tab[7] != 4 {
		return 0, 0, fmt.Errorf("unknown Go function table format")
	}
	count := uint64(le.Uint32(tab[8:]))
	text := uint64(le.Uint32(tab[16:]))
	names := uint64(le.Uint32(tab[20:]))
	funcs := uint64(le.Uint32(tab[36:]))
	size := uint64(len(tab))
	if names >= size || funcs+(count+1)*8 > size {
		return 0, 0, fmt.Errorf("corrupt Go function table")
	}
	for i := uint64(0); i < count; i++ {
		entry := funcs + i*8
		fn := funcs + uint64(le.Uint32(tab[entry+4:]))
		if fn+8 > size {
			return 0, 0, fmt.Errorf("corrupt Go function table")
		}
		n := names + uint64(le.Uint32(tab[fn+4:]))
		if n+uint64(len(name)) >= size || tab[n+uint64(len(name))] != 0 || string(tab[n:n+uint64(len(name))]) != name {
			continue
		}
		return text + uint64(le.Uint32(tab[entry:])), text + uint64(le.Uint32(tab[entry+8:])), nil
	}
	return 0, 0, fmt.Errorf("no orcaSim server in this gkapi")
}
