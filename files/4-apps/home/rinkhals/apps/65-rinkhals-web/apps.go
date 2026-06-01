package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

// Locations that match tools.sh:
//   BUILTIN_APP_PATH = $RINKHALS_ROOT/home/rinkhals/apps   (system apps shipped in the SWU)
//   USER_APP_PATH    = $RINKHALS_HOME/apps                 (user overrides + per-app .config files)
//   TEMPORARY_APP_PATH = /tmp/rinkhals/apps                (session-only overrides)
//
// RINKHALS_ROOT is the SWU mount; we resolve it from the live symlink so we
// pick up version upgrades without restarting rinkhals-web.
const (
	rinkhalsCurrent  = "/useremain/rinkhals/.current"
	userAppPath      = "/useremain/home/rinkhals/apps"
	temporaryAppPath = "/tmp/rinkhals/apps"
	toolsSh          = "/useremain/rinkhals/.current/tools.sh"
)

func builtinAppPath() string {
	return filepath.Join(rinkhalsCurrent, "home/rinkhals/apps")
}

// AppProperty mirrors a single entry in app.json's "properties" object,
// augmented with the resolved current value. The Advanced flag is a UI hint -
// advanced properties are hidden from the default Configure drawer view and
// only revealed when the user opts in to "Show advanced settings". It is not
// a security boundary; the same authenticated user can still write through
// the API directly.
type AppProperty struct {
	Key        string   `json:"key"`
	Display    string   `json:"display"`
	Type       string   `json:"type"`
	Options    []string `json:"options,omitempty"`
	Default    string   `json:"default"`
	Value      string   `json:"value"`
	Overridden bool     `json:"overridden"`
	Advanced   bool     `json:"advanced,omitempty"`
}

// AppRequirements mirrors the optional "requirements" object.
type AppRequirements struct {
	Memory int `json:"memory,omitempty"`
	CPU    int `json:"cpu,omitempty"`
}

// AppManifest is the raw shape of app.json on disk.
type AppManifest struct {
	Version      string                            `json:"$version"`
	Name         string                            `json:"name"`
	Description  string                            `json:"description"`
	AppVersion   string                            `json:"version"`
	Requirements *AppRequirements                  `json:"requirements,omitempty"`
	Properties   map[string]map[string]interface{} `json:"properties,omitempty"`
	// Optional upstream-tracking declaration. Only catalog apps (and only those
	// that actually pull binaries from somewhere) populate this. Local apps
	// loaded by /api/apps simply ignore it.
	Upstream *UpstreamRef `json:"upstream,omitempty"`
}

// App is the wire shape returned by /api/apps.
type App struct {
	ID           string           `json:"id"`
	Name         string           `json:"name"`
	Description  string           `json:"description"`
	Version      string           `json:"version"`
	Source       string           `json:"source"` // "system" or "user"
	Enabled      bool             `json:"enabled"`
	Running      bool             `json:"running"`
	Requirements *AppRequirements `json:"requirements,omitempty"`
	Properties   []AppProperty    `json:"properties"`
}

