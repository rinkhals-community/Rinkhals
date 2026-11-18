// rinkhals-patcher patches Anycubic's K3SysUi and gkapi on the printer, for
// firmware Rinkhals doesn't ship a static patch for. It does what
// create-patch.py does at build time, but finds the patch locations itself.
//
// It never modifies its input. The patched copy is written to --output only
// when every check passes; on any doubt it exits non-zero and writes nothing.
//
// Exit status: 0 patched (or, with --check, patchable), 2 already patched,
// 1 anything else.
package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"syscall"
)

func main() {
	binary := flag.String("binary", "", "K3SysUi or gkapi binary to patch")
	output := flag.String("output", "", "where to write the patched copy (default: <binary>.patched)")
	check := flag.Bool("check", false, "only report whether the binary is an unpatched one we can patch")
	flag.Parse()
	log.SetFlags(0)

	if *binary == "" {
		log.Fatal("--binary is required")
	}
	if *output == "" {
		*output = *binary + ".patched"
	}

	p, unmap, err := open(*binary)
	if err == nil {
		defer unmap()
		// gkapi is a Go program, K3SysUi a C++ one.
		if p.f.Section(".gopclntab") != nil {
			err = p.PatchGkapi()
		} else {
			err = p.PatchUI()
		}
	}
	switch {
	case errors.Is(err, errAlreadyPatched):
		log.Printf("%s is already patched", *binary)
		os.Exit(2)
	case err != nil:
		log.Printf("%s: not patched: %v", *binary, err)
		os.Exit(1)
	case *check:
		return
	}

	if err := p.writeFile(*output); err != nil {
		log.Printf("%s: %v", *output, err)
		os.Exit(1)
	}
	log.Printf("wrote %s", *output)
}

// open maps the binary at path read-only.
func open(path string) (*Patcher, func(), error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, nil, err
	}
	if info.Size() == 0 {
		return nil, nil, fmt.Errorf("empty file")
	}
	data, err := syscall.Mmap(int(f.Fd()), 0, int(info.Size()), syscall.PROT_READ, syscall.MAP_PRIVATE)
	if err != nil {
		return nil, nil, err
	}
	p, err := NewPatcher(data)
	if err != nil {
		syscall.Munmap(data)
		return nil, nil, err
	}
	return p, func() { syscall.Munmap(data) }, nil
}

const chunk = 256 << 10

// writeFile writes the patched binary so that path either doesn't exist or is
// complete, even across a power cut: write a temporary file, flush it, read it
// back, rename. It works a chunk at a time to stay small in memory.
func (p *Patcher) writeFile(path string) error {
	tmp := path + ".part"
	defer os.Remove(tmp)

	f, err := os.OpenFile(tmp, os.O_RDWR|os.O_CREATE|os.O_TRUNC, 0o755)
	if err != nil {
		return err
	}
	defer f.Close()

	want, got := make([]byte, chunk), make([]byte, chunk)
	size := uint64(len(p.data))
	for off := uint64(0); off < size; off += chunk {
		n := min(chunk, size-off)
		p.overlay(off, want[:n])
		if _, err := f.Write(want[:n]); err != nil {
			return err
		}
	}
	if err := f.Sync(); err != nil {
		return err
	}
	for off := uint64(0); off < size; off += chunk {
		n := min(chunk, size-off)
		p.overlay(off, want[:n])
		if _, err := io.ReadFull(io.NewSectionReader(f, int64(off), int64(n)), got[:n]); err != nil {
			return err
		}
		if !bytes.Equal(want[:n], got[:n]) {
			return fmt.Errorf("read back different data than was written")
		}
	}
	if err := f.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		return err
	}
	if dir, err := os.Open(filepath.Dir(path)); err == nil {
		dir.Sync()
		dir.Close()
	}
	return nil
}
