package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// Firmware install: a unified flow that handles both Anycubic stock firmware
// SWUs and Rinkhals release SWUs. The mechanism on the printer is the same in
// both cases:
//
//   1. Download the .swu to /useremain/update.swu
//   2. unzip -P <model-password> -d /useremain (yields /useremain/update_swu/)
//   3. tar -xzf /useremain/update_swu/setup.tar.gz -C /useremain/update_swu
//   4. Patch the inner update.sh to suppress self-cleanup and the final reboot
//      (we want to control rebooting ourselves so the UI can report status)
//   5. Run /useremain/update_swu/update.sh
//   6. Re-append start.sh.patch to /userdata/app/gk/start.sh if Rinkhals's
//      loader is missing (defensive - only matters when an Anycubic install
//      wiped /userdata, which shouldn't happen but we double-check)
//   7. Touch /useremain/rinkhals/.reboot-marker and reboot
//
// This mirrors what the Python touch-panel UI (common.py extract_swu/install_swu)
// already does today. Keeping the two paths byte-identical is intentional: the
// printer doesn't care which UI triggered the install.
//
// Concurrency: only one install runs at a time. A mutex guards the state
// machine; subsequent /install calls return 409.
//
// Safety model: the WebUI's whole purpose is to let users do everything
// without SSH or the touch panel, so install is a first-class action. Guards:
//
//   - Basic auth on every endpoint (same as the rest of /api/*)
//   - Two-step preflight + commit, with single-use 60s-TTL install_id
//   - URL allowlist (Rinkhals = our GitHub release attachments,
//     Anycubic = cdn.cloud-universe.anycubic.com)
//   - Print-state gate via fetchPrinterState before minting a token
//   - Concurrency mutex (second install request returns 409)
//   - Optional dry-run flag in the commit body: downloads and extracts but
//     stops before update.sh, for users who want to verify the download path
//     before committing to a real flash
//
// The TWO-STEP confirm:
//   POST /api/firmware/install/preflight  -> { install_id, expires_at, ... }
//   POST /api/firmware/install/commit     -> starts the install
// install_id has a 60s TTL and is consumed on commit (single-use). This
// prevents stale UI tabs from triggering an install on a long-stale page.

// Install state vocabulary the UI reads.
const (
	installStateIdle       = "idle"
	installStatePreparing  = "preparing"
	installStateDownload   = "downloading"
	installStateExtract    = "extracting"
	installStateInstalling = "installing"
	installStateRebooting  = "rebooting"
	installStateComplete   = "complete"
	installStateFailed     = "failed"
)

const (
	installURLPath     = "/useremain/update.swu"
	installExtractPath = "/useremain/update_swu"
	installLogPath     = "/useremain/rinkhals/install.log"
	preflightTTL       = 60 * time.Second
)

// In-memory install state, guarded by firmwareInstallMu. Held briefly: state
// transitions copy out, work happens against the copy, then re-acquired to
// publish updates.
type installRunState struct {
	State        string    `json:"state"`
	Source       string    `json:"source"` // "rinkhals" or "anycubic"
	Version      string    `json:"version"`
	AssetURL     string    `json:"asset_url"`
	DownloadPct  int       `json:"download_pct"`
	DownloadedMB float64   `json:"downloaded_mb"`
	TotalMB      float64   `json:"total_mb"`
	Message      string    `json:"message"`
	Error        string    `json:"error,omitempty"`
	StartedAt    time.Time `json:"started_at"`
	UpdatedAt    time.Time `json:"updated_at"`
	DryRun       bool      `json:"dry_run"`
	InstallID    string    `json:"install_id"`
}

var (
	firmwareInstallMu       sync.Mutex
	installCurrent  *installRunState
	installLog      []string        // ring buffer of log lines, capped
	installLogMax   = 500
	installWaiters  []chan struct{} // SSE subscribers; signalled on each update
	preflightTokens = map[string]*preflightToken{}
)