// listAppIDs walks builtin + user directories and returns a deduplicated,
// sorted list of app IDs (the directory names, e.g. "40-moonraker").
func listAppIDs() []string {
	seen := map[string]bool{}
	add := func(root string) {
		entries, err := os.ReadDir(root)
		if err != nil {
			return
		}
		for _, e := range entries {
			if !e.IsDir() {
				continue
			}
			seen[e.Name()] = true
		}
	}
	add(builtinAppPath())
	add(userAppPath)

	ids := make([]string, 0, len(seen))
	for id := range seen {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

// resolveAppRoot picks the user app directory when present, otherwise the
// builtin one — same precedence tools.sh's get_app_root uses.
func resolveAppRoot(id string) (root, source string) {
	userRoot := filepath.Join(userAppPath, id)
	if st, err := os.Stat(userRoot); err == nil && st.IsDir() {
		return userRoot, "user"
	}
	return filepath.Join(builtinAppPath(), id), "system"
}

func readManifest(root string) (*AppManifest, error) {
	data, err := os.ReadFile(filepath.Join(root, "app.json"))
	if err != nil {
		return nil, err
	}
	var m AppManifest
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, err
	}
	return &m, nil
}

// readConfigFile parses the JSON config blob at path and returns it as a
// flat string map. Missing/unreadable/malformed files return an empty map -
// callers shouldn't see errors here, only the absence of values.
func readConfigFile(path string) map[string]string {
	out := map[string]string{}
	data, err := os.ReadFile(path)
	if err != nil {
		return out
	}
	var raw map[string]interface{}
	if err := json.Unmarshal(data, &raw); err != nil {
		return out
	}
	for k, v := range raw {
		if v == nil {
			continue
		}
		out[k] = fmt.Sprint(v)
	}
	return out
}

// readUserConfig returns persistent user overrides (the JSON written by
// set_app_property under USER_APP_PATH/<id>.config). The UI marks anything
// found here as "overridden" so the user knows they've changed it from the
// default.
func readUserConfig(id string) map[string]string {
	return readConfigFile(filepath.Join(userAppPath, id+".config"))
}

// readTempConfig returns runtime values an app has written back to itself
// via set_temporary_app_property (under TEMPORARY_APP_PATH/<id>.config). This
// is how apps publish output that needs to surface in the UI (e.g. Tailscale
// writes its login URL into account_login here, OctoEverywhere writes the
// link URL into printer_link). These values are not user overrides - they're
// the app's own runtime state.
func readTempConfig(id string) map[string]string {
	return readConfigFile(filepath.Join(temporaryAppPath, id+".config"))
}

// queryAppStates runs a single shell invocation that emits a line per app
// with enabled and running flags. This keeps the cost flat (one fork) instead
// of paying it per-app.
func queryAppStates(ids []string) map[string]struct {
	Enabled bool
	Running bool
} {
	result := map[string]struct {
		Enabled bool
		Running bool
	}{}
	if len(ids) == 0 {
		return result
	}

	// Build a small shell snippet that prints "<id>|<enabled>|<status>" for each.
	// is_app_enabled prints 1 when enabled, blank otherwise. get_app_status
	// prints "started" or "stopped".
	var b strings.Builder
	fmt.Fprintf(&b, ". %s\n", toolsSh)
	for _, id := range ids {
		fmt.Fprintf(&b,
			"printf '%s|%%s|%%s\\n' \"$(is_app_enabled %s 2>/dev/null)\" \"$(get_app_status %s 2>/dev/null)\"\n",
			id, id, id)
	}

	out, err := exec.Command("sh", "-c", b.String()).Output()
	if err != nil {
		return result
	}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.SplitN(line, "|", 3)
		if len(parts) != 3 {
			continue
		}
		result[parts[0]] = struct {
			Enabled bool
			Running bool
		}{
			Enabled: strings.TrimSpace(parts[1]) == "1",
			Running: strings.Contains(parts[2], "started"),
		}
	}
	return result
}

// buildProperties merges app.json's property declarations with the persisted
// user overrides AND the temporary runtime values, picking the effective value
// with the same precedence tools.sh's get_app_property uses:
//
//	temp (runtime) > user (persistent) > default
//
// Only persistent user overrides set Overridden=true. A value sourced from the
// temp config is just runtime state (e.g. Tailscale writing its login URL into
// account_login) and shouldn't be labelled "user override".
func buildProperties(manifest *AppManifest, userCfg, tempCfg map[string]string) []AppProperty {
	if manifest == nil || len(manifest.Properties) == 0 {
		return []AppProperty{}
	}
	props := make([]AppProperty, 0, len(manifest.Properties))
	for key, raw := range manifest.Properties {
		p := AppProperty{Key: key}
		if v, ok := raw["display"].(string); ok {
			p.Display = v
		}
		if v, ok := raw["type"].(string); ok {
			p.Type = v
		}
		if v, ok := raw["default"]; ok && v != nil {
			p.Default = fmt.Sprint(v)
		}
		if opts, ok := raw["options"].([]interface{}); ok {
			for _, o := range opts {
				if o != nil {
					p.Options = append(p.Options, fmt.Sprint(o))
				}
			}
		}
		if v, ok := raw["advanced"].(bool); ok {
			p.Advanced = v
		}
		if v, has := tempCfg[key]; has && v != "" {
			p.Value = v // runtime value from /tmp; not flagged as overridden
		} else if v, has := userCfg[key]; has {
			p.Value = v
			p.Overridden = true
		} else {
			p.Value = p.Default
		}
		props = append(props, p)
	}
	sort.Slice(props, func(i, j int) bool { return props[i].Key < props[j].Key })
	return props
}

// appNeedsConfiguration reports whether an app has at least one *user-facing*
// property with no default. Apps like that should be configured before they
// are enabled; apps whose user-facing properties all have sensible defaults
// (or are advanced/output-only) are safe to auto-enable. The following
// property kinds don't count toward the gate:
//
//   - Advanced properties: hidden behind an opt-in toggle.
//   - "qr" type properties: these are output values that the app writes back
//     into its own config (e.g. Tailscale's account_login URL, OctoEverywhere's
//     printer_link). The user can't supply them ahead of time, so they should
//     never block install. The portal renders them as QR codes when present.
func appNeedsConfiguration(manifest *AppManifest) bool {
	for _, p := range buildProperties(manifest, nil, nil) {
		if p.Advanced {
			continue
		}
		if p.Type == "qr" {
			continue
		}
		if strings.TrimSpace(p.Default) == "" {
			return true
		}
	}
	return false
}

