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
//   - Binary patches: K3SysUi and gkapi are patched at boot by
//     rinkhals-patcher. .current/opt/rinkhals/patches/patches.txt lists the
//     firmware versions the result has been checked on, one line per binary:
//     "<binary> <model> <version> <stock MD5> <patched MD5 | unpatched |
//     unverified>".
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
	PatchFileName string `json:"patch_filename"` // file the entry comes from
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

// knownBinary is one line of patches.txt.
type knownBinary struct {
	Name, Model, FirmwareVer string
	// Result is the MD5 of the patched binary, "unpatched" when Rinkhals
	// changes nothing in it on this firmware, or "unverified".
	Result string
}

var patchesFile = "/useremain/rinkhals/.current/opt/rinkhals/patches/patches.txt"

// readKnownBinaries parses patches.txt. It returns an error only when the file
// can't be read; lines it doesn't understand are skipped.
func readKnownBinaries(path string) ([]knownBinary, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var out []knownBinary
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) != 5 || strings.HasPrefix(fields[0], "#") {
			continue
		}
		out = append(out, knownBinary{Name: fields[0], Model: fields[1], FirmwareVer: fields[2], Result: fields[4]})
	}
	return out, nil
}

// patchTargetFromBinName maps a binary's name to the path it runs from.
func patchTargetFromBinName(binName string) string {
	switch binName {
	case "K3SysUi":
		return "/app/K3SysUi"
	case "gkapi":
		return "/app/gkapi"
	}
	return "/app/" + binName
}

// collectBinaryPatches lists the binaries Rinkhals patches, per firmware.
// known reports whether the running firmware is in patches.txt at all, which
// also counts the binaries left unpatched on it.
func collectBinaryPatches(currentModel, currentFW string) (patches []binaryPatch, known bool) {
	entries, err := readKnownBinaries(patchesFile)
	if err != nil {
		return nil, false
	}
	patches = make([]binaryPatch, 0, len(entries))
	for _, e := range entries {
		applies := e.Model == currentModel && e.FirmwareVer == currentFW
		known = known || applies
		if e.Result == "unpatched" {
			continue
		}
		patches = append(patches, binaryPatch{
			Name:          e.Name,
			Target:        patchTargetFromBinName(e.Name),
			Model:         e.Model,
			FirmwareVer:   e.FirmwareVer,
			PatchFileName: filepath.Base(patchesFile),
			AppliesToThis: applies,
		})
	}
	return patches, known
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

	// Compatible-for-run = the running (model, firmware) combination is one
	// Rinkhals has been checked on.
	binaries, compat := collectBinaryPatches(model, fw)
	hooks := make([]scriptHook, 0, len(describedHooks))
	for _, h := range describedHooks {
		hooks = append(hooks, resolveScriptHook(h))
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
