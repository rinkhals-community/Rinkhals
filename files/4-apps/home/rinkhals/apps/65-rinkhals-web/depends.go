package main

import (
	"encoding/json"
	"net/http"
	"path/filepath"
	"sort"
	"strings"
)

// App dependencies. "depends" in app.json lists the apps (by folder name) an
// app can't work without. An entry can name alternatives separated by |, when
// any one of several apps will do. tools.sh enforces the rules for enabling and
// disabling; this file covers what only the portal does: installing from the
// store and uninstalling.
//
//   - an app can't be installed until everything it depends on is installed
//   - an app can't be uninstalled while an installed app depends on it

// alternatives splits one "depends" entry into the apps that satisfy it.
func alternatives(entry string) []string {
	var out []string
	for _, a := range strings.Split(entry, "|") {
		if a = strings.TrimSpace(a); a != "" {
			out = append(out, a)
		}
	}
	return out
}

// entryMet says whether have() holds for one of the entry's alternatives,
// leaving out the app named in without.
func entryMet(entry string, have func(string) bool, without string) bool {
	for _, a := range alternatives(entry) {
		if a != without && have(a) {
			return true
		}
	}
	return false
}

// dependentsOf lists the apps in depends (app id -> its "depends" entries) that
// would lose a dependency without target: they name it in an entry, and have()
// holds for no other alternative in that entry. Sorted.
func dependentsOf(target string, depends map[string][]string, have func(string) bool) []string {
	var out []string
	for id, needs := range depends {
		if id == target {
			continue
		}
		for _, entry := range needs {
			named := false
			for _, a := range alternatives(entry) {
				named = named || a == target
			}
			if named && !entryMet(entry, have, target) {
				out = append(out, id)
				break
			}
		}
	}
	sort.Strings(out)
	return out
}

// missingFrom lists the entries of needs that have() holds for no alternative of.
func missingFrom(needs []string, have func(string) bool) []string {
	var out []string
	for _, entry := range needs {
		if !entryMet(entry, have, "") {
			out = append(out, entry)
		}
	}
	return out
}

// spellOut turns entries into text: "a|b" reads as "a or b".
func spellOut(entries []string) string {
	return strings.ReplaceAll(strings.Join(entries, ", "), "|", " or ")
}

// isAppInstalled matches tools.sh's is_app_installed: a user or system app
// folder holding both app.sh and app.json.
func isAppInstalled(id string) bool {
	if !isSafeKey(id) {
		return false
	}
	root, _ := resolveAppRoot(id)
	return fileExists(filepath.Join(root, "app.sh")) && fileExists(filepath.Join(root, "app.json"))
}

// installedDepends reads what every installed app depends on.
func installedDepends() map[string][]string {
	out := map[string][]string{}
	for _, id := range listAppIDs() {
		if !isAppInstalled(id) {
			continue
		}
		root, _ := resolveAppRoot(id)
		if m, err := readManifest(root); err == nil && len(m.Depends) > 0 {
			out[id] = m.Depends
		}
	}
	return out
}

// refuse answers with success:false and a message, the shape the portal shows
// as an error toast.
func refuse(w http.ResponseWriter, status int, message string) {
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"success": false,
		"output":  message,
	})
}

// uninstallBlockedBy says why an app can't be uninstalled, or "" if it can.
func uninstallBlockedBy(id string) string {
	dependents := dependentsOf(id, installedDepends(), isAppInstalled)
	if len(dependents) == 0 {
		return ""
	}
	return "Can't uninstall " + id + ". These apps depend on it, uninstall them first: " + strings.Join(dependents, ", ")
}

// installBlockedBy says why a store app can't be installed, or "" if it can.
func installBlockedBy(id string, depends []string) string {
	missing := missingFrom(depends, isAppInstalled)
	if len(missing) == 0 {
		return ""
	}
	return "Can't install " + id + ". It needs these apps installed first: " + spellOut(missing)
}
