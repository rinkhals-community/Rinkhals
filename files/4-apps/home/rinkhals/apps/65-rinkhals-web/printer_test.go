package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func withPrinterState(t *testing.T, status int, body string, klipperLocal bool) *PrinterState {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()

	oldURL, oldCheck := printStatsURL, klipperRunsOnPrinter
	printStatsURL = srv.URL
	klipperRunsOnPrinter = func() bool { return klipperLocal }
	defer func() { printStatsURL, klipperRunsOnPrinter = oldURL, oldCheck }()

	return fetchPrinterState()
}

const klippyNotConnected = `{"error": {"code": 503, "message": "Klippy Host not connected"}}`

// The tunnel apps stop GoKlipper and drive the printer from another computer,
// so the printer's Moonraker can't see their prints: don't allow installs.
func TestNoKlipperOnPrinterBlocksInstalls(t *testing.T) {
	got := withPrinterState(t, http.StatusServiceUnavailable, klippyNotConnected, false)
	if got.State != "remote" || got.CanInstall || got.Reason == "" {
		t.Fatalf("got %+v, want state remote with installs blocked and a reason", got)
	}
}

// With GoKlipper or Klippy on the printer, a 503 is a restart or a startup,
// as before.
func TestKlipperStartingOnPrinterStillAllowsInstalls(t *testing.T) {
	got := withPrinterState(t, http.StatusServiceUnavailable, klippyNotConnected, true)
	if got.State != "offline" || !got.CanInstall {
		t.Fatalf("got %+v, want offline with installs allowed", got)
	}
}

func TestPrintingBlocksInstalls(t *testing.T) {
	got := withPrinterState(t, http.StatusOK, `{"result": {"status": {"print_stats": {"state": "printing"}}}}`, true)
	if got.State != "printing" || got.CanInstall {
		t.Fatalf("got %+v, want printing with installs blocked", got)
	}
}

func TestStandbyAllowsInstalls(t *testing.T) {
	got := withPrinterState(t, http.StatusOK, `{"result": {"status": {"print_stats": {"state": "complete"}}}}`, true)
	if got.State != "standby" || !got.CanInstall {
		t.Fatalf("got %+v, want standby with installs allowed", got)
	}
}

func TestKlipperCommandMatching(t *testing.T) {
	cases := []struct {
		argv      []string
		gk, klipy bool
	}{
		{[]string{"./gklib", "-a", "/tmp/unix_uds1", "rinkhals_gklib.cfg"}, true, false},
		{[]string{"/userdata/app/gk/gklib", "-a", "/tmp/unix_uds1"}, true, false},
		{[]string{"python", "-m", "klippy", "-a", "/tmp/unix_uds1"}, false, true},
		{[]string{"/usr/bin/python3", "/home/pi/klipper/klippy/klippy.py", "printer.cfg"}, false, true},
		{[]string{"tail", "-f", "/tmp/rinkhals/gklib.log"}, false, false},
		{[]string{"sh", "/useremain/home/rinkhals/apps/vanilla-klipper/klippy.sh"}, false, false},
		{[]string{"python3", "ready_check.py", "/tmp/unix_uds1", "180"}, false, false},
	}
	for _, c := range cases {
		if got := isGoKlipper(c.argv); got != c.gk {
			t.Errorf("isGoKlipper(%v) = %v, want %v", c.argv, got, c.gk)
		}
		if got := isKlippy(c.argv); got != c.klipy {
			t.Errorf("isKlippy(%v) = %v, want %v", c.argv, got, c.klipy)
		}
	}
}