type preflightToken struct {
	Source    string
	Version   string
	AssetURL  string
	Sha256    string // optional, for asset verification
	ExpiresAt time.Time
	Compat    *compatibilityReport
}

// compatibilityReport explains whether installing the target SWU is safe given
// what's running. For Rinkhals SWUs this is always true. For Anycubic SWUs we
// check whether the current Rinkhals install has patches for the target stock
// firmware version - if not, Rinkhals will refuse to load on next boot and the
// user will be on stock until they install a compatible Rinkhals release.
type compatibilityReport struct {
	Compatible              bool     `json:"compatible"`
	Warnings                []string `json:"warnings"`
	RinkhalsPatchesForTarget bool    `json:"rinkhals_patches_for_target"`
	TargetVersion           string   `json:"target_version,omitempty"`
}

// --- helpers ---

func appendInstallLog(line string) {
	stamp := time.Now().Format("15:04:05")
	entry := stamp + " " + line
	installLog = append(installLog, entry)
	if len(installLog) > installLogMax {
		installLog = installLog[len(installLog)-installLogMax:]
	}
	// Mirror to the on-disk install.log so the touch-panel UI and any SSH
	// debugging see the same trace.
	if f, err := os.OpenFile(installLogPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644); err == nil {
		fmt.Fprintln(f, time.Now().Format(time.RFC3339), line)
		f.Close()
	}
	notifyWaiters()
}

func setInstallState(mutate func(*installRunState)) {
	if installCurrent == nil {
		return
	}
	mutate(installCurrent)
	installCurrent.UpdatedAt = time.Now()
	notifyWaiters()
}

func notifyWaiters() {
	for _, ch := range installWaiters {
		select {
		case ch <- struct{}{}:
		default:
		}
	}
}

func randomToken() string {
	b := make([]byte, 16)
	rand.Read(b)
	return hex.EncodeToString(b)
}

// validateAssetURL ensures the URL is from a trusted source for the given
// source category. Rinkhals SWUs must come from the rinkhals-community GitHub
// release attachments; Anycubic SWUs must come from Anycubic's CDN or the
// raw.githubusercontent.com manifest mirror's recorded URL. Anything else is
// rejected so we don't allow installing an arbitrary attacker-supplied SWU.
func validateAssetURL(source, assetURL string) error {
	u, err := url.Parse(assetURL)
	if err != nil || u.Scheme != "https" {
		return fmt.Errorf("asset_url must be an https URL")
	}
	host := strings.ToLower(u.Host)
	switch source {
	case "rinkhals":
		if host != "github.com" && host != "objects.githubusercontent.com" {
			return fmt.Errorf("rinkhals asset_url must come from github.com")
		}
		if host == "github.com" && !strings.HasPrefix(u.Path, "/rinkhals-community/Rinkhals/releases/download/") {
			return fmt.Errorf("rinkhals asset_url must point at this repo's release downloads")
		}
	case "anycubic":
		// Anycubic publishes via cdn.cloud-universe.anycubic.com. We don't
		// pin the path because the CDN paths look like opaque blob IDs.
		if !strings.HasSuffix(host, "cloud-universe.anycubic.com") {
			return fmt.Errorf("anycubic asset_url must come from cdn.cloud-universe.anycubic.com")
		}
	default:
		return fmt.Errorf("unknown source %q", source)
	}
	return nil
}

// --- compatibility check ---

