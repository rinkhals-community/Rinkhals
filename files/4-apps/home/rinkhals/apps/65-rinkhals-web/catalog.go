package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// The community app catalog lives at https://github.com/rinkhals-community/Rinkhals.Apps.
// We hit two GitHub endpoints (Contents API + latest release) and then raw.githubusercontent.com
// for individual app.json files - the raw host isn't rate-limited, which keeps us well
// under the 60 unauthenticated API requests/hour ceiling.
const (
	catalogOwner          = "rinkhals-community"
	catalogRepo           = "Rinkhals.Apps"
	catalogBranch         = "master"
	catalogContentsAPI    = "https://api.github.com/repos/rinkhals-community/Rinkhals.Apps/contents/apps"
	catalogLatestRelease  = "https://api.github.com/repos/rinkhals-community/Rinkhals.Apps/releases/latest"
	catalogRawBase        = "https://raw.githubusercontent.com/rinkhals-community/Rinkhals.Apps"
	catalogCacheTTL       = 10 * time.Minute
	catalogHTTPTimeout    = 15 * time.Second
	// Download to persistent eMMC, not /tmp: /tmp is tmpfs (RAM) and a large app
	// SWU would be held in memory while install_swu also extracts into /useremain,
	// risking OOM on memory-constrained printers.
	catalogDownloadTmp    = "/useremain/rinkhals-catalog"
	catalogUserAgent      = "rinkhals-web"
)

// UpstreamRef mirrors the optional "upstream" block in app.json. Apps that
// pull binaries from an external source declare where to look so we can show
// the live upstream version next to the bundled one.
type UpstreamRef struct {
	Type        string `json:"type"`                   // "github-release" or "github-branch-head"
	Repo        string `json:"repo"`                   // owner/name
	StripPrefix string `json:"strip_prefix,omitempty"` // e.g. "v" so v1.2.3 reads as 1.2.3
	Branch      string `json:"branch,omitempty"`       // for github-branch-head; defaults to "master"
}

// CatalogApp is the wire shape returned to the UI - the per-app manifest plus
// the installation-aware fields (download URL for this printer model, install
// state) and upstream-tracking fields (live upstream version, link).
type CatalogApp struct {
	ID                string           `json:"id"`
	Name              string           `json:"name"`
	Description       string           `json:"description"`
	Version           string           `json:"version"`
	Requirements      *AppRequirements `json:"requirements,omitempty"`
	Depends           []string         `json:"depends,omitempty"`
	AvailableForModel bool             `json:"available_for_model"`
	DownloadURL       string           `json:"download_url,omitempty"`
	AssetSize         int64            `json:"asset_size,omitempty"`
	Installed         bool             `json:"installed"`
	InstalledVersion  string           `json:"installed_version,omitempty"`
	// Upstream tracking. Upstream is the declared source (so the UI can link
	// to it); UpstreamVersion is what we resolved at fetch time, blank when
	// unknown or when the manifest has no upstream block. The UI marks the
	// card stale when UpstreamVersion != Version.
	Upstream        *UpstreamRef `json:"upstream,omitempty"`
	UpstreamVersion string       `json:"upstream_version,omitempty"`
	UpstreamURL     string       `json:"upstream_url,omitempty"`
}

type Catalog struct {
	Release   string       `json:"release"`
	FetchedAt time.Time    `json:"fetched_at"`
	Model     string       `json:"model"`         // resolved KOBRA_MODEL_CODE
	AssetGroup string      `json:"asset_group"`   // mapped SWU suffix (e.g. "k2p-k3")
	Apps      []CatalogApp `json:"apps"`
	Notice    string       `json:"notice,omitempty"` // surfaced when model has no SWU group mapping
}

