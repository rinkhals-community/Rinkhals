package main

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestDependentsOf(t *testing.T) {
	depends := map[string][]string{
		"helixscreen":     {"vanilla-klipper"},
		"other-screen":    {"40-moonraker", "vanilla-klipper"},
		"vanilla-klipper": {"40-moonraker"},
		"self":            {"self"},
	}
	cases := map[string][]string{
		"vanilla-klipper": {"helixscreen", "other-screen"},
		"40-moonraker":    {"other-screen", "vanilla-klipper"},
		"helixscreen":     nil,
		"self":            nil, // an app naming itself doesn't block its own removal
		"unknown":         nil,
	}
	for target, want := range cases {
		if got := dependentsOf(target, depends); !reflect.DeepEqual(got, want) {
			t.Errorf("dependentsOf(%q) = %v, want %v", target, got, want)
		}
	}
}

func TestMissingFrom(t *testing.T) {
	have := func(id string) bool { return id == "40-moonraker" }
	if got := missingFrom([]string{"40-moonraker", "vanilla-klipper"}, have); !reflect.DeepEqual(got, []string{"vanilla-klipper"}) {
		t.Errorf("missingFrom = %v", got)
	}
	if got := missingFrom(nil, have); got != nil {
		t.Errorf("missingFrom(nil) = %v, want nothing", got)
	}
}

func TestBlockedMessagesNameTheApps(t *testing.T) {
	// Nothing is installed in the test environment, so every dependency is missing.
	msg := installBlockedBy("helixscreen", []string{"vanilla-klipper"})
	if msg == "" {
		t.Fatal("an app with a missing dependency must not be installable")
	}
	for _, word := range []string{"helixscreen", "vanilla-klipper"} {
		if !contains(msg, word) {
			t.Errorf("message %q doesn't mention %q", msg, word)
		}
	}
	if msg := installBlockedBy("plain", nil); msg != "" {
		t.Errorf("an app without dependencies was blocked: %q", msg)
	}
	if msg := uninstallBlockedBy("vanilla-klipper"); msg != "" {
		t.Errorf("uninstall blocked with nothing installed: %q", msg)
	}
}

func contains(s, sub string) bool {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}

func TestReadManifestToleratesCommentLines(t *testing.T) {
	dir := t.TempDir()
	manifest := "{\n    // what this app needs\n    \"name\": \"Screen\",\n    \"depends\": [ \"vanilla-klipper\" ]\n}\n"
	if err := os.WriteFile(filepath.Join(dir, "app.json"), []byte(manifest), 0o644); err != nil {
		t.Fatal(err)
	}
	m, err := readManifest(dir)
	if err != nil {
		t.Fatalf("manifest with a comment line was rejected: %v", err)
	}
	if m.Name != "Screen" || !reflect.DeepEqual(m.Depends, []string{"vanilla-klipper"}) {
		t.Errorf("read %+v", m)
	}
}
