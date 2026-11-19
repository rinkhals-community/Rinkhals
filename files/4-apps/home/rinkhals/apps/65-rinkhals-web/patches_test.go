package main

import (
	"os"
	"path/filepath"
	"testing"
)

func usePatchesFile(t *testing.T, content string) {
	t.Helper()
	old := patchesFile
	t.Cleanup(func() { patchesFile = old })
	patchesFile = filepath.Join(t.TempDir(), "patches.txt")
	if content != "" {
		if err := os.WriteFile(patchesFile, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

const testPatches = `# binary model firmware stock result
K3SysUi KS1  2.7.3.5  a78d7022704e4d53e9f43b22ea22c698 40c321058549e103819d8cd44071cc43
gkapi   KS1  2.7.3.5  1b4c6496442fd712b2eaae5ff645e80a 5887354547d73ef2b4283a6b84bf4cdc
K3SysUi KS1  2.5.8.8  11111111111111111111111111111111 22222222222222222222222222222222
gkapi   KS1  2.5.8.8  33333333333333333333333333333333 unpatched
K3SysUi K3   2.4.6.4  0c94572665312b25074ccd9ad54cf27c unverified

a line that is not an entry
`

func TestCollectBinaryPatches(t *testing.T) {
	usePatchesFile(t, testPatches)

	patches, known := collectBinaryPatches("KS1", "2.7.3.5")
	if !known {
		t.Error("KS1 2.7.3.5 is listed but reported as unknown")
	}
	// The unpatched gkapi is not a patch; everything else is, unverified included.
	if len(patches) != 4 {
		t.Fatalf("got %d patches, want 4: %+v", len(patches), patches)
	}
	applies := 0
	for _, p := range patches {
		if p.AppliesToThis {
			applies++
			if p.Model != "KS1" || p.FirmwareVer != "2.7.3.5" {
				t.Errorf("%+v applies to KS1 2.7.3.5", p)
			}
		}
	}
	if applies != 2 {
		t.Errorf("%d patches apply to the running firmware, want 2", applies)
	}
	if patches[0].Target != "/app/K3SysUi" {
		t.Errorf("target = %q", patches[0].Target)
	}

	// A firmware whose only other binary is left unpatched is still a known one.
	if _, known := collectBinaryPatches("KS1", "2.5.8.8"); !known {
		t.Error("KS1 2.5.8.8 is listed but reported as unknown")
	}
	if _, known := collectBinaryPatches("KS1", "9.9.9.9"); known {
		t.Error("KS1 9.9.9.9 is not listed but reported as known")
	}
	if _, known := collectBinaryPatches("K3", "2.7.3.5"); known {
		t.Error("the version of another model counted for this one")
	}
}

func TestCollectBinaryPatchesWithoutRinkhals(t *testing.T) {
	usePatchesFile(t, "")
	if patches, known := collectBinaryPatches("KS1", "2.7.3.5"); known || len(patches) != 0 {
		t.Errorf("no patches.txt, but got %d patches (known %v)", len(patches), known)
	}
}