// Cache state. catalogDataMu guards the cached pointer and is only ever held
// briefly; catalogBuildMu serializes the slow network rebuild so concurrent
// callers don't stampede GitHub. Reads of a fresh cache never block on a
// rebuild in progress. installMu serializes SWU installs, which share the
// fixed /useremain/update_swu staging directory inside install_swu.
var (
	catalogDataMu  sync.Mutex
	catalogBuildMu sync.Mutex
	catalogData    *Catalog
	catalogStamp   time.Time

	installMu sync.Mutex

	// Upstream-version lookups have a separate (longer) cache than the
	// catalog itself. The catalog refreshes every 10 minutes, but upstream
	// versions change much more slowly and each lookup is its own GitHub API
	// call; caching them for 6 hours keeps us well under the unauthenticated
	// 60/hr budget even when the user hammers Refresh.
	upstreamCacheMu  sync.Mutex
	upstreamCache    = map[string]upstreamCacheEntry{}
	upstreamCacheTTL = 6 * time.Hour
)

type upstreamCacheEntry struct {
	Version string
	URL     string
	At      time.Time
}

// modelToAssetGroup maps the KOBRA_MODEL_CODE that tools.sh exposes to the
// SWU asset suffix the Rinkhals.Apps release uses. Models without an
// explicit SWU build fall back to the closest hardware match - if Rinkhals.Apps
// later ships a dedicated build, the user will just stop seeing the fallback notice.
func modelToAssetGroup(model string) (string, string) {
	switch strings.ToUpper(strings.TrimSpace(model)) {
	case "K2P", "K3":
		return "k2p-k3", ""
	case "K3V2":
		return "k2p-k3", "no dedicated K3V2 SWU group; using K2P/K3 build"
	case "K3M":
		return "k3m", ""
	case "KS1":
		return "ks1", ""
	case "KS1M":
		return "ks1", "no dedicated KS1M SWU group; using KS1 build"
	default:
		return "", "unknown printer model (" + model + "); SWU downloads disabled"
	}
}

func currentModelCode() string {
	// tools.sh exports KOBRA_MODEL_CODE; rinkhals-web runs in an environment
	// that sources rinkhals, so it's available in os.Environ. As a safety net
	// we shell out if the var isn't already set.
	if m := os.Getenv("KOBRA_MODEL_CODE"); m != "" {
		return m
	}
	out, err := exec.Command("sh", "-c", ". "+toolsSh+" >/dev/null 2>&1; printf %s \"$KOBRA_MODEL_CODE\"").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// installedAppVersions reads each currently-installed user app's manifest and
// returns a name -> version map so we can mark catalog entries as already installed.
func installedAppVersions() map[string]string {
	out := map[string]string{}
	entries, err := os.ReadDir(userAppPath)
	if err != nil {
		return out
	}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		m, err := readManifest(filepath.Join(userAppPath, e.Name()))
		if err != nil || m == nil {
			out[e.Name()] = "" // installed, version unknown
			continue
		}
		out[e.Name()] = m.AppVersion
	}
	return out
}

// --- GitHub fetchers ---

func httpGetJSON(url string, into interface{}) error {
	client := &http.Client{Timeout: catalogHTTPTimeout}
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("User-Agent", catalogUserAgent)
	req.Header.Set("Accept", "application/vnd.github+json")
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("GET %s: %s: %s", url, resp.Status, strings.TrimSpace(string(body)))
	}
	return json.NewDecoder(resp.Body).Decode(into)
}

type ghContentEntry struct {
	Name string `json:"name"`
	Type string `json:"type"`
}

type ghReleaseAsset struct {
	Name               string `json:"name"`
	BrowserDownloadURL string `json:"browser_download_url"`
	Size               int64  `json:"size"`
}

type ghRelease struct {
	TagName string           `json:"tag_name"`
	Assets  []ghReleaseAsset `json:"assets"`
}

// fetchManifest pulls apps/<name>/app.json from raw.githubusercontent.com at
// the given git ref (branch or tag). Empty ref falls back to catalogBranch.
// raw isn't rate-limited so we hammer it freely.
func fetchManifest(appName, ref string) (*AppManifest, error) {
	if ref == "" {
		ref = catalogBranch
	}
	url := fmt.Sprintf("%s/%s/apps/%s/app.json", catalogRawBase, ref, appName)
	var m AppManifest
	if err := httpGetJSON(url, &m); err != nil {
		return nil, err
	}
	return &m, nil
}