// checkAnycubicCompatibility verifies that the currently-installed Rinkhals
// has patches for the target Anycubic firmware version. Rinkhals ships patches
// as files under opt/rinkhals/patches/ named like K3SysUi.KS1_2.7.2.1.* and
// gkapi.KS1_2.7.2.1.*. If the corresponding files don't exist, Rinkhals's
// start.sh will refuse to apply the loader and the printer will boot stock.
func checkAnycubicCompatibility(targetVersion string) *compatibilityReport {
	report := &compatibilityReport{
		TargetVersion: targetVersion,
		Compatible:    true,
	}
	model := currentModelCode()
	if model == "" || targetVersion == "" {
		report.Compatible = false
		report.Warnings = append(report.Warnings, "Could not determine current model or target version")
		return report
	}
	patchesDir := "/useremain/rinkhals/.current/opt/rinkhals/patches"
	entries, err := os.ReadDir(patchesDir)
	if err != nil {
		// No Rinkhals installed at all - installing a stock Anycubic firmware
		// is fine in that case (there's nothing to be broken).
		report.RinkhalsPatchesForTarget = true
		return report
	}
	needle := fmt.Sprintf("%s_%s", model, targetVersion)
	for _, e := range entries {
		if strings.Contains(e.Name(), needle) {
			report.RinkhalsPatchesForTarget = true
			return report
		}
	}
	report.RinkhalsPatchesForTarget = false
	report.Compatible = false
	report.Warnings = append(report.Warnings, fmt.Sprintf(
		"The currently-installed Rinkhals does not include patches for %s firmware %s. "+
			"After this install completes, Rinkhals will not start on next boot - the printer "+
			"will run stock Anycubic firmware until you install a Rinkhals release that ships "+
			"patches for %s. Make sure you have a compatible Rinkhals release ready to install afterward.",
		model, targetVersion, targetVersion))
	return report
}

// --- HTTP: preflight ---

type preflightRequest struct {
	Source   string `json:"source"`
	Version  string `json:"version"`
	AssetURL string `json:"asset_url"`
}

type preflightResponse struct {
	InstallID     string               `json:"install_id"`
	ExpiresAt     time.Time            `json:"expires_at"`
	Source        string               `json:"source"`
	Version       string               `json:"version"`
	Compatibility *compatibilityReport `json:"compatibility,omitempty"`
}

func handleInstallPreflight(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "POST, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req preflightRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}
	if req.Source != "rinkhals" && req.Source != "anycubic" {
		http.Error(w, "source must be 'rinkhals' or 'anycubic'", http.StatusBadRequest)
		return
	}
	if req.Version == "" || req.AssetURL == "" {
		http.Error(w, "version and asset_url are required", http.StatusBadRequest)
		return
	}
	if err := validateAssetURL(req.Source, req.AssetURL); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	// Print-state gate: don't even mint a token if a print is running.
	if state := fetchPrinterState(); !state.CanInstall {
		http.Error(w, fmt.Sprintf("Printer is busy: %s", state.Reason), http.StatusConflict)
		return
	}

	token := &preflightToken{
		Source:    req.Source,
		Version:   req.Version,
		AssetURL:  req.AssetURL,
		ExpiresAt: time.Now().Add(preflightTTL),
	}
	if req.Source == "anycubic" {
		token.Compat = checkAnycubicCompatibility(req.Version)
	} else {
		token.Compat = &compatibilityReport{Compatible: true}
	}

	id := randomToken()

	firmwareInstallMu.Lock()
	preflightTokens[id] = token
	// Garbage-collect expired tokens lazily.
	for k, t := range preflightTokens {
		if time.Now().After(t.ExpiresAt) {
			delete(preflightTokens, k)
		}
	}
	firmwareInstallMu.Unlock()

	json.NewEncoder(w).Encode(preflightResponse{
		InstallID:     id,
		ExpiresAt:     token.ExpiresAt,
		Source:        req.Source,
		Version:       req.Version,
		Compatibility: token.Compat,
	})
}

// --- HTTP: commit ---

type commitRequest struct {
	InstallID string `json:"install_id"`
	DryRun    bool   `json:"dry_run"`
}

