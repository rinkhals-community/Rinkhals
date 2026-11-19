package main

import (
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// fakeAppStates swaps in a counting query and a clock the test moves.
func fakeAppStates(t *testing.T) (queries *int32, advance func(time.Duration)) {
	t.Helper()
	var n int32
	now := time.Unix(1_000_000, 0)
	var mu sync.Mutex

	oldQuery, oldNow := appStatesQuery, appStatesNow
	appStatesQuery = func() map[string]appState {
		c := atomic.AddInt32(&n, 1)
		return map[string]appState{"app": {Enabled: true, Running: c%2 == 1}}
	}
	appStatesNow = func() time.Time { mu.Lock(); defer mu.Unlock(); return now }
	invalidateAppStates()
	t.Cleanup(func() {
		appStatesQuery, appStatesNow = oldQuery, oldNow
		invalidateAppStates()
	})
	return &n, func(d time.Duration) { mu.Lock(); now = now.Add(d); mu.Unlock() }
}

func TestAppStatesAreRememberedBetweenPolls(t *testing.T) {
	queries, advance := fakeAppStates(t)

	// A page polling every 5 s for 15 s costs one query, not four.
	for i := 0; i < 3; i++ {
		if !cachedAppStates()["app"].Running {
			t.Fatal("expected the first answer")
		}
		advance(4 * time.Second)
	}
	if got := atomic.LoadInt32(queries); got != 1 {
		t.Errorf("%d queries for three polls inside the TTL, want 1", got)
	}
}

func TestAnActionForgetsTheStates(t *testing.T) {
	queries, _ := fakeAppStates(t)

	cachedAppStates()
	invalidateAppStates()
	// The page reloads right after its own action and must see the new state.
	if cachedAppStates()["app"].Running {
		t.Error("got the answer from before the action")
	}
	if got := atomic.LoadInt32(queries); got != 2 {
		t.Errorf("%d queries, want 2", got)
	}
}

func TestStaleStatesAreServedWhileOneRefreshRuns(t *testing.T) {
	queries, advance := fakeAppStates(t)
	cachedAppStates()
	advance(appStatesTTL + time.Second)

	// Several polls arrive after the TTL. None of them waits, and together
	// they start a single refresh.
	for i := 0; i < 5; i++ {
		if !cachedAppStates()["app"].Running {
			t.Fatal("a poll after the TTL should still get the remembered answer at once")
		}
	}
	deadline := time.Now().Add(2 * time.Second)
	for atomic.LoadInt32(queries) < 2 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	time.Sleep(20 * time.Millisecond)
	if got := atomic.LoadInt32(queries); got != 2 {
		t.Errorf("%d queries after five stale polls, want 2", got)
	}
	if cachedAppStates()["app"].Running {
		t.Error("the refreshed answer was not picked up")
	}
}
