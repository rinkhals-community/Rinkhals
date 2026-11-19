package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"net/http"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
)

// readCPUTimes parses the aggregate "cpu" line of /proc/stat and returns the
// total and idle jiffie counters (idle includes iowait).
func readCPUTimes() (total, idle int64, ok bool) {
	data, err := ioutil.ReadFile("/proc/stat")
	if err != nil {
		return 0, 0, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if !strings.HasPrefix(line, "cpu ") {
			continue
		}
		fields := strings.Fields(line)[1:] // drop the "cpu" label
		for i, f := range fields {
			v, err := strconv.ParseInt(f, 10, 64)
			if err != nil {
				continue
			}
			total += v
			if i == 3 || i == 4 { // idle, iowait
				idle += v
			}
		}
		return total, idle, true
	}
	return 0, 0, false
}

// cpuBusyPercent samples /proc/stat twice over the given window and returns the
// aggregate CPU busy percentage (0-100, summed across all cores).
//
// We report this instead of the load average on purpose. This hardware keeps
// ~11 kernel threads (the Realtek RTL8723DS wifi driver and Rockchip media
// stack) permanently parked in uninterruptible sleep on driver semaphores.
// Linux counts uninterruptible tasks in the load average, so loadavg sits
// around ~11 even when the CPU is mostly idle - it does not reflect real work.
// CPU utilization derived from /proc/stat is immune to that inflation.
func cpuBusyPercent(window time.Duration) (int, bool) {
	total1, idle1, ok1 := readCPUTimes()
	if !ok1 {
		return 0, false
	}
	time.Sleep(window)
	total2, idle2, ok2 := readCPUTimes()
	if !ok2 {
		return 0, false
	}
	dTotal := total2 - total1
	dIdle := idle2 - idle1
	if dTotal <= 0 {
		return 0, false
	}
	busy := float64(dTotal-dIdle) / float64(dTotal) * 100
	if busy < 0 {
		busy = 0
	} else if busy > 100 {
		busy = 100
	}
	return int(busy + 0.5), true
}


func handleMetrics(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	uptimeBytes, _ := ioutil.ReadFile("/proc/uptime")
	uptimeStr := strings.Split(string(uptimeBytes), " ")[0]
	
	memBytes, _ := ioutil.ReadFile("/proc/meminfo")
	var memTotal, memFree, memAvailable int
	for _, line := range strings.Split(string(memBytes), "\n") {
		if strings.HasPrefix(line, "MemTotal:") {
			fmt.Sscanf(line, "MemTotal: %d kB", &memTotal)
		} else if strings.HasPrefix(line, "MemAvailable:") {
			fmt.Sscanf(line, "MemAvailable: %d kB", &memAvailable)
		} else if strings.HasPrefix(line, "MemFree:") {
			fmt.Sscanf(line, "MemFree: %d kB", &memFree)
		}
	}
	if memAvailable == 0 {
		// Very old kernels lack MemAvailable; fall back to free.
		memAvailable = memFree
	}
	// Round kB to MB and derive the three segments so they always sum to total:
	//   in use = total - available   (committed, not reclaimable)
	//   cached = available - free     (reclaimable page cache / slab)
	//   free   = free                 (untouched)
	// "available" (cached + free) is what an app can actually use, which is the
	// number the dashboard shows: MemFree alone reads ~97% used and is misleading.
	memTotalMB := (memTotal + 512) / 1024
	memAvailableMB := (memAvailable + 512) / 1024
	memFreeMB := (memFree + 512) / 1024
	memInUseMB := memTotalMB - memAvailableMB
	memCachedMB := memAvailableMB - memFreeMB

	var stat syscall.Statfs_t
	syscall.Statfs("/userdata", &stat)
	diskUsage := 0
	if stat.Blocks > 0 {
		diskUsage = int(float64(stat.Blocks-stat.Bfree) / float64(stat.Blocks) * 100)
	}

	cpuUsage, ok := cpuBusyPercent(250 * time.Millisecond)
	if !ok {
		cpuUsage = 0
	}

	json.NewEncoder(w).Encode(map[string]interface{}{
		"uptime":         uptimeStr,
		"cpuUsage":       cpuUsage,
		"memTotalMB":     memTotalMB,
		"memAvailableMB": memAvailableMB,
		"memInUseMB":     memInUseMB,
		"memCachedMB":    memCachedMB,
		"memFreeMB":      memFreeMB,
		"diskUsage":      diskUsage,
	})
}

func handleSaveFile(w http.ResponseWriter, r *http.Request) {

	var req struct {
		Path    string `json:"path"`
		Content string `json:"content"`
	}
	json.NewDecoder(r.Body).Decode(&req)

	cleanPath := filepath.Clean(req.Path)
	ioutil.WriteFile(cleanPath, []byte(req.Content), 0644)
	json.NewEncoder(w).Encode(map[string]interface{}{"success": true})
}

func handleServices(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method == "GET" {
		services := []map[string]string{
			{"id": "25-mainsail", "name": "Mainsail", "status": "Stopped"},
			{"id": "26-fluidd", "name": "Fluidd", "status": "Stopped"},
			{"id": "40-moonraker", "name": "Moonraker", "status": "Stopped"},
			{"id": "30-mjpg-streamer", "name": "Webcam", "status": "Stopped"},
			{"id": "50-remote-display", "name": "Remote Display", "status": "Stopped"},
		}

		// From the remembered app states: this used to start a shell per
		// service on every poll of the dashboard (see appstates.go)
		states := cachedAppStates()
		for _, s := range services {
			if states[s["id"]].Running {
				s["status"] = "Running"
			}
		}
		json.NewEncoder(w).Encode(services)
		return
	}

	var req struct {
		Action  string `json:"action"`
		Service string `json:"service"`
	}
	json.NewDecoder(r.Body).Decode(&req)

	// Both values go into a shell command, so neither is taken as given: the
	// action must be one we know, and the service a plain app id.
	if !isServiceAction(req.Action) || !isSafeKey(req.Service) {
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"success": false,
			"output":  "Unknown action or service",
		})
		return
	}
	service := shellQuote(req.Service)
	cmdStr := fmt.Sprintf(". %s && %s_app %s", toolsSh, req.Action, service)
	if req.Action == "restart" {
		cmdStr = fmt.Sprintf(". %s && stop_app %s && sleep 1 && start_app %s", toolsSh, service, service)
	}

	out, err := exec.Command("sh", "-c", cmdStr).CombinedOutput()
	invalidateAppStates()
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": err == nil,
		"output":  string(out),
	})
}

// isServiceAction tells whether the dashboard may ask for this action on a
// service. Each one but "restart" names a tools.sh function, <action>_app.
func isServiceAction(action string) bool {
	switch action {
	case "start", "stop", "restart", "enable", "disable":
		return true
	}
	return false
}

func handleLogStream(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil { return }
	defer conn.Close()

	logPath := r.URL.Query().Get("path")
	if logPath == "" { return }
	logPath = filepath.Clean(logPath)

	cmd := exec.Command("tail", "-f", "-n", "100", logPath)
	stdout, err := cmd.StdoutPipe()
	if err != nil { return }
	
	if err := cmd.Start(); err != nil { return }
	defer cmd.Process.Kill()

	go func() {
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				cmd.Process.Kill()
				return
			}
		}
	}()

	scanner := bufio.NewScanner(stdout)
	for scanner.Scan() {
		conn.WriteMessage(websocket.TextMessage, scanner.Bytes())
	}
}