func handleInstallCommit(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "POST, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req commitRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	firmwareInstallMu.Lock()
	if installCurrent != nil && installCurrent.State != installStateIdle &&
		installCurrent.State != installStateComplete && installCurrent.State != installStateFailed {
		firmwareInstallMu.Unlock()
		http.Error(w, "An install is already in progress", http.StatusConflict)
		return
	}
	token, ok := preflightTokens[req.InstallID]
	if !ok {
		firmwareInstallMu.Unlock()
		http.Error(w, "Unknown or expired install_id - call preflight again", http.StatusBadRequest)
		return
	}
	if time.Now().After(token.ExpiresAt) {
		delete(preflightTokens, req.InstallID)
		firmwareInstallMu.Unlock()
		http.Error(w, "install_id expired - call preflight again", http.StatusBadRequest)
		return
	}
	delete(preflightTokens, req.InstallID)

	// dry_run is an opt-in verification mode: downloads and extracts the SWU
	// but stops short of running update.sh + reboot. Useful for sanity-checking
	// the download path and SWU integrity. Default is false - the user clicked
	// "Confirm install" in the UI, they get a real flash.
	dryRun := req.DryRun

	// Reset state, clear ring buffer.
	installCurrent = &installRunState{
		State:     installStatePreparing,
		Source:    token.Source,
		Version:   token.Version,
		AssetURL:  token.AssetURL,
		DryRun:    dryRun,
		StartedAt: time.Now(),
		UpdatedAt: time.Now(),
		InstallID: req.InstallID,
		Message:   "Preparing install",
	}
	installLog = installLog[:0]
	firmwareInstallMu.Unlock()

	go runInstall(token, dryRun)

	json.NewEncoder(w).Encode(map[string]interface{}{
		"started":    true,
		"install_id": req.InstallID,
		"dry_run":    dryRun,
	})
}

// --- HTTP: state + progress SSE ---

func handleInstallState(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "GET, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	firmwareInstallMu.Lock()
	defer firmwareInstallMu.Unlock()
	resp := map[string]interface{}{
		"state": installStateIdle,
		"log":   installLog,
	}
	if installCurrent != nil {
		resp["state"] = installCurrent.State
		resp["run"] = installCurrent
	}
	json.NewEncoder(w).Encode(resp)
}

func handleInstallProgress(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	// SSE setup. No JSON content type here - text/event-stream.
	h := w.Header()
	h.Set("Content-Type", "text/event-stream")
	h.Set("Cache-Control", "no-cache")
	h.Set("Connection", "keep-alive")
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "Streaming unsupported", http.StatusInternalServerError)
		return
	}

	ch := make(chan struct{}, 4)
	firmwareInstallMu.Lock()
	installWaiters = append(installWaiters, ch)
	firmwareInstallMu.Unlock()
	defer func() {
		firmwareInstallMu.Lock()
		for i, w := range installWaiters {
			if w == ch {
				installWaiters = append(installWaiters[:i], installWaiters[i+1:]...)
				break
			}
		}
		firmwareInstallMu.Unlock()
	}()

	send := func() {
		firmwareInstallMu.Lock()
		payload := map[string]interface{}{
			"state": installStateIdle,
			"log":   append([]string{}, installLog...),
		}
		if installCurrent != nil {
			payload["state"] = installCurrent.State
			payload["run"] = installCurrent
		}
		firmwareInstallMu.Unlock()
		buf, _ := json.Marshal(payload)
		fmt.Fprintf(w, "data: %s\n\n", buf)
		flusher.Flush()
	}

	// Initial snapshot so the UI sees current state immediately.
	send()

	ctx := r.Context()
	heartbeat := time.NewTicker(15 * time.Second)
	defer heartbeat.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ch:
			send()
		case <-heartbeat.C:
			fmt.Fprintf(w, ": keepalive\n\n")
			flusher.Flush()
		}
	}
}

// --- install runner ---

