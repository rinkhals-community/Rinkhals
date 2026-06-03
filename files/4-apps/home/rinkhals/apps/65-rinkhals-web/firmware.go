package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

// Sources of truth for the Firmware page:
//
//   - Anycubic stock firmware catalog comes from the Rinkhals.Firmwares mirror.
//     One JSON manifest per model under
//     raw.githubusercontent.com/rinkhals-community/Rinkhals.Firmwares/main/
//     manifests-anycubic/manifest-<model_lower>.json. The mirror tracks Anycubic
//     releases plus a community-curated changelog and direct CDN URLs.
//
//   - Rinkhals releases come from the GitHub releases API on this repo. We
//     filter to non-prereleases by default; the UI can opt in to seeing test
//     builds with ?include_prerelease=1.
//
// Both feeds are cached aggressively to stay well under the unauthenticated
// 60-requests-per-hour ceiling. The Anycubic manifest is on raw.github which
// isn't rate-limited, so a 6-hour cache there is cheap; the Rinkhals releases
// listing uses the api.github.com endpoint, capped at 30 minutes.

const (
	firmwareManifestBase   = "https://raw.githubusercontent.com/rinkhals-community/Rinkhals.Firmwares/main/manifests-anycubic"
	rinkhalsReleasesAPI    = "https://api.github.com/repos/rinkhals-community/Rinkhals/releases?per_page=10"
	rinkhalsReleasesWebURL = "https://github.com/rinkhals-community/Rinkhals/releases/tag/"

	firmwareAnycubicTTL = 6 * time.Hour
	firmwareRinkhalsTTL = 30 * time.Minute
	firmwareStatusTTL   = 30 * time.Minute
)

// FirmwareStatus is the lightweight summary the dashboard chip and Manage
// Rinkhals page read. Always includes current installed versions, plus the
// resolved-from-upstream latest values and computed availability flags.
type FirmwareStatus struct {
	ModelCode               string    `json:"model_code"`
	ModelName               string    `json:"model_name"`
	CurrentFirmware         string    `json:"current_firmware"`
	CurrentRinkhals         string    `json:"current_rinkhals"`
	LatestFirmware          string    `json:"latest_firmware,omitempty"`
	LatestRinkhals          string    `json:"latest_rinkhals,omitempty"`
	FirmwareUpdateAvailable bool      `json:"firmware_update_available"`
	RinkhalsUpdateAvailable bool      `json:"rinkhals_update_available"`
	FetchedAt               time.Time `json:"fetched_at"`
	Notice                  string    `json:"notice,omitempty"`
}

// AnycubicFirmwareVersion mirrors one entry in the model's manifest. We expose
// the raw upstream date as a unix timestamp; the UI formats it for display.
// `Current` is set when the version matches the printer's running firmware.
type AnycubicFirmwareVersion struct {
	Version string `json:"version"`
	Date    int64  `json:"date"`
	Changes string `json:"changes,omitempty"`
	MD5     string `json:"md5,omitempty"`
	URL     string `json:"url"`
	Current bool   `json:"current"`
}

// AnycubicCatalog is the wire shape of /api/firmware/anycubic. Versions come
// back newest-first regardless of how the upstream manifest orders them.
type AnycubicCatalog struct {
	ModelCode string                    `json:"model_code"`
	ModelName string                    `json:"model_name"`
	Versions  []AnycubicFirmwareVersion `json:"versions"`
	FetchedAt time.Time                 `json:"fetched_at"`
	Notice    string                    `json:"notice,omitempty"`
}

// RinkhalsRelease mirrors one GitHub release with the slice of fields the UI
// actually consumes. Body is the full markdown release-notes body so the
// release-notes modal can render it client-side without an extra round-trip.
// AssetURL/AssetSize point at the update-*.swu for the current printer's
// model group; absent when no matching asset exists.
type RinkhalsRelease struct {
	Tag          string `json:"tag"`
	Name         string `json:"name"`
	PublishedAt  string `json:"published_at"`
	URL          string `json:"url"`
	Body         string `json:"body"`
	IsPrerelease bool   `json:"is_prerelease"`
	Current      bool   `json:"current"`
	AssetURL     string `json:"asset_url,omitempty"`
	AssetSize    int64  `json:"asset_size,omitempty"`
}

