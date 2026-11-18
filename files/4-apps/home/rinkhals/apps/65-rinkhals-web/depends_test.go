package main

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestDependentsOf(t *testing.T) {
	depends := map[string][]string{
		"helixscreen":     {"vanilla-klipper|tunneled-klipper"},
		"other-screen":    {"40-moonraker", "vanilla-klipper"},
		"vanilla-klipper": {"40-moonraker"},
		"self":            {"self"},
	}
	all := func(string) bool { return true }
	onlyVanilla := func(id string) bool { return id == "vanilla-klipper" || id == "40-moonraker" }

	cases := []struct {
		target string
		have   func(string) bool
		want   []string
	}{
		// With tunneled-klipper around, helixscreen can do without vanilla-klipper.
		{"vanilla-klipper", all, []string{"other-screen"}},
		// Without it, vanilla-klipper is helixscreen's last alternative.
		{"vanilla-klipper", onlyVanilla, []string{"helixscreen", "other-screen"}},
		{"tunneled-klipper", all, nil},
		{"40-moonraker", all, []string{"other-screen", "vanilla-klipper"}},
		{"helixscreen", all, nil},
		{"self", all, nil}, // an app naming itself doesn't block its own removal
		{"unknown", all, nil},
	}
	for _, c := range cases {
		if got := dependentsOf(c.target, depends, c.have); !reflect.DeepEqual(got, c.want) {
			t.Errorf("dependentsOf(%q) = %v, want %v", c.target, got, c.want)
		}
	}
}

func TestMissingFrom(t *testing.T) {
	have := func(id string) bool { return id == "40-moonraker" || id == "tunneled-klipper" }
	needs := []string{"40-moonraker", "vanilla-klipper", "vanilla-klipper|tunneled-klipper", "a|b"}
	if got := missingFrom(needs, have); !reflect.DeepEqual(got, []string{"vanilla-klipper", "a|b"}) {
		t.Errorf("missingFrom = %v", got)
	}
	if got := missingFrom(nil, have); got != nil {
		t.Errorf("missingFrom(nil) = %v, want nothing", got)
	}
	if got := spellOut([]string{"x", "a|b"}); got != "x, a or b" {
		t.Errorf("spellOut = %q", got)
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