func runInstall(token *preflightToken, dryRun bool) {
	defer func() {
		if rec := recover(); rec != nil {
			appendInstallLog(fmt.Sprintf("PANIC: %v", rec))
			firmwareInstallMu.Lock()
			setInstallState(func(s *installRunState) {
				s.State = installStateFailed
				s.Error = fmt.Sprintf("internal error: %v", rec)
			})
			firmwareInstallMu.Unlock()
		}
	}()

	appendInstallLog(fmt.Sprintf("Install starting: source=%s version=%s dry_run=%t", token.Source, token.Version, dryRun))

	// --- 1. Download ---
	firmwareInstallMu.Lock()
	setInstallState(func(s *installRunState) {
		s.State = installStateDownload
		s.Message = "Downloading SWU"
	})
	firmwareInstallMu.Unlock()

	if err := downloadSWU(token.AssetURL, installURLPath); err != nil {
		failInstall("Download failed", err)
		return
	}
	appendInstallLog("Download complete")

	// --- 2. Extract ---
	firmwareInstallMu.Lock()
	setInstallState(func(s *installRunState) {
		s.State = installStateExtract
		s.Message = "Extracting SWU"
	})
	firmwareInstallMu.Unlock()

	if err := extractSWU(installURLPath); err != nil {
		failInstall("Extract failed", err)
		return
	}
	appendInstallLog("Extract complete")

	if dryRun {
		appendInstallLog("Dry-run requested: stopping before update.sh / reboot")
		firmwareInstallMu.Lock()
		setInstallState(func(s *installRunState) {
			s.State = installStateComplete
			s.Message = "Dry-run complete - SWU downloaded and extracted but not applied"
		})
		firmwareInstallMu.Unlock()
		return
	}

	// --- 3. Patch update.sh to suppress self-cleanup + reboot ---
	if err := patchUpdateScript(); err != nil {
		failInstall("Patching update.sh failed", err)
		return
	}
	appendInstallLog("update.sh patched (suppressed self-cleanup + reboot)")

	// --- 4. Install ---
	firmwareInstallMu.Lock()
	setInstallState(func(s *installRunState) {
		s.State = installStateInstalling
		s.Message = "Running update.sh"
	})
	firmwareInstallMu.Unlock()

	if err := runUpdateScript(); err != nil {
		failInstall("update.sh failed", err)
		return
	}
	appendInstallLog("update.sh finished")

	// --- 5. Defensive: re-append start.sh patch if missing ---
	// Anycubic SWUs replace /app/ but not /userdata/, so the patch should
	// still be there. Re-checking matches what the Python touch-panel UI does.
	if err := ensureStartShPatch(); err != nil {
		appendInstallLog(fmt.Sprintf("Warning: could not re-apply start.sh patch: %v", err))
	}

	// --- 6. Set reboot marker and reboot ---
	if err := os.MkdirAll("/useremain/rinkhals", 0755); err == nil {
		if f, err := os.Create("/useremain/rinkhals/.reboot-marker"); err == nil {
			f.Close()
		}
	}

	firmwareInstallMu.Lock()
	setInstallState(func(s *installRunState) {
		s.State = installStateRebooting
		s.Message = "Rebooting now - portal will be back online in about a minute"
	})
	firmwareInstallMu.Unlock()
	appendInstallLog("Rebooting")

	// Give SSE subscribers a moment to receive the rebooting state before the
	// kernel cuts us off.
	time.Sleep(1 * time.Second)
	exec.Command("sync").Run()
	exec.Command("reboot").Run()
}

func failInstall(message string, err error) {
	appendInstallLog(fmt.Sprintf("%s: %v", message, err))
	firmwareInstallMu.Lock()
	setInstallState(func(s *installRunState) {
		s.State = installStateFailed
		s.Error = fmt.Sprintf("%s: %v", message, err)
	})
	firmwareInstallMu.Unlock()
}

// --- step implementations ---