// resolveUpstream returns the live upstream version + a human-readable URL,
// using a 6-hour cache per (type|repo|branch) key. Network errors and unknown
// types return empty strings rather than failing the whole catalog rebuild -
// staleness data is a nice-to-have, not a blocker.
func resolveUpstream(u *UpstreamRef) (version, url string) {
	if u == nil || u.Type == "" || u.Repo == "" {
		return "", ""
	}
	branch := u.Branch
	if branch == "" {
		branch = "master"
	}
	key := u.Type + "|" + u.Repo + "|" + branch

	upstreamCacheMu.Lock()
	hit, ok := upstreamCache[key]
	upstreamCacheMu.Unlock()
	if ok && time.Since(hit.At) < upstreamCacheTTL {
		return hit.Version, hit.URL
	}

	switch u.Type {
	case "github-release":
		var rel struct {
			TagName string `json:"tag_name"`
			HTMLURL string `json:"html_url"`
		}
		if err := httpGetJSON("https://api.github.com/repos/"+u.Repo+"/releases/latest", &rel); err == nil {
			v := rel.TagName
			if u.StripPrefix != "" && strings.HasPrefix(v, u.StripPrefix) {
				v = v[len(u.StripPrefix):]
			}
			version, url = v, rel.HTMLURL
		}
	case "github-branch-head":
		var c struct {
			SHA     string `json:"sha"`
			HTMLURL string `json:"html_url"`
		}
		if err := httpGetJSON("https://api.github.com/repos/"+u.Repo+"/commits/"+branch, &c); err == nil {
			short := c.SHA
			if len(short) > 8 {
				short = short[:8]
			}
			version, url = short, c.HTMLURL
		}
	default:
		// Unknown type: leave both empty so the UI shows nothing.
	}

	upstreamCacheMu.Lock()
	upstreamCache[key] = upstreamCacheEntry{Version: version, URL: url, At: time.Now()}
	upstreamCacheMu.Unlock()
	return version, url
}

// rebuildCatalog is the slow path: list app dirs, fetch each manifest, fetch
// the latest release, fuse everything together, and return it. Safe to call
// concurrently with reads via the mutex.
func rebuildCatalog() (*Catalog, error) {
	// 1. List apps/
	var entries []ghContentEntry
	if err := httpGetJSON(catalogContentsAPI, &entries); err != nil {
		return nil, fmt.Errorf("listing catalog apps/: %w", err)
	}

	// 2. Latest release
	var rel ghRelease
	if err := httpGetJSON(catalogLatestRelease, &rel); err != nil {
		// Non-fatal: we can still show the catalog without download URLs.
		rel = ghRelease{}
	}

	// 3. Model resolution
	model := currentModelCode()
	group, notice := modelToAssetGroup(model)
	installed := installedAppVersions()

	// Index release assets by app name for quick lookup.
	type assetMatch struct {
		url  string
		size int64
	}
	assetByApp := map[string]assetMatch{}
	if group != "" {
		suffix := "-" + group + ".swu"
		prefix := "app-"
		for _, a := range rel.Assets {
			if !strings.HasPrefix(a.Name, prefix) || !strings.HasSuffix(a.Name, suffix) {
				continue
			}
			appName := strings.TrimSuffix(strings.TrimPrefix(a.Name, prefix), suffix)
			assetByApp[appName] = assetMatch{url: a.BrowserDownloadURL, size: a.Size}
		}
	}

	// 4. Pull each manifest. The listing has ~12 entries so doing this serially is fine
	//    and a lot cheaper than parallel HTTP for our latency budget.
	apps := make([]CatalogApp, 0, len(entries))
	for _, e := range entries {
		if e.Type != "dir" {
			continue
		}
		// Read the manifest from the same point the installable SWU was built
		// (the latest release tag) so the displayed version matches what will
		// actually install. Apps with no release asset for this model are not
		// installable, so they fall back to the branch HEAD manifest for display.
		ref := catalogBranch
		if _, ok := assetByApp[e.Name]; ok && rel.TagName != "" {
			ref = rel.TagName
		}
		m, err := fetchManifest(e.Name, ref)
		if err != nil {
			// One bad manifest shouldn't take down the catalog; surface a stub.
			apps = append(apps, CatalogApp{
				ID:   e.Name,
				Name: e.Name,
				Description: fmt.Sprintf("Failed to read manifest: %v", err),
			})
			continue
		}

		entry := CatalogApp{
			ID:           e.Name,
			Name:         stringOr(m.Name, e.Name),
			Description:  m.Description,
			Version:      m.AppVersion,
			Requirements: m.Requirements,
			Upstream:     m.Upstream,
		}
		if asset, ok := assetByApp[e.Name]; ok {
			entry.AvailableForModel = true
			entry.DownloadURL = asset.url
			entry.AssetSize = asset.size
		}
		if v, ok := installed[e.Name]; ok {
			entry.Installed = true
			entry.InstalledVersion = v
		}
		if m.Upstream != nil {
			entry.UpstreamVersion, entry.UpstreamURL = resolveUpstream(m.Upstream)
		}
		apps = append(apps, entry)
	}

	return &Catalog{
		Release:    rel.TagName,
		FetchedAt:  time.Now().UTC(),
		Model:      model,
		AssetGroup: group,
		Apps:       apps,
		Notice:     notice,
	}, nil
}