// RinkhalsCatalog is the wire shape of /api/firmware/rinkhals.
type RinkhalsCatalog struct {
	Releases  []RinkhalsRelease `json:"releases"`
	FetchedAt time.Time         `json:"fetched_at"`
}

// Cache state. Data mutex held only briefly to swap the cached pointer; the
// build mutexes serialise the network fetches so concurrent reads don't all
// trigger an upstream round-trip when the cache expires.
var (
	firmwareStatusDataMu    sync.Mutex
	firmwareStatusBuildMu   sync.Mutex
	firmwareStatusCached    *FirmwareStatus
	firmwareStatusCachedAt  time.Time

	firmwareAnycubicDataMu   sync.Mutex
	firmwareAnycubicBuildMu  sync.Mutex
	firmwareAnycubicCached   = map[string]*AnycubicCatalog{} // keyed by model code
	firmwareAnycubicCachedAt = map[string]time.Time{}

	firmwareRinkhalsDataMu   sync.Mutex
	firmwareRinkhalsBuildMu  sync.Mutex
	firmwareRinkhalsCached   *RinkhalsCatalog
	firmwareRinkhalsCachedAt time.Time
)

// --- environment helpers ---

func modelDisplayName(code string) string {
	switch strings.ToUpper(code) {
	case "K2P":
		return "Anycubic Kobra 2 Pro"
	case "K3":
		return "Anycubic Kobra 3"
	case "K3V2":
		return "Anycubic Kobra 3 V2"
	case "K3M":
		return "Anycubic Kobra 3 Max"
	case "KS1":
		return "Anycubic Kobra S1"
	case "KS1M":
		return "Anycubic Kobra S1 Max"
	}
	return code
}

// currentKobraVersion reads the running stock firmware version. tools.sh
// exports KOBRA_VERSION (sourced from /useremain/dev/version); if we weren't
// launched with that env, fall back to reading the file directly so callers
// from a fresh shell still work.
func currentKobraVersion() string {
	if v := os.Getenv("KOBRA_VERSION"); v != "" {
		return v
	}
	if data, err := os.ReadFile("/useremain/dev/version"); err == nil {
		return strings.TrimSpace(string(data))
	}
	return ""
}

// currentRinkhalsVersion reads the running Rinkhals release tag the same way:
// prefer the env var, fall back to the .version file under .current.
func currentRinkhalsVersion() string {
	if v := os.Getenv("RINKHALS_VERSION"); v != "" {
		return v
	}
	if data, err := os.ReadFile("/useremain/rinkhals/.current/.version"); err == nil {
		return strings.TrimSpace(string(data))
	}
	// Final fallback - shell out so we follow the same resolution path tools.sh
	// uses. This covers fresh-process scenarios where neither the env nor the
	// file is available for whatever reason.
	out, err := exec.Command("sh", "-c", ". "+toolsSh+" >/dev/null 2>&1; printf %s \"$RINKHALS_VERSION\"").Output()
	if err == nil {
		return strings.TrimSpace(string(out))
	}
	return ""
}

// --- Anycubic catalog ---

type anycubicManifest struct {
	Firmwares []AnycubicFirmwareVersion `json:"firmwares"`
}

func fetchAnycubicCatalog(modelCode string) (*AnycubicCatalog, error) {
	code := strings.ToUpper(strings.TrimSpace(modelCode))
	if code == "" {
		return nil, fmt.Errorf("model code required")
	}
	url := fmt.Sprintf("%s/manifest-%s.json", firmwareManifestBase, strings.ToLower(code))
	var manifest anycubicManifest
	if err := httpGetJSON(url, &manifest); err != nil {
		return nil, err
	}
	current := currentKobraVersion()
	versions := make([]AnycubicFirmwareVersion, 0, len(manifest.Firmwares))
	for _, f := range manifest.Firmwares {
		f.Current = (f.Version != "" && f.Version == current)
		versions = append(versions, f)
	}
	// Newest first regardless of upstream ordering.
	sortVersionsNewestFirst(versions)
	return &AnycubicCatalog{
		ModelCode: code,
		ModelName: modelDisplayName(code),
		Versions:  versions,
		FetchedAt: time.Now().UTC(),
	}, nil
}

