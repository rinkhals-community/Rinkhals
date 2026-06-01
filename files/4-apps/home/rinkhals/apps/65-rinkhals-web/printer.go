package main

import (
	"encoding/json"
	"io"
	"net/http"
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

// fetchPrinterState consults Moonraker on localhost:7125 and translates its
// print_stats.state into our wire shape. An unreachable Moonraker is treated
// as "offline" with CanInstall=true: the most common cause is that the
// Moonraker app is stopped, not that a print is silently in progress without
// any visible UI to report it.
func fetchPrinterState() *PrinterState {
	client := &http.Client{Timeout: 1500 * time.Millisecond}
	resp, err := client.Get("http://localhost:7125/printer/objects/query?print_stats")
	if err != nil {
		return &PrinterState{State: "offline", CanInstall: true}
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
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
