package main

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// Rinkhals modifies the stock Anycubic firmware in a few well-known ways. The
// /api/firmware/patches endpoint exposes the inventory so the Manage Rinkhals
// page can show the user what's actually changed on top of stock - useful both
// for transparency and as context before deciding to swap firmware versions.
//
// We catalog two things:
//
//   - Binary patches: files under .current/opt/rinkhals/patches/, named like
//     K3SysUi.<MODEL>_<VERSION>.* or gkapi.<MODEL>_<VERSION>.*. These are
//     applied at boot to replace the stock binaries. The file name encodes
//     which model + firmware version the patch targets.
//
//   - Script-level hooks: things Rinkhals installs into /userdata or /etc to
//     wire its services into the stock init flow (start.sh patch, DNS hook,
//     etc.). These are described declaratively here because the install
//     locations are mostly static and grepping for them gives a clearer
//     picture than walking the install tree at runtime.
//
// All paths are read from the currently-installed Rinkhals - we never reach
// out to the repo, so this works on printers that have never been online.

type binaryPatch struct {
	Name          string `json:"name"`           // e.g. "K3SysUi"
	Target        string `json:"target"`         // e.g. "/app/K3SysUi"
	Model         string `json:"model"`          // e.g. "KS1"
	FirmwareVer   string `json:"firmware_ver"`   // e.g. "2.7.2.1"
	PatchFileName string `json:"patch_filename"` // raw filename under patches/
	SizeBytes     int64  `json:"size_bytes"`
	AppliesToThis bool   `json:"applies_to_this"` // matches running model+version
}

type scriptHook struct {
	Name        string `json:"name"`
	Description string `json:"description"`
	Path        string `json:"path"`
	Present     bool   `json:"present"`
}

type patchesResponse struct {
	ModelCode        string        `json:"model_code"`
	FirmwareVersion  string        `json:"firmware_version"`
	RinkhalsVersion  string        `json:"rinkhals_version"`
	BinaryPatches    []binaryPatch `json:"binary_patches"`
	ScriptHooks      []scriptHook  `json:"script_hooks"`
	CompatibleForRun bool          `json:"compatible_for_run"`
}

// parsePatchFilename interprets filenames like "K3SysUi.KS1_2.7.2.1.sh" or
// "gkapi.K2P_3.1.4.bsdiff" into (name, model, firmwareVer). Returns empty
// strings for the components that don't match the pattern.
func parsePatchFilename(name string) (binName, model, fwVer string) {
	// Split off extension (everything after the last dot at the end).
	base := name
	if i := strings.LastIndex(base, "."); i > 0 {
		// Common patch extensions: .sh, .bsdiff, .patch, .bin. If the suffix
		// looks short and alphanumeric, treat it as an extension; otherwise
		// leave it in (some manifests use multi-part suffixes).
		ext := base[i+1:]
		if len(ext) <= 8 && allAlnum(ext) {
			base = base[:i]
		}
	}
	// Expect: <binName>.<MODEL>_<FW_VER>
	parts := strings.SplitN(base, ".", 2)
	if len(parts) != 2 {
		return "", "", ""
	}
	binName = parts[0]
	rest := parts[1]
	// rest looks like KS1_2.7.2.1 - underscore separates model from version.
	us := strings.Index(rest, "_")
	if us < 0 {
		return binName, "", ""
	}
	model = rest[:us]
	fwVer = rest[us+1:]
	return
}

func allAlnum(s string) bool {
	for _, r := range s {
		if !((r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9')) {
			return false
		}
	}
	return true
}

// patchTargetFromBinName maps the short name in a patch file (the part before
// the model+version) to the actual path it overwrites at runtime.
func patchTargetFromBinName(binName string) string {
	switch binName {
	case "K3SysUi":
		return "/app/K3SysUi"
	case "gkapi":
		return "/app/gkapi"
	}
	return "/app/" + binName
}

func collectBinaryPatches(currentModel, currentFW string) []binaryPatch {
	dir := "/useremain/rinkhals/.current/opt/rinkhals/patches"
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	out := make([]binaryPatch, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		binName, model, fwVer := parsePatchFilename(name)
		if binName == "" {
			continue
		}
		info, err := e.Info()
		var size int64
		if err == nil {
			size = info.Size()
		}
		out = append(out, binaryPatch{
			Name:          binName,
			Target:        patchTargetFromBinName(binName),
			Model:         model,
			FirmwareVer:   fwVer,
			PatchFileName: name,
			SizeBytes:     size,
			AppliesToThis: model == currentModel && fwVer == currentFW,
		})
	}
	return out
}

// describedHooks is the static list of script-level modifications Rinkhals
// makes outside its own tree. Path existence is checked at request time so
// the UI shows the actual state rather than what's expected to be there.
var describedHooks = []scriptHook{
	{
		Name:        "Boot loader",
		Description: "Appended to /userdata/app/gk/start.sh so the stock init script bootstraps Rinkhals on every boot.",
		Path:        "/userdata/app/gk/start.sh",
	},
	{
		Name:        "Boot loader (K3-series restart hook)",
		Description: "Same loader appended to restart_k3c.sh on printers that use it (K3 family).",
		Path:        "/userdata/app/gk/restart_k3c.sh",
	},
	{
		Name:        "DNS fallback hook",
		Description: "udhcpc post-hook that adds public DNS resolvers when DHCP doesn't supply any, so name resolution still works when the router omits a DNS server.",
		Path:        "/useremain/rinkhals/.current/usr/share/udhcpc/default.script.d/rinkhals-dns-fallback.script",
	},
	{
		Name:        "Profile environment",
		Description: "Sets RINKHALS_* environment variables for any shell that sources /etc/profile.",
		Path:        "/useremain/rinkhals/.current/etc/profile.d/z_environment.sh",
	},
}

func resolveScriptHook(h scriptHook) scriptHook {
	out := h
	if data, err := os.ReadFile(h.Path); err == nil {
		// For start.sh-style files we want "present" to mean "Rinkhals loader
		// is appended", not just "the file exists". For others, file existence
		// is the signal.
		if filepath.Base(h.Path) == "start.sh" || filepath.Base(h.Path) == "restart_k3c.sh" {
			out.Present = strings.Contains(string(data), "Rinkhals/begin")
		} else {
			out.Present = true
		}
	} else {
		out.Present = false
	}
	return out
}

func handlePatchesList(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "GET, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	model := currentModelCode()
	fw := currentKobraVersion()
	rk := currentRinkhalsVersion()

	binaries := collectBinaryPatches(model, fw)
	hooks := make([]scriptHook, 0, len(describedHooks))
	for _, h := range describedHooks {
		hooks = append(hooks, resolveScriptHook(h))
	}

	// Compatible-for-run = at least one binary patch matches the running
	// (model, firmware) combination. When that's false, Rinkhals will fall
	// back to stock at boot time.
	compat := false
	for _, b := range binaries {
		if b.AppliesToThis {
			compat = true
			break
		}
	}

	json.NewEncoder(w).Encode(patchesResponse{
		ModelCode:        model,
		FirmwareVersion:  fw,
		RinkhalsVersion:  rk,
		BinaryPatches:    binaries,
		ScriptHooks:      hooks,
		CompatibleForRun: compat,
	})
}