// compareVersionsDesc returns true when `a` should sort before `b` (i.e. a is
// "newer"). We compare component-by-component as integers when both sides
// parse, falling back to lexical comparison when they don't. Anycubic uses
// dotted four-component versions like "2.7.2.1" or "1.4.0", and the manifest's
// `date` field is upload-to-CDN timestamp which doesn't always track release
// order - so we sort on the version string instead.
func compareVersionsDesc(a, b string) bool {
	pa := strings.Split(a, ".")
	pb := strings.Split(b, ".")
	for i := 0; i < len(pa) || i < len(pb); i++ {
		var ai, bi int
		var aok, bok bool
		if i < len(pa) {
			_, err := fmt.Sscanf(pa[i], "%d", &ai)
			aok = err == nil
		}
		if i < len(pb) {
			_, err := fmt.Sscanf(pb[i], "%d", &bi)
			bok = err == nil
		}
		if aok && bok {
			if ai != bi {
				return ai > bi
			}
			continue
		}
		// One side ran out of components, or one side wasn't numeric. Compare
		// the surviving component(s) lexically; treat missing as less-than.
		var as, bs string
		if i < len(pa) {
			as = pa[i]
		}
		if i < len(pb) {
			bs = pb[i]
		}
		if as != bs {
			return as > bs
		}
	}
	return false
}

func sortVersionsNewestFirst(v []AnycubicFirmwareVersion) {
	// Simple insertion sort. Version counts per model are small (typically <30)
	// so this is fine and avoids importing sort just for one call.
	for i := 1; i < len(v); i++ {
		j := i
		for j > 0 && compareVersionsDesc(v[j].Version, v[j-1].Version) {
			v[j], v[j-1] = v[j-1], v[j]
			j--
		}
	}
}

func getAnycubicCatalog(modelCode string, force bool) (*AnycubicCatalog, error) {
	code := strings.ToUpper(strings.TrimSpace(modelCode))

	firmwareAnycubicDataMu.Lock()
	data, ok := firmwareAnycubicCached[code]
	stamp := firmwareAnycubicCachedAt[code]
	firmwareAnycubicDataMu.Unlock()
	if !force && ok && time.Since(stamp) < firmwareAnycubicTTL {
		return data, nil
	}

	firmwareAnycubicBuildMu.Lock()
	defer firmwareAnycubicBuildMu.Unlock()

	firmwareAnycubicDataMu.Lock()
	data, ok = firmwareAnycubicCached[code]
	stamp = firmwareAnycubicCachedAt[code]
	firmwareAnycubicDataMu.Unlock()
	if !force && ok && time.Since(stamp) < firmwareAnycubicTTL {
		return data, nil
	}

	fresh, err := fetchAnycubicCatalog(code)
	if err != nil {
		if data != nil {
			return data, err // serve stale on transient failure
		}
		return nil, err
	}
	firmwareAnycubicDataMu.Lock()
	firmwareAnycubicCached[code] = fresh
	firmwareAnycubicCachedAt[code] = time.Now()
	firmwareAnycubicDataMu.Unlock()
	return fresh, nil
}

// --- Rinkhals releases catalog ---

type ghReleaseEntry struct {
	TagName     string           `json:"tag_name"`
	Name        string           `json:"name"`
	Body        string           `json:"body"`
	PublishedAt string           `json:"published_at"`
	HTMLURL     string           `json:"html_url"`
	Prerelease  bool             `json:"prerelease"`
	Draft       bool             `json:"draft"`
	Assets      []ghReleaseAsset `json:"assets"`
}

