package main

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
)

// PrinterState is the wire shape returned by /api/printer/state. The UI uses
// CanInstall to gate install / uninstall buttons across the portal (Apps,
// Firmware, etc.) so the same response shape drives every page.
type PrinterState struct {
	State      string `json:"state"`
	CanInstall bool   `json:"can_install"`
	Reason     string `json:"reason,omitempty"`
}

// Cache TTL for the printer-state query. Short enough that the UI feels live,
// long enough that multiple pages polling concurrently share one upstream
// Moonraker round-trip.
const printerStateCacheTTL = 2 * time.Second

var (
	printerStateMu       sync.Mutex
	printerStateCached   *PrinterState
	printerStateCachedAt time.Time
)

// Subset of Moonraker's /printer/objects/query?print_stats response. We only
// look at print_stats.state; the rest of the payload is ignored on parse.
type moonrakerPrintStatsResponse struct {
	Result struct {
		Status struct {
			PrintStats struct {
				State string `json:"state"`
			} `json:"print_stats"`
		} `json:"status"`
	} `json:"result"`
}

// Swapped out by tests.
var (
	printStatsURL        = "http://localhost:7125/printer/objects/query?print_stats"
	klipperRunsOnPrinter = klipperProcessRunning
)

// remoteKlipperReason is shown when no Klipper runs on the printer itself.
// The tunnel apps (tunneled-klipper, lan-tunneled-klipper) stop GoKlipper and
// run Klipper on another computer, so the printer's own Moonraker can't see a
// print it's driving, and an update's reboot would cut that print off.
const remoteKlipperReason = "Klipper isn't running on this printer, so a tunnel app may be printing from another computer"

// fetchPrinterState consults Moonraker on localhost:7125 and translates its
// print_stats.state into our wire shape. An unreachable Moonraker is treated
// as "offline" with CanInstall=true: the most common cause is that the
// Moonraker app is stopped, not that a print is silently in progress without
// any visible UI to report it.
//
// A Moonraker that answers but can't reach Klipper is different when no
// Klipper runs on the printer at all (neither GoKlipper nor Klippy): that's
// what the tunnel apps leave behind, and a print may be running elsewhere.
func fetchPrinterState() *PrinterState {
	client := &http.Client{Timeout: 1500 * time.Millisecond}
	resp, err := client.Get(printStatsURL)
	if err != nil {
		return &PrinterState{State: "offline", CanInstall: true}
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		if !klipperRunsOnPrinter() {
			return &PrinterState{State: "remote", CanInstall: false, Reason: remoteKlipperReason}
		}
		return &PrinterState{State: "offline", CanInstall: true}
	}
	body, _ := io.ReadAll(resp.Body)
	var parsed moonrakerPrintStatsResponse
	if err := json.Unmarshal(body, &parsed); err != nil {
		return &PrinterState{State: "unknown", CanInstall: true}
	}

	raw := parsed.Result.Status.PrintStats.State
	out := &PrinterState{State: raw, CanInstall: true}

	// Moonraker / Klipper state vocabulary -> our wire shape. The few states
	// where a write to /useremain (install or uninstall) would be dangerous
	// flip CanInstall to false; everything else (standby, complete, error,
	// offline) leaves it true.
	switch raw {
	case "printing":
		out.CanInstall = false
		out.Reason = "Printer is currently printing"
	case "paused":
		out.CanInstall = false
		out.Reason = "Printer is currently paused mid-print"
	case "pausing":
		out.CanInstall = false
		out.Reason = "Printer is pausing the print"
	case "cancelling":
		out.CanInstall = false
		out.Reason = "Printer is cancelling the print"
	case "complete", "cancelled", "standby", "":
		// Normalize all "not actively printing" states to standby. The UI
		// only really cares about standby vs busy; the verbose variants are
		// implementation detail of the Klipper print_stats state machine.
		out.State = "standby"
	}
	return out
}

func handlePrinterState(w http.ResponseWriter, r *http.Request) {
	if corsPreflight(w, r, "GET, OPTIONS") {
		return
	}
	writeJSONHeaders(w)
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Serve the cache if it's fresh; otherwise refresh under the lock.
	printerStateMu.Lock()
	if printerStateCached != nil && time.Since(printerStateCachedAt) < printerStateCacheTTL {
		cached := *printerStateCached
		printerStateMu.Unlock()
		json.NewEncoder(w).Encode(cached)
		return
	}
	printerStateMu.Unlock()

	state := fetchPrinterState()

	printerStateMu.Lock()
	printerStateCached = state
	printerStateCachedAt = time.Now()
	printerStateMu.Unlock()

	json.NewEncoder(w).Encode(state)
}

// klipperProcessRunning reports whether GoKlipper (gklib) or mainline Klippy
// runs on this printer.
func klipperProcessRunning() bool {
	if runtime.GOOS != "linux" {
		// Nothing to look at: don't block anything
		return true
	}
	_, found := findProcess(func(argv []string) bool { return isGoKlipper(argv) || isKlippy(argv) })
	return found
}

// findProcess returns the first process whose arguments match. It reads /proc
// rather than ps, whose busybox output is truncated, and the matchers look at
// the program itself, so a log viewer with "gklib.log" in its arguments
// doesn't count.
func findProcess(match func(argv []string) bool) (int, bool) {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return 0, false
	}
	for _, e := range entries {
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue
		}
		raw, err := os.ReadFile(filepath.Join("/proc", e.Name(), "cmdline"))
		if err != nil || len(raw) == 0 {
			continue
		}
		if match(strings.Split(strings.TrimRight(string(raw), "\x00"), "\x00")) {
			return pid, true
		}
	}
	return 0, false
}

// isGoKlipper matches "./gklib ...".
func isGoKlipper(argv []string) bool {
	return len(argv) > 0 && filepath.Base(argv[0]) == "gklib"
}

// isKlippy matches "python -m klippy ..." and "python .../klippy.py ...".
func isKlippy(argv []string) bool {
	for i := 1; i < len(argv); i++ {
		if argv[i] == "klippy" && argv[i-1] == "-m" {
			return true
		}
		if filepath.Base(argv[i]) == "klippy.py" {
			return true
		}
	}
	return false
}