// getCatalog returns a cached catalog if fresh, otherwise rebuilds. The rebuild
// runs without holding the data lock, so a fresh-cache read is never blocked by
// a slow GitHub fetch; only the rebuild itself is serialized (catalogBuildMu).
func getCatalog(force bool) (*Catalog, error) {
	// Fast path: serve a fresh cache without touching the build lock.
	catalogDataMu.Lock()
	data, stamp := catalogData, catalogStamp
	catalogDataMu.Unlock()
	if !force && data != nil && time.Since(stamp) < catalogCacheTTL {
		return data, nil
	}

	// Serialize rebuilds. Callers that arrive during a rebuild wait here, then
	// pick up the fresh result from the re-check below instead of refetching.
	catalogBuildMu.Lock()
	defer catalogBuildMu.Unlock()

	catalogDataMu.Lock()
	data, stamp = catalogData, catalogStamp
	catalogDataMu.Unlock()
	if !force && data != nil && time.Since(stamp) < catalogCacheTTL {
		return data, nil
	}

	c, err := rebuildCatalog()
	if err != nil {
		if data != nil {
			return data, err // stale fallback
		}
		return nil, err
	}
	catalogDataMu.Lock()
	catalogData = c
	catalogStamp = time.Now()
	catalogDataMu.Unlock()
	return c, nil
}

// invalidateCatalog drops the cache so the next read rebuilds (e.g. after an
// install changes installed state).
func invalidateCatalog() {
	catalogDataMu.Lock()
	catalogData = nil
	catalogStamp = time.Time{}
	catalogDataMu.Unlock()
}

// --- HTTP handlers ---

