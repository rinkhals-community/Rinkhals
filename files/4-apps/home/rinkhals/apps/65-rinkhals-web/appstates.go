package main

import (
	"os"
	"strconv"
	"sync"
	"time"
)

// App states, without asking the apps over and over.
//
// The only way to ask an app whether it is running is its own "app.sh status",
// a shell script that starts a handful of processes. The portal's pages want
// the state of every app every 5 seconds. On a printer with one core, shared
// with Klipper, running every status script on every poll showed as a CPU
// spike to 80-100% for as long as a browser had the portal open.
//
// So each app is asked once, and its answer is remembered together with the
// process ids it reported. After that, a poll only looks at things that cost
// nothing to look at:
//   - the app's enabled and disabled flag files, read on every poll
//   - whether the processes it reported still exist
// The app is only asked again when one of those changed, when the portal
// itself did something to an app (start, stop, enable, disable, install,
// uninstall: every app is asked again, once), or when its turn comes in a
// slow round that asks one app every appStatesStep. The round is there for
// what the cheap signs can't show, such as an app started from a terminal.
// Nothing is asked at all once pages stop polling.

type appState = struct {
	Enabled bool
	Running bool
}

var (
	// One app is asked again this often while pages are polling
	appStatesStep = 10 * time.Second
	// With no page polling for this long, everything stops
	appStatesIdle = 30 * time.Second

	appStatesMu      sync.Mutex
	appStatesValue   map[string]appState // never changed in place: replaced
	appStatesPIDs    map[string][]int    // same
	appStatesDue     []string            // apps to ask again now
	appStatesGen     int                 // bumped when the answers are forgotten
	appStatesAsked   time.Time
	appStatesWalking bool
	appStatesWake    = make(chan struct{}, 1)

	// One full round of questions at a time, so impatient pages can't stack
	// them up
	appStatesLoadMu sync.Mutex

	// Swapped out by tests
	appStatesIDs     = listAppIDs
	appStatesQuery   = queryAppState
	appStatesEnabled = isAppEnabled
	appStatesAlive   = func(pid int) bool {
		_, err := os.Stat("/proc/" + strconv.Itoa(pid))
		return err == nil
	}
)

// cachedAppStates returns the state of every app. It only waits when nothing
// is remembered.
func cachedAppStates() map[string]appState {
	appStatesMu.Lock()
	appStatesAsked = time.Now()
	value, pids, gen := appStatesValue, appStatesPIDs, appStatesGen
	appStatesMu.Unlock()

	if value == nil {
		value = loadAppStates()
	} else {
		value = checkAppStates(value, pids, gen)
	}

	// The slow round runs from here on, until pages stop polling
	appStatesMu.Lock()
	if appStatesValue != nil && !appStatesWalking {
		appStatesWalking = true
		go walkAppStates()
	}
	appStatesMu.Unlock()
	return value
}

// checkAppStates looks at the free signs. Enabled is always current in what
// it returns; an app whose flags changed or whose processes are gone is put
// up to be asked again.
func checkAppStates(value map[string]appState, pids map[string][]int, gen int) map[string]appState {
	var due []string
	next := value
	for id, state := range value {
		if enabled := appStatesEnabled(id); enabled != state.Enabled {
			if len(due) == 0 {
				next = make(map[string]appState, len(value))
				for k, v := range value {
					next[k] = v
				}
			}
			state.Enabled = enabled
			next[id] = state
			due = append(due, id)
			continue
		}
		if state.Running {
			for _, pid := range pids[id] {
				if !appStatesAlive(pid) {
					due = append(due, id)
					break
				}
			}
		}
	}
	if len(due) == 0 {
		return value
	}

	appStatesMu.Lock()
	if appStatesGen == gen && appStatesValue != nil {
		// Keep what the walker may have learned meanwhile, apart from Enabled
		merged := make(map[string]appState, len(appStatesValue))
		for k, v := range appStatesValue {
			v.Enabled = next[k].Enabled
			merged[k] = v
		}
		appStatesValue = merged
		for _, id := range due {
			queued := false
			for _, q := range appStatesDue {
				queued = queued || q == id
			}
			if !queued {
				appStatesDue = append(appStatesDue, id)
			}
		}
	}
	appStatesMu.Unlock()
	wakeAppStates()
	return next
}