// loadApp returns the full wire shape for a single ID. It returns an error when
// the app directory doesn't exist (neither user nor builtin), so callers can
// turn a request for an unknown app into a 404.
func loadApp(id string, state map[string]struct {
	Enabled bool
	Running bool
}) (*App, error) {
	root, source := resolveAppRoot(id)
	if st, err := os.Stat(root); err != nil || !st.IsDir() {
		return nil, fmt.Errorf("app not found: %s", id)
	}
	manifest, err := readManifest(root)
	if err != nil {
		// Directory exists but the manifest is missing/unreadable — surface a
		// stub rather than 404ing an app that is actually installed.
		manifest = &AppManifest{Name: id}
	}

	userCfg := readUserConfig(id)
	tempCfg := readTempConfig(id)
	props := buildProperties(manifest, userCfg, tempCfg)

	s := state[id]
	return &App{
		ID:           id,
		Name:         strings.TrimSpace(stringOr(manifest.Name, id)),
		Description:  manifest.Description,
		Version:      manifest.AppVersion,
		Source:       source,
		Enabled:      s.Enabled,
		Running:      s.Running,
		Requirements: manifest.Requirements,
		Properties:   props,
	}, nil
}

func stringOr(s, fallback string) string {
	if strings.TrimSpace(s) == "" {
		return fallback
	}
	return s
}

// --- HTTP handlers ---

func handleAppsList(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "GET, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != "GET" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	ids := listAppIDs()
	state := queryAppStates(ids)

	apps := make([]*App, 0, len(ids))
	for _, id := range ids {
		app, err := loadApp(id, state)
		if err != nil {
			continue
		}
		apps = append(apps, app)
	}
	json.NewEncoder(w).Encode(apps)
}

