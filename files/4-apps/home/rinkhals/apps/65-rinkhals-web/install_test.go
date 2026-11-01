package main

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// The guard constant has to match the real installer, or the portal silently
// goes back to reporting the relaunching copy's exit status.
func TestUpdateScriptArgsRecognisesTheRealRinkhalsInstaller(t *testing.T) {
	script, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "..", "update.sh"))
	if err != nil {
		t.Fatalf("reading files/update.sh: %v", err)
	}
	if got := updateScriptArgs(script); !reflect.DeepEqual(got, []string{"async"}) {
		t.Fatalf("Rinkhals update.sh: got %v, want [async]", got)
	}
}

func TestUpdateScriptArgsLeavesOtherScriptsAlone(t *testing.T) {
	anycubic := []byte("#!/bin/sh\ncp -f /tmp/app /userdata/app\nexit 0\n")
	if got := updateScriptArgs(anycubic); got != nil {
		t.Fatalf("non-Rinkhals update.sh: got %v, want no arguments", got)
	}
}
