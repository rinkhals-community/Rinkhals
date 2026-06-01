import { readable } from "svelte/store";

export type PrinterStateValue =
	| "standby"
	| "printing"
	| "paused"
	| "pausing"
	| "cancelling"
	| "error"
	| "offline"
	| "unknown";

export interface PrinterStateResponse {
	state: PrinterStateValue;
	can_install: boolean;
	reason?: string;
}

const apiHost = import.meta.env.DEV ? "http://localhost:8080" : "";

const initialState: PrinterStateResponse = {
	state: "unknown",
	can_install: true
};

/**
 * Shared printer-state store. Polls `/api/printer/state` every 5 seconds
 * while at least one Svelte component is subscribed, and stops automatically
 * when nothing is listening (Svelte's readable contract handles
 * subscriber-count tracking for us).
 *
 * Pages should drive UI gating ("disable Install while printing") off
 * `$printerState.can_install` rather than checking the raw state directly,
 * so the policy of "which states block installs" stays in one place
 * (the backend) and the UI doesn't have to know the full Moonraker /
 * Klipper state vocabulary.
 *
 * Network errors leave the previously-known value in place rather than
 * resetting to a default - that way a transient blip doesn't visually
 * unlock buttons that were correctly disabled a tick ago.
 */
export const printerState = readable<PrinterStateResponse>(initialState, (set) => {
	let active = true;

	const tick = async () => {
		if (!active) return;
		try {
			const res = await fetch(`${apiHost}/api/printer/state`);
			if (res.ok && active) {
				const data: PrinterStateResponse = await res.json();
				set(data);
			}
		} catch {
			// Leave the last good value in place on transient errors.
		}
	};

	tick();
	const handle = setInterval(tick, 5000);

	return () => {
		active = false;
		clearInterval(handle);
	};
});