// loadAppStates asks every app and remembers the answers.
func loadAppStates() map[string]appState {
	appStatesLoadMu.Lock()
	defer appStatesLoadMu.Unlock()

	// Someone else may have just done this while we waited for our turn
	appStatesMu.Lock()
	if appStatesValue != nil {
		value := appStatesValue
		appStatesMu.Unlock()
		return value
	}
	gen := appStatesGen
	appStatesMu.Unlock()

	value := map[string]appState{}
	pids := map[string][]int{}
	for _, id := range appStatesIDs() {
		value[id], pids[id] = appStatesQuery(id)
	}

	appStatesMu.Lock()
	// Kept only if nothing was done to an app while we were asking
	if appStatesGen == gen {
		appStatesValue, appStatesPIDs, appStatesDue = value, pids, nil
	}
	appStatesMu.Unlock()
	return value
}

// walkAppStates asks the apps that are due at once, and otherwise one app per
// step, until pages stop polling.
func walkAppStates() {
	var round []string
	for {
		timer := time.NewTimer(appStatesStep)
		stepped := false
		select {
		case <-timer.C:
			stepped = true
		case <-appStatesWake:
			timer.Stop()
		}

		for {
			appStatesMu.Lock()
			if appStatesValue == nil || time.Since(appStatesAsked) >= appStatesIdle {
				// Nobody is looking any more, or an action forgot the
				// answers. Forget them either way: the next page to ask gets
				// fresh ones.
				appStatesValue, appStatesPIDs, appStatesDue = nil, nil, nil
				appStatesWalking = false
				appStatesMu.Unlock()
				return
			}
			gen := appStatesGen
			id := ""
			if len(appStatesDue) > 0 {
				id, appStatesDue = appStatesDue[0], appStatesDue[1:]
			}
			appStatesMu.Unlock()

			if id == "" {
				if !stepped {
					break
				}
				stepped = false
				if len(round) == 0 {
					round = appStatesIDs()
					forgetMissingApps(round, gen)
				}
				if len(round) == 0 {
					break
				}
				id, round = round[0], round[1:]
			}

			state, pids := appStatesQuery(id)

			appStatesMu.Lock()
			if appStatesGen == gen && appStatesValue != nil {
				nextValue := make(map[string]appState, len(appStatesValue)+1)
				for k, v := range appStatesValue {
					nextValue[k] = v
				}
				nextPIDs := make(map[string][]int, len(appStatesPIDs)+1)
				for k, v := range appStatesPIDs {
					nextPIDs[k] = v
				}
				nextValue[id], nextPIDs[id] = state, pids
				appStatesValue, appStatesPIDs = nextValue, nextPIDs
			}
			appStatesMu.Unlock()
		}
	}
}

// forgetMissingApps drops the apps that are no longer installed.
func forgetMissingApps(installed []string, gen int) {
	keep := make(map[string]bool, len(installed))
	for _, id := range installed {
		keep[id] = true
	}
	appStatesMu.Lock()
	defer appStatesMu.Unlock()
	if appStatesGen != gen || appStatesValue == nil {
		return
	}
	nextValue := map[string]appState{}
	nextPIDs := map[string][]int{}
	for id, state := range appStatesValue {
		if keep[id] {
			nextValue[id], nextPIDs[id] = state, appStatesPIDs[id]
		}
	}
	appStatesValue, appStatesPIDs = nextValue, nextPIDs
}

func wakeAppStates() {
	select {
	case appStatesWake <- struct{}{}:
	default:
	}
}

// invalidateAppStates forgets the remembered states. Call it after anything
// that starts, stops, enables, disables, installs or removes an app.
func invalidateAppStates() {
	appStatesMu.Lock()
	appStatesValue, appStatesPIDs, appStatesDue = nil, nil, nil
	appStatesGen++
	appStatesMu.Unlock()
	wakeAppStates()
}
