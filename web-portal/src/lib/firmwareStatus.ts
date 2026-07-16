import { readable } from "svelte/store";

export interface FirmwareStatusResponse {
	model_code: string;
	model_name: string;
	current_firmware: string;
	current_rinkhals: string;
	latest_firmware?: string;
	latest_rinkhals?: string;
	firmware_update_available: boolean;
	rinkhals_update_available: boolean;
	fetched_at: string;
	notice?: string;
}

const apiHost = import.meta.env.DEV ? "http://localhost:8090" : "";

const initialStatus: FirmwareStatusResponse = {
	model_code: "",
	model_name: "",
	current_firmware: "",
	current_rinkhals: "",
	firmware_update_available: false,
	rinkhals_update_available: false,
	fetched_at: ""
};

/**
 * Shared firmware-status store. The backend already caches /api/firmware/status
 * for 30 minutes, so the poll cadence here only needs to be brisk enough that a
 * fresh visit to a page picks up changes within a few seconds; we don't need
 * to hammer the upstream feeds. We poll every 60s while subscribed and let the
 * backend cache absorb concurrent reads from multiple pages.
 *
 * Like the printer-state store, network errors leave the previously-known
 * value in place rather than resetting to the empty default.
 */
export const firmwareStatus = readable<FirmwareStatusResponse>(initialStatus, (set) => {
	let active = true;

	const tick = async () => {
		if (!active) return;
		try {
			const res = await fetch(`${apiHost}/api/firmware/status`);
			if (res.ok && active) {
				const data: FirmwareStatusResponse = await res.json();
				set(data);
			}
		} catch {
			// Leave the last good value in place on transient errors.
		}
	};

	tick();
	const handle = setInterval(tick, 60_000);

	return () => {
		active = false;
		clearInterval(handle);
	};
});