func downloadSWU(assetURL, target string) error {
	req, err := http.NewRequest("GET", assetURL, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", "RinkhalsWeb/install")

	client := &http.Client{Timeout: 30 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	totalBytes := resp.ContentLength
	totalMB := 0.0
	if totalBytes > 0 {
		totalMB = float64(totalBytes) / (1024 * 1024)
	}

	if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
		return err
	}
	f, err := os.Create(target)
	if err != nil {
		return err
	}
	defer f.Close()

	hash := sha256.New()
	buf := make([]byte, 64*1024)
	var downloaded int64
	lastUpdate := time.Now()
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := f.Write(buf[:n]); werr != nil {
				return werr
			}
			hash.Write(buf[:n])
			downloaded += int64(n)
			// Throttle progress updates to ~3/sec so we don't drown SSE.
			if time.Since(lastUpdate) > 300*time.Millisecond {
				lastUpdate = time.Now()
				pct := 0
				if totalBytes > 0 {
					pct = int(downloaded * 100 / totalBytes)
				}
				downMB := float64(downloaded) / (1024 * 1024)
				firmwareInstallMu.Lock()
				setInstallState(func(s *installRunState) {
					s.DownloadPct = pct
					s.DownloadedMB = downMB
					s.TotalMB = totalMB
					s.Message = fmt.Sprintf("Downloading: %d%% (%.1f / %.1f MB)", pct, downMB, totalMB)
				})
				firmwareInstallMu.Unlock()
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			return rerr
		}
	}

	firmwareInstallMu.Lock()
	setInstallState(func(s *installRunState) {
		s.DownloadPct = 100
		s.DownloadedMB = float64(downloaded) / (1024 * 1024)
		if totalMB > 0 {
			s.TotalMB = totalMB
		} else {
			s.TotalMB = s.DownloadedMB
		}
		s.Message = fmt.Sprintf("Downloaded %.1f MB (sha256 %s)", s.DownloadedMB, hex.EncodeToString(hash.Sum(nil))[:8])
	})
	firmwareInstallMu.Unlock()
	return nil
}

// extractSWU mirrors `tools.sh install_swu` up through the tar extraction
// step. We don't shell out to install_swu because it would also run the
// SWU's update.sh; we want a separate patch step in between.
func extractSWU(swuPath string) error {
	password := lookupSWUPassword(currentModelCode())
	if password == "" {
		return fmt.Errorf("no SWU password known for model %q", currentModelCode())
	}

	// Reset extract dir.
	exec.Command("rm", "-rf", installExtractPath).Run()
	if err := os.MkdirAll(installExtractPath, 0755); err != nil {
		return err
	}

	// unzip -P <pwd> swuPath -d /useremain  (the SWU expects to land directly
	// in /useremain because the ZIP contains a top-level update_swu/ directory)
	cmd := exec.Command("unzip", "-o", "-P", password, swuPath, "-d", "/useremain")
	cmd.Stdout = installLogWriter{}
	cmd.Stderr = installLogWriter{}
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("unzip: %w", err)
	}

	// MD5 verify if the SWU shipped one.
	if md5File := filepath.Join(installExtractPath, "setup.tar.gz.md5"); fileExists(md5File) {
		expected, _ := os.ReadFile(md5File)
		expectedHex := strings.TrimSpace(string(expected))
		actual, err := md5HexOfFile(filepath.Join(installExtractPath, "setup.tar.gz"))
		if err != nil {
			return fmt.Errorf("md5 check: %w", err)
		}
		if !strings.EqualFold(actual, expectedHex) {
			return fmt.Errorf("setup.tar.gz md5 mismatch (got %s, want %s)", actual, expectedHex)
		}
		appendInstallLog("setup.tar.gz md5 verified")
	}

	if fileExists(filepath.Join(installExtractPath, "setup.tar.gz")) {
		cmd := exec.Command("tar", "-xzf", filepath.Join(installExtractPath, "setup.tar.gz"), "-C", installExtractPath)
		cmd.Stdout = installLogWriter{}
		cmd.Stderr = installLogWriter{}
		if err := cmd.Run(); err != nil {
			return fmt.Errorf("tar: %w", err)
		}
	}

	// Remove the consumed .swu so a stale file doesn't trigger anything later.
	os.Remove(swuPath)
	return nil
}

