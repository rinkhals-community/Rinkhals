package main

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeApps stands in for two installed apps, "app" (running as pid 100) and
// "other" (stopped), and counts how often each one is asked.
type fakeApps struct {
	mu      sync.Mutex
	asked   map[string]int
	running map[string]bool
	enabled map[string]bool
	alive   map[int]bool
}

func (f *fakeApps) set(change func()) { f.mu.Lock(); change(); f.mu.Unlock() }

func (f *fakeApps) timesAsked(id string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.asked[id]
}

func fakeAppStates(t *testing.T, step, idle time.Duration) *fakeApps {
	t.Helper()
	f := &fakeApps{
		asked:   map[string]int{},
		running: map[string]bool{"app": true},
		enabled: map[string]bool{"app": true},
		alive:   map[int]bool{100: true},
	}

	stopAppStatesWalker(t)
	oldIDs, oldQuery, oldEnabled, oldAlive := appStatesIDs, appStatesQuery, appStatesEnabled, appStatesAlive
	oldStep, oldIdle := appStatesStep, appStatesIdle

	appStatesIDs = func() []string { return []string{"app", "other"} }
	appStatesEnabled = func(id string) bool { f.mu.Lock(); defer f.mu.Unlock(); return f.enabled[id] }
	appStatesAlive = func(pid int) bool { f.mu.Lock(); defer f.mu.Unlock(); return f.alive[pid] }
	appStatesQuery = func(id string) (appState, []int) {
		f.mu.Lock()
		defer f.mu.Unlock()
		f.asked[id]++
		state := appState{Enabled: f.enabled[id], Running: f.running[id]}
		if id == "app" && state.Running {
			return state, []int{100}
		}
		return state, nil
	}
	appStatesStep, appStatesIdle = step, idle

	t.Cleanup(func() {
		stopAppStatesWalker(t)
		appStatesIDs, appStatesQuery, appStatesEnabled, appStatesAlive = oldIDs, oldQuery, oldEnabled, oldAlive
		appStatesStep, appStatesIdle = oldStep, oldIdle
	})
	return f
}

func appStatesAreWalking() bool {
	appStatesMu.Lock()
	defer appStatesMu.Unlock()
	return appStatesWalking
}

func stopAppStatesWalker(t *testing.T) {
	t.Helper()
	eventually(t, "the background round to stop", func() bool {
		invalidateAppStates()
		return !appStatesAreWalking()
	})
}

func eventually(t *testing.T, what string, done func() bool) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for !done() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
		time.Sleep(time.Millisecond)
	}
}

func TestPollsDontAskTheApps(t *testing.T) {
	f := fakeAppStates(t, time.Hour, time.Hour)

	for i := 0; i < 50; i++ {
		states := cachedAppStates()
		if !states["app"].Running || !states["app"].Enabled || states["other"].Running {
			t.Fatalf("poll %d: wrong states %v", i, states)
		}
	}
	if a, o := f.timesAsked("app"), f.timesAsked("other"); a != 1 || o != 1 {
		t.Errorf("50 polls asked app %d times and other %d times, want once each", a, o)
	}
}

func TestAnActionAsksEveryAppAgain(t *testing.T) {
	f := fakeAppStates(t, time.Hour, time.Hour)

	cachedAppStates()
	f.set(func() { f.running["app"] = false })
	invalidateAppStates()
	// The page reloads right after its own action and must see the new state.
	if cachedAppStates()["app"].Running {
		t.Error("got the answer from before the action")
	}
	if a := f.timesAsked("app"); a != 2 {
		t.Errorf("app asked %d times, want 2", a)
	}
}

func TestAnAppWhoseProcessDiedIsAskedAgain(t *testing.T) {
	f := fakeAppStates(t, time.Hour, time.Hour)

	cachedAppStates()
	f.set(func() { f.alive[100] = false; f.running["app"] = false })

	eventually(t, "the app to show as stopped", func() bool { return !cachedAppStates()["app"].Running })
	if a, o := f.timesAsked("app"), f.timesAsked("other"); a != 2 || o != 1 {
		t.Errorf("app asked %d times and other %d times, want 2 and 1", a, o)
	}
}