func handleCatalog(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "GET, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != "GET" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	force := r.URL.Query().Get("refresh") == "1"
	c, err := getCatalog(force)
	if err != nil {
		// If we returned stale data alongside an error, include both.
		if c != nil {
			w.Header().Set("X-Catalog-Warning", err.Error())
			json.NewEncoder(w).Encode(c)
			return
		}
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	json.NewEncoder(w).Encode(c)
}

func handleCatalogRefresh(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "POST, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	c, err := getCatalog(true)
	if err != nil && c == nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	json.NewEncoder(w).Encode(c)
}

// handleCatalogInstall handles POST /api/catalog/{id}/install. Downloads the
// matching SWU for the current model to eMMC and pipes it through install_swu
// (the same code path the USB-stick installer uses). When the freshly installed
// app needs no configuration, it is enabled and started automatically.
func handleCatalogInstall(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "POST, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != "POST" {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Path is /api/catalog/{id}/install
	rest := strings.TrimPrefix(r.URL.Path, "/api/catalog/")
	parts := strings.SplitN(rest, "/", 2)
	if len(parts) != 2 || parts[1] != "install" || parts[0] == "" {
		http.Error(w, "Not found", http.StatusNotFound)
		return
	}
	id := parts[0]
	if !isSafeKey(id) {
		http.Error(w, "Invalid app id", http.StatusBadRequest)
		return
	}

	// Serialize installs: install_swu wipes and reuses a fixed staging dir
	// (/useremain/update_swu), so two concurrent installs would corrupt each
	// other. Reject rather than queue so the caller gets immediate feedback.
	if !installMu.TryLock() {
		http.Error(w, "Another install is already in progress", http.StatusConflict)
		return
	}
	defer installMu.Unlock()

	// Find the catalog entry to discover the download URL for this model.
	c, err := getCatalog(false)
	if err != nil && c == nil {
		http.Error(w, "Catalog unavailable: "+err.Error(), http.StatusBadGateway)
		return
	}
	var entry *CatalogApp
	for i := range c.Apps {
		if c.Apps[i].ID == id {
			entry = &c.Apps[i]
			break
		}
	}
	if entry == nil {
		http.Error(w, "Unknown app: "+id, http.StatusNotFound)
		return
	}
	if !entry.AvailableForModel || entry.DownloadURL == "" {
		http.Error(w, "No SWU available for this printer model", http.StatusUnprocessableEntity)
		return
	}

	// Download to /tmp/rinkhals-catalog/<id>.swu
	if err := os.MkdirAll(catalogDownloadTmp, 0755); err != nil {
		http.Error(w, "Failed to prepare download dir: "+err.Error(), http.StatusInternalServerError)
		return
	}
	swuPath := filepath.Join(catalogDownloadTmp, id+".swu")
	if err := downloadFile(entry.DownloadURL, swuPath); err != nil {
		http.Error(w, "Download failed: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer os.Remove(swuPath)

	// Pipe through install_swu (in tools.sh). This is the same call path the
	// USB-stick installer uses, so success here matches what users get today.
	cmd := fmt.Sprintf(". %s\ninstall_swu %s\n", toolsSh, shellQuote(swuPath))
	out, err := exec.Command("sh", "-c", cmd).CombinedOutput()
	installed := err == nil

	resp := map[string]interface{}{
		"success":      installed,
		"output":       string(out),
		"app":          id,
		"installed":    installed,
		"needs_config": false,
		"auto_enabled": false,
	}

	if installed {
		// Decide auto-enable from the freshly installed manifest. Apps whose
		// properties all have defaults (or that have none) are safe to enable
		// and start now; apps that need user input are left disabled so they
		// can be configured first.
		manifest, _ := readManifest(filepath.Join(userAppPath, id))
		needsConfig := appNeedsConfiguration(manifest)
		resp["needs_config"] = needsConfig

		if !needsConfig {
			q := shellQuote(id)
			enableCmd := fmt.Sprintf(". %s\nenable_app %s && start_app %s\n", toolsSh, q, q)
			eout, eerr := exec.Command("sh", "-c", enableCmd).CombinedOutput()
			resp["auto_enabled"] = eerr == nil
			resp["enable_output"] = string(eout)
		}
	}

	// Bust the catalog cache so a subsequent GET shows "installed: true".
	invalidateCatalog()
	json.NewEncoder(w).Encode(resp)
}

func downloadFile(url, dst string) error {
	client := &http.Client{Timeout: 5 * time.Minute}
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("User-Agent", catalogUserAgent)
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("HTTP %s", resp.Status)
	}
	f, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer f.Close()
	if _, err := io.Copy(f, resp.Body); err != nil {
		return err
	}
	return nil
}

// Suppress unused-import warning until base64 ends up needed (will be used by
// future "preview README" endpoint that fetches README.md via the Contents API).
var _ = base64.StdEncoding