func fetchRinkhalsCatalog() (*RinkhalsCatalog, error) {
	var raw []ghReleaseEntry
	if err := httpGetJSON(rinkhalsReleasesAPI, &raw); err != nil {
		return nil, err
	}

	// Resolve current model and asset group so we can pick the right SWU per
	// release to surface as the download artifact.
	model := currentModelCode()
	group, _ := modelToAssetGroup(model)
	currentTag := currentRinkhalsVersion()

	releases := make([]RinkhalsRelease, 0, len(raw))
	for _, r := range raw {
		if r.Draft {
			continue
		}
		entry := RinkhalsRelease{
			Tag:          r.TagName,
			Name:         r.Name,
			PublishedAt:  r.PublishedAt,
			URL:          r.HTMLURL,
			Body:         r.Body,
			IsPrerelease: r.Prerelease,
			Current:      r.TagName == currentTag,
		}
		// Pick the update-<group>.swu asset for this printer. Installers and
		// tools zips are surfaced separately when we add the install flow.
		if group != "" {
			needle := "update-" + group + ".swu"
			for _, a := range r.Assets {
				if a.Name == needle {
					entry.AssetURL = a.BrowserDownloadURL
					entry.AssetSize = a.Size
					break
				}
			}
		}
		releases = append(releases, entry)
	}

	return &RinkhalsCatalog{
		Releases:  releases,
		FetchedAt: time.Now().UTC(),
	}, nil
}

func getRinkhalsCatalog(force bool) (*RinkhalsCatalog, error) {
	firmwareRinkhalsDataMu.Lock()
	data, stamp := firmwareRinkhalsCached, firmwareRinkhalsCachedAt
	firmwareRinkhalsDataMu.Unlock()
	if !force && data != nil && time.Since(stamp) < firmwareRinkhalsTTL {
		return data, nil
	}

	firmwareRinkhalsBuildMu.Lock()
	defer firmwareRinkhalsBuildMu.Unlock()

	firmwareRinkhalsDataMu.Lock()
	data, stamp = firmwareRinkhalsCached, firmwareRinkhalsCachedAt
	firmwareRinkhalsDataMu.Unlock()
	if !force && data != nil && time.Since(stamp) < firmwareRinkhalsTTL {
		return data, nil
	}

	fresh, err := fetchRinkhalsCatalog()
	if err != nil {
		if data != nil {
			return data, err
		}
		return nil, err
	}
	firmwareRinkhalsDataMu.Lock()
	firmwareRinkhalsCached = fresh
	firmwareRinkhalsCachedAt = time.Now()
	firmwareRinkhalsDataMu.Unlock()
	return fresh, nil
}

// --- combined status (the lightweight summary the dashboard uses) ---

func buildFirmwareStatus(force bool) (*FirmwareStatus, error) {
	model := currentModelCode()
	status := &FirmwareStatus{
		ModelCode:       model,
		ModelName:       modelDisplayName(model),
		CurrentFirmware: currentKobraVersion(),
		CurrentRinkhals: currentRinkhalsVersion(),
		FetchedAt:       time.Now().UTC(),
	}

	if anycubic, err := getAnycubicCatalog(model, force); err == nil && len(anycubic.Versions) > 0 {
		// Versions are newest-first from sortVersionsNewestFirst.
		status.LatestFirmware = anycubic.Versions[0].Version
		// Only flag an update when the catalog's newest is strictly higher than
		// what's installed. If the printer is on a build newer than the
		// community-curated manifest knows about (common when Anycubic ships a
		// firmware before the manifest catches up), no update is "available".
		status.FirmwareUpdateAvailable = status.LatestFirmware != "" &&
			status.CurrentFirmware != "" &&
			compareVersionsDesc(status.LatestFirmware, status.CurrentFirmware)
	} else if err != nil {
		status.Notice = "Could not reach the Anycubic firmware catalog"
	}

	if rinkhals, err := getRinkhalsCatalog(force); err == nil {
		// First non-prerelease entry is the latest stable. As with the Anycubic
		// side, only flag an update when "latest" is strictly higher than what's
		// installed - someone running a dev/test build (e.g. "20260601_01_test_webui")
		// shouldn't see "update available" pointing at "20260601_01" when the
		// dated prefix is the same release in a different channel.
		for _, r := range rinkhals.Releases {
			if !r.IsPrerelease {
				status.LatestRinkhals = r.Tag
				status.RinkhalsUpdateAvailable = r.Tag != "" &&
					status.CurrentRinkhals != "" &&
					compareVersionsDesc(r.Tag, status.CurrentRinkhals)
				break
			}
		}
	} else if err != nil {
		if status.Notice == "" {
			status.Notice = "Could not reach the Rinkhals releases feed"
		}
	}

	return status, nil
}

