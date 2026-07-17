import { writable, derived, get } from "svelte/store";
import { browser } from "$app/environment";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "rinkhals-theme";

function readStoredPreference(): ThemePreference {
	if (!browser) return "system";
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw === "light" || raw === "dark" || raw === "system") return raw;
	} catch (e) {
		// ignore (private mode, etc.)
	}
	return "system";
}

function systemPrefersDark(): boolean {
	if (!browser) return false;
	return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolve(pref: ThemePreference): ResolvedTheme {
	if (pref === "system") return systemPrefersDark() ? "dark" : "light";
	return pref;
}

function apply(resolved: ResolvedTheme) {
	if (!browser) return;
	document.documentElement.setAttribute("data-theme", resolved);
}

export const themePreference = writable<ThemePreference>(readStoredPreference());

export const resolvedTheme = derived<typeof themePreference, ResolvedTheme>(
	themePreference,
	($pref, set) => {
		set(resolve($pref));

		if (!browser) return;

		// React to system theme changes while in "system" mode.
		const mq = window.matchMedia("(prefers-color-scheme: dark)");
		const onChange = () => {
			if (get(themePreference) === "system") {
				set(resolve("system"));
			}
		};
		mq.addEventListener("change", onChange);
		return () => mq.removeEventListener("change", onChange);
	},
	resolve(readStoredPreference())
);

// Push changes to <html data-theme> and persist preference.
if (browser) {
	resolvedTheme.subscribe(apply);
	themePreference.subscribe((pref) => {
		try {
			localStorage.setItem(STORAGE_KEY, pref);
		} catch (e) {
			// ignore
		}
	});
}

export function setTheme(pref: ThemePreference) {
	themePreference.set(pref);
}

export function cycleTheme() {
	const order: ThemePreference[] = ["system", "light", "dark"];
	const current = get(themePreference);
	const next = order[(order.indexOf(current) + 1) % order.length];
	themePreference.set(next);
}