func handleApp(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "GET, POST, PUT, DELETE, OPTIONS") {
		return
	}
	writeJSONHeaders(w)

	// Parse "/api/apps/{id}[/...]" with the suffix being subresource routing.
	rest := strings.TrimPrefix(r.URL.Path, "/api/apps/")
	parts := strings.SplitN(rest, "/", 2)
	if parts[0] == "" {
		http.Error(w, "App ID required", http.StatusBadRequest)
		return
	}
	id := parts[0]
	// App ids are directory names (e.g. "40-moonraker"); reject anything that
	// isn't a plain identifier so a crafted path can't reach the shell helpers,
	// several of which interpolate the id unquoted.
	if !isSafeKey(id) {
		http.Error(w, "Invalid app id", http.StatusBadRequest)
		return
	}
	sub := ""
	if len(parts) == 2 {
		sub = parts[1]
	}

	switch {
	case sub == "" && r.Method == "GET":
		state := queryAppStates([]string{id})
		app, err := loadApp(id, state)
		if err != nil {
			http.Error(w, err.Error(), http.StatusNotFound)
			return
		}
		json.NewEncoder(w).Encode(app)

	case sub == "" && r.Method == "DELETE":
		// Uninstall a user app: stop it, disable it, remove the directory plus
		// any persisted/temporary config and stray flag files. Only user apps
		// (under USER_APP_PATH) can be uninstalled - system apps would reappear
		// at the next boot from the SWU bundle anyway, so deleting them is a
		// no-op that surprises the user.
		root, source := resolveAppRoot(id)
		if source != "user" {
			http.Error(w, "Cannot uninstall a system app; system apps ship in the firmware", http.StatusUnprocessableEntity)
			return
		}
		// Defence in depth: confirm the resolved path is really under userAppPath
		// before we hand it to os.RemoveAll. isSafeKey already rejects '/', so
		// this guards against a future symlink at $USER_APP_PATH/foo pointing
		// outside the tree.
		rel, relErr := filepath.Rel(userAppPath, root)
		if relErr != nil || strings.HasPrefix(rel, "..") || rel == "." || rel == "" {
			http.Error(w, "Invalid app path", http.StatusBadRequest)
			return
		}

		// Best-effort: stop and disable the app before removing files. We don't
		// fail the uninstall if these fail; an already-stopped app is fine and
		// disable_app on a missing dir is a no-op.
		preCmd := fmt.Sprintf(". %s\nstop_app %s 2>/dev/null || true\ndisable_app %s 2>/dev/null || true\n",
			toolsSh, shellQuote(id), shellQuote(id))
		_ = exec.Command("sh", "-c", preCmd).Run()

		var rmErrs []string
		if err := os.RemoveAll(root); err != nil {
			rmErrs = append(rmErrs, "app directory: "+err.Error())
		}
		// Persistent and temporary user config, plus top-level enable/disable
		// flags for the user-app case. Each is best-effort; missing files are
		// expected and not errors.
		_ = os.Remove(filepath.Join(userAppPath, id+".config"))
		_ = os.Remove(filepath.Join(userAppPath, id+".enabled"))
		_ = os.Remove(filepath.Join(userAppPath, id+".disabled"))
		_ = os.Remove(filepath.Join(temporaryAppPath, id+".config"))

		// Catalog "Installed" state derives from app dirs on disk, so bust it.
		invalidateCatalog()

		resp := map[string]interface{}{
			"success": len(rmErrs) == 0,
			"app":     id,
		}
		if len(rmErrs) > 0 {
			resp["output"] = strings.Join(rmErrs, "; ")
		} else {
			resp["output"] = "Uninstalled " + id
		}
		json.NewEncoder(w).Encode(resp)

	case sub == "enable" && r.Method == "POST":
		runAppHelper(w, "enable_app", id)

	case sub == "disable" && r.Method == "POST":
		runAppHelper(w, "disable_app", id)

	case sub == "action" && r.Method == "POST":
		var req struct {
			Action string `json:"action"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid body", http.StatusBadRequest)
			return
		}
		switch req.Action {
		case "start":
			runAppHelper(w, "start_app", id)
		case "stop":
			runAppHelper(w, "stop_app", id)
		case "restart":
			q := shellQuote(id)
			runAppCmd(w, fmt.Sprintf("stop_app %s; sleep 1; start_app %s", q, q))
		default:
			http.Error(w, "Invalid action", http.StatusBadRequest)
		}

	case sub == "config" && r.Method == "GET":
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(readUserConfig(id))

	case sub == "config" && r.Method == "PUT":
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "Invalid body", http.StatusBadRequest)
			return
		}
		// Run all set_app_property calls in one shell invocation.
		var b strings.Builder
		fmt.Fprintf(&b, ". %s\n", toolsSh)
		for k, v := range body {
			// Reject any key that isn't a simple identifier so we can't inject jq
			// expressions into the helper.
			if !isSafeKey(k) {
				http.Error(w, "Invalid property key: "+k, http.StatusBadRequest)
				return
			}
			fmt.Fprintf(&b, "set_app_property %s %s %s\n", shellQuote(id), shellQuote(k), shellQuote(v))
		}
		out, err := exec.Command("sh", "-c", b.String()).CombinedOutput()
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": err == nil,
			"output":  string(out),
		})

	case sub == "config" && r.Method == "DELETE":
		runAppHelper(w, "clear_app_properties", id)

	case strings.HasPrefix(sub, "config/") && r.Method == "DELETE":
		key := strings.TrimPrefix(sub, "config/")
		if !isSafeKey(key) {
			http.Error(w, "Invalid property key", http.StatusBadRequest)
			return
		}
		runAppCmd(w, fmt.Sprintf("remove_app_property %s %s", shellQuote(id), shellQuote(key)))

	default:
		http.Error(w, "Not found", http.StatusNotFound)
	}
}

// --- helpers ---

func writeJSONHeaders(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Content-Type", "application/json")
}

// corsPreflight answers a CORS OPTIONS preflight and reports whether it handled
// the request. On-device the UI is same-origin so this never fires; it exists so
// PUT/DELETE/POST work from the cross-origin Vite dev server (5173 -> 8080).
func corsPreflight(w http.ResponseWriter, r *http.Request, methods string) bool {
	if r.Method != http.MethodOptions {
		return false
	}
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", methods)
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
	w.WriteHeader(http.StatusNoContent)
	return true
}

func runAppHelper(w http.ResponseWriter, helper, id string) {
	runAppCmd(w, fmt.Sprintf("%s %s", helper, shellQuote(id)))
}

func runAppCmd(w http.ResponseWriter, body string) {
	cmd := fmt.Sprintf(". %s\n%s\n", toolsSh, body)
	out, err := exec.Command("sh", "-c", cmd).CombinedOutput()
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": err == nil,
		"output":  string(out),
	})
}

func shellQuote(s string) string {
	// Single-quote and escape embedded single quotes the POSIX-portable way.
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}

func isSafeKey(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		ok := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' || r == '-'
		if !ok {
			return false
		}
	}
	return true
}