func getFirmwareStatus(force bool) (*FirmwareStatus, error) {
	firmwareStatusDataMu.Lock()
	data, stamp := firmwareStatusCached, firmwareStatusCachedAt
	firmwareStatusDataMu.Unlock()
	if !force && data != nil && time.Since(stamp) < firmwareStatusTTL {
		return data, nil
	}

	firmwareStatusBuildMu.Lock()
	defer firmwareStatusBuildMu.Unlock()

	firmwareStatusDataMu.Lock()
	data, stamp = firmwareStatusCached, firmwareStatusCachedAt
	firmwareStatusDataMu.Unlock()
	if !force && data != nil && time.Since(stamp) < firmwareStatusTTL {
		return data, nil
	}

	fresh, err := buildFirmwareStatus(force)
	if err != nil && data != nil {
		return data, err
	}
	if fresh == nil {
		return data, err
	}
	firmwareStatusDataMu.Lock()
	firmwareStatusCached = fresh
	firmwareStatusCachedAt = time.Now()
	firmwareStatusDataMu.Unlock()
	return fresh, nil
}

func invalidateFirmwareCaches() {
	firmwareStatusDataMu.Lock()
	firmwareStatusCached = nil
	firmwareStatusCachedAt = time.Time{}
	firmwareStatusDataMu.Unlock()

	firmwareAnycubicDataMu.Lock()
	firmwareAnycubicCached = map[string]*AnycubicCatalog{}
	firmwareAnycubicCachedAt = map[string]time.Time{}
	firmwareAnycubicDataMu.Unlock()

	firmwareRinkhalsDataMu.Lock()
	firmwareRinkhalsCached = nil
	firmwareRinkhalsCachedAt = time.Time{}
	firmwareRinkhalsDataMu.Unlock()
}

// --- HTTP handlers ---

func handleFirmwareStatus(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "GET, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	force := r.URL.Query().Get("refresh") == "1"
	status, err := getFirmwareStatus(force)
	if err != nil && status == nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	if err != nil {
		w.Header().Set("X-Firmware-Warning", err.Error())
	}
	json.NewEncoder(w).Encode(status)
}

func handleFirmwareAnycubic(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "GET, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	force := r.URL.Query().Get("refresh") == "1"
	model := r.URL.Query().Get("model")
	if model == "" {
		model = currentModelCode()
	}
	catalog, err := getAnycubicCatalog(model, force)
	if err != nil && catalog == nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	json.NewEncoder(w).Encode(catalog)
}

func handleFirmwareRinkhals(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "GET, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	force := r.URL.Query().Get("refresh") == "1"
	includePrerelease := r.URL.Query().Get("include_prerelease") == "1"

	catalog, err := getRinkhalsCatalog(force)
	if err != nil && catalog == nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	// Filter prereleases out unless explicitly requested. The cache always
	// stores the full list so toggling the flag doesn't trigger a refetch.
	if !includePrerelease {
		filtered := make([]RinkhalsRelease, 0, len(catalog.Releases))
		for _, r := range catalog.Releases {
			if !r.IsPrerelease {
				filtered = append(filtered, r)
			}
		}
		catalog = &RinkhalsCatalog{
			Releases:  filtered,
			FetchedAt: catalog.FetchedAt,
		}
	}
	json.NewEncoder(w).Encode(catalog)
}

func handleFirmwareRefresh(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "POST, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	invalidateFirmwareCaches()
	status, _ := getFirmwareStatus(true)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": true,
		"status":  status,
	})
}