// patchUpdateScript edits the inner update.sh to suppress self-cleanup of the
// .swu and to suppress the final `reboot` call. We want to drive rebooting
// ourselves so the SSE stream can announce the transition before the kernel
// cuts off the HTTP connection. Mirrors what common.py's install_swu() does.
func patchUpdateScript() error {
	scriptPath := filepath.Join(installExtractPath, "update.sh")
	data, err := os.ReadFile(scriptPath)
	if err != nil {
		return err
	}
	content := string(data)
	content = strings.ReplaceAll(content, "rm -f /useremain/update.swu", "echo skip-rm-useremain-update")
	content = strings.ReplaceAll(content, "rm -f $USB_PATH/update.swu", "echo skip-rm-usb-update")
	content = strings.ReplaceAll(content, "reboot", "echo skip-reboot")
	if err := os.WriteFile(scriptPath, []byte(content), 0755); err != nil {
		return err
	}
	return nil
}

func runUpdateScript() error {
	scriptPath := filepath.Join(installExtractPath, "update.sh")
	if err := os.Chmod(scriptPath, 0755); err != nil {
		return err
	}
	cmd := exec.Command("sh", scriptPath)
	cmd.Dir = installExtractPath
	cmd.Stdout = installLogWriter{}
	cmd.Stderr = installLogWriter{}
	return cmd.Run()
}

func ensureStartShPatch() error {
	startSh := "/userdata/app/gk/start.sh"
	if !fileExists(startSh) {
		return nil
	}
	data, err := os.ReadFile(startSh)
	if err != nil {
		return err
	}
	if strings.Contains(string(data), "Rinkhals/begin") {
		return nil
	}
	// Find the patch file in the freshly-installed Rinkhals tree.
	patchFile := "/useremain/rinkhals/start.sh.patch"
	if !fileExists(patchFile) {
		return fmt.Errorf("start.sh.patch not present after install")
	}
	patch, err := os.ReadFile(patchFile)
	if err != nil {
		return err
	}
	f, err := os.OpenFile(startSh, os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = f.Write(patch)
	if err == nil {
		appendInstallLog("Re-appended Rinkhals loader to /userdata/app/gk/start.sh")
	}
	return err
}

// --- small utilities ---

func lookupSWUPassword(model string) string {
	switch strings.ToUpper(model) {
	case "K2P", "K3", "K3V2":
		return "U2FsdGVkX19deTfqpXHZnB5GeyQ/dtlbHjkUnwgCi+w="
	case "KS1", "KS1M":
		return "U2FsdGVkX1+lG6cHmshPLI/LaQr9cZCjA8HZt6Y8qmbB7riY"
	case "K3M":
		return "4DKXtEGStWHpPgZm8Xna9qluzAI8VJzpOsEIgd8brTLiXs8fLSu3vRx8o7fMf4h6"
	}
	return ""
}

func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

// md5HexOfFile - lightweight md5 via the busybox md5sum binary, since the
// stdlib md5 import is fine but using the same tool the printer uses
// elsewhere keeps behaviour consistent with the Python reference.
func md5HexOfFile(path string) (string, error) {
	out, err := exec.Command("md5sum", path).Output()
	if err != nil {
		return "", err
	}
	fields := strings.Fields(string(out))
	if len(fields) == 0 {
		return "", fmt.Errorf("empty md5sum output")
	}
	return fields[0], nil
}

// installLogWriter routes subprocess stdout/stderr lines into the install log.
type installLogWriter struct{}

func (installLogWriter) Write(p []byte) (int, error) {
	for _, line := range strings.Split(strings.TrimRight(string(p), "\n"), "\n") {
		if line != "" {
			appendInstallLog(line)
		}
	}
	return len(p), nil
}