func TestAFlagChangeShowsAtOnceAndAsksThatAppAgain(t *testing.T) {
	f := fakeAppStates(t, time.Hour, time.Hour)

	cachedAppStates()
	// Enabled and started from the touch screen
	f.set(func() { f.enabled["other"] = true; f.running["other"] = true })

	if !cachedAppStates()["other"].Enabled {
		t.Error("the enabled flag should show on the very next poll")
	}
	eventually(t, "the app to show as running", func() bool { return cachedAppStates()["other"].Running })
	if a, o := f.timesAsked("app"), f.timesAsked("other"); a != 1 || o != 2 {
		t.Errorf("app asked %d times and other %d times, want 1 and 2", a, o)
	}
}

func TestTheSlowRoundAsksOneAppPerStep(t *testing.T) {
	const step = 20 * time.Millisecond
	f := fakeAppStates(t, step, time.Hour)

	start := time.Now()
	cachedAppStates()
	// Started from a terminal: no flag changed, no process of ours died
	f.set(func() { f.running["other"] = true })

	eventually(t, "the slow round to notice", func() bool { return cachedAppStates()["other"].Running })
	elapsed := time.Since(start)
	asked := f.timesAsked("app") + f.timesAsked("other")
	if limit := 2 + int(elapsed/step) + 1; asked > limit {
		t.Errorf("%d questions in %v, want at most %d", asked, elapsed, limit)
	}
}

func TestEverythingStopsWhenNobodyPolls(t *testing.T) {
	f := fakeAppStates(t, 2*time.Millisecond, 30*time.Millisecond)

	cachedAppStates()
	eventually(t, "the background round to stop by itself", func() bool { return !appStatesAreWalking() })
	settled := f.timesAsked("app")
	time.Sleep(50 * time.Millisecond)
	if got := f.timesAsked("app"); got != settled {
		t.Errorf("still asking with no page polling: %d then %d", settled, got)
	}
	// The next page to poll gets fresh answers, not ones from before the pause.
	cachedAppStates()
	if got := f.timesAsked("app"); got != settled+1 {
		t.Errorf("app asked %d times after polling again, want %d", got, settled+1)
	}
}

func TestParseAppStatus(t *testing.T) {
	started, pids := parseAppStatus("Status: started\nPIDs: 12 34\nLog: /tmp/x.log\n")
	if !started || len(pids) != 2 || pids[0] != 12 || pids[1] != 34 {
		t.Errorf("got %v %v", started, pids)
	}
	if started, pids := parseAppStatus("Status: stopped\nPIDs: \nLog: \n"); started || pids != nil {
		t.Errorf("stopped: got %v %v", started, pids)
	}
	if started, _ := parseAppStatus(""); started {
		t.Error("no output should mean stopped")
	}
	if started, _ := parseAppStatus("Status: startedish\n"); started {
		t.Error("only the word started counts")
	}
	if started, pids := parseAppStatus("noise\nStatus: started\nPIDs: abc 7\n"); !started || len(pids) != 1 || pids[0] != 7 {
		t.Errorf("noise: got %v %v", started, pids)
	}
}

func TestServiceActionsAreLimited(t *testing.T) {
	for _, action := range []string{"start", "stop", "restart", "enable", "disable"} {
		if !isServiceAction(action) {
			t.Errorf("%q should be allowed", action)
		}
	}
	for _, action := range []string{"", "remove", "start; reboot #", "stop_app x; reboot; start"} {
		if isServiceAction(action) {
			t.Errorf("%q should be refused", action)
		}
	}
}

func TestAppStatusArgs(t *testing.T) {
	dir := t.TempDir()
	plain := filepath.Join(dir, "plain.sh")
	shebang := filepath.Join(dir, "shebang.sh")
	os.WriteFile(plain, []byte(". /useremain/rinkhals/.current/tools.sh\n"), 0755)
	os.WriteFile(shebang, []byte("#!/bin/sh\n"), 0755)

	if got := strings.Join(appStatusArgs(plain), " "); got != "-n 19 sh "+plain+" status" {
		t.Errorf("a script with no #! line must be run with sh, got %q", got)
	}
	if got := strings.Join(appStatusArgs(shebang), " "); got != "-n 19 "+shebang+" status" {
		t.Errorf("a script with a #! line runs by itself, got %q", got)
	}
}
