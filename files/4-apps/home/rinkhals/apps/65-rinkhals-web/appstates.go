package main

import (
	"sync"
	"time"
)

// App states, remembered for a few seconds.
//
// Finding out whether apps are enabled and running means a shell that loads
// tools.sh and runs every app's own "app.sh status", each of which loads
// tools.sh again: a couple of hundred short-lived processes for one answer.
// The portal's pages ask every 5 seconds, and on a printer with one core,
// shared with Klipper, that showed as a CPU spike to 80-95% every 5 seconds
// for as long as a browser had the portal open.
//
// So the answer is kept for appStatesTTL. A page asking within that time gets
// the remembered answer. One asking later still gets it straight away, while
// a single refresh runs in the background. Anything the portal does to an app
// (start, stop, enable, disable, install, uninstall) forgets the answer, so
// the page shows the result of its own action at once.

type appState = struct {
	Enabled bool
	Running bool
}

const appStatesTTL = 15 * time.Second

var (
	appStatesMu         sync.Mutex
	appStatesValue      map[string]appState
	appStatesAt         time.Time
	appStatesRefreshing bool

	// One query at a time, so impatient pages can't stack them up.
	appStatesQueryMu sync.Mutex

	// Swapped out by tests.
	appStatesQuery = func() map[string]appState { return queryAppStates(listAppIDs()) }
	appStatesNow   = time.Now
)

// cachedAppStates returns the state of every app, at most appStatesTTL old
// unless a refresh is already on its way.
func cachedAppStates() map[string]appState {
	appStatesMu.Lock()
	value, at := appStatesValue, appStatesAt

	if value != nil {
		if appStatesNow().Sub(at) >= appStatesTTL && !appStatesRefreshing {
			appStatesRefreshing = true
			go refreshAppStates()
		}
		appStatesMu.Unlock()
		return value
	}
	appStatesMu.Unlock()

	// Nothing remembered: this caller waits for a real answer.
	return refreshAppStates()
}

func refreshAppStates() map[string]appState {
	appStatesQueryMu.Lock()
	defer appStatesQueryMu.Unlock()

	// Someone else may have just answered while we waited for our turn.
	appStatesMu.Lock()
	if appStatesValue != nil && appStatesNow().Sub(appStatesAt) < appStatesTTL {
		value := appStatesValue
		appStatesRefreshing = false
		appStatesMu.Unlock()
		return value
	}
	appStatesMu.Unlock()

	value := appStatesQuery()

	appStatesMu.Lock()
	appStatesValue = value
	appStatesAt = appStatesNow()
	appStatesRefreshing = false
	appStatesMu.Unlock()
	return value
}

// invalidateAppStates forgets the remembered states. Call it after anything
// that starts, stops, enables, disables, installs or removes an app.
func invalidateAppStates() {
	appStatesMu.Lock()
	appStatesValue = nil
	appStatesMu.Unlock()
}
