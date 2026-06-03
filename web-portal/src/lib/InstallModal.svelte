<script lang="ts">
	import { onDestroy } from "svelte";
	import { X, AlertTriangle, Download, ShieldAlert, CheckCircle2, Loader2 } from "lucide-svelte";

	type Source = "rinkhals" | "anycubic";

	interface Compatibility {
		compatible: boolean;
		warnings: string[];
		rinkhals_patches_for_target: boolean;
		target_version?: string;
	}

	interface PreflightResponse {
		install_id: string;
		expires_at: string;
		source: Source;
		version: string;
		compatibility?: Compatibility;
	}

	interface RunState {
		state: string; // matches backend installState* constants
		source: Source;
		version: string;
		download_pct: number;
		downloaded_mb: number;
		total_mb: number;
		message: string;
		error?: string;
		dry_run: boolean;
	}

	interface ProgressEvent {
		state: string;
		log: string[];
		run?: RunState;
	}

	interface Props {
		source: Source;
		version: string;
		assetUrl: string;
		title: string;
		subtitle?: string;
		onClose: () => void;
	}

	let { source, version, assetUrl, title, subtitle, onClose }: Props = $props();

	const apiHost = import.meta.env.DEV ? "http://localhost:8090" : "";

	type Phase = "preflighting" | "confirm" | "starting" | "running" | "rebooting" | "complete" | "failed";

	let phase = $state<Phase>("preflighting");
	let preflight = $state<PreflightResponse | null>(null);
	let preflightError = $state<string | null>(null);
	let runState = $state<RunState | null>(null);
	let progressLog = $state<string[]>([]);
	let commitError = $state<string | null>(null);
	let dryRun = $state(false);
	let eventSource: EventSource | null = null;
	let reconnectTimer: any = null;

	async function doPreflight() {
		phase = "preflighting";
		preflightError = null;
		try {
			const res = await fetch(`${apiHost}/api/firmware/install/preflight`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ source, version, asset_url: assetUrl })
			});
			if (!res.ok) {
				preflightError = await res.text();
				phase = "failed";
				return;
			}
			preflight = await res.json();
			// Default to real install. dry-run is an optional verification toggle
			// the user can opt into; the primary action is the real flash.
			dryRun = false;
			phase = "confirm";
		} catch (e: any) {
			preflightError = e.message || "Preflight failed";
			phase = "failed";
		}
	}

	async function doCommit() {
		if (!preflight) return;
		commitError = null;
		phase = "starting";

		try {
			const res = await fetch(`${apiHost}/api/firmware/install/commit`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ install_id: preflight.install_id, dry_run: dryRun })
			});
			if (!res.ok) {
				commitError = await res.text();
				phase = "failed";
				return;
			}
			phase = "running";
			openProgressStream();
		} catch (e: any) {
			commitError = e.message || "Commit failed";
			phase = "failed";
		}
	}

	function openProgressStream() {
		// EventSource carries cookies but not Authorization header. The backend
		// uses basic auth - because our session is already authenticated and the
		// browser holds the credentials for that origin, EventSource reuses them
		// on same-origin requests. In dev mode (cross-origin to localhost:8090)
		// the user will need to allow credentials separately; that's fine for
		// production usage where everything is same-origin.
		eventSource = new EventSource(`${apiHost}/api/firmware/install/progress`);
		eventSource.onmessage = (e) => {
			try {
				const ev: ProgressEvent = JSON.parse(e.data);
				if (ev.run) {
					runState = ev.run;
				}
				if (ev.log && ev.log.length > 0) {
					progressLog = ev.log;
				}
				if (ev.state === "rebooting") {
					phase = "rebooting";
					eventSource?.close();
					startReconnectPolling();
				} else if (ev.state === "complete") {
					phase = "complete";
					eventSource?.close();
				} else if (ev.state === "failed") {
					phase = "failed";
					eventSource?.close();
				}
			} catch (err) {
				console.error("Bad SSE payload", err);
			}
		};
		eventSource.onerror = () => {
			// SSE drops are expected when the printer reboots. If we were already
			// in the rebooting phase, the reconnect poller will pick up the
			// printer when it comes back. Otherwise surface the drop.
			if (phase === "running" || phase === "starting") {
				// May just be a transient gap; the heartbeat will retry.
			}
		};
	}

	function startReconnectPolling() {
		// After reboot, poll /api/printer/state until it responds OK. When it
		// does, the page can be reloaded.
		if (reconnectTimer) clearInterval(reconnectTimer);
		reconnectTimer = setInterval(async () => {
			try {
				const res = await fetch(`${apiHost}/api/printer/state`);
				if (res.ok) {
					phase = "complete";
					clearInterval(reconnectTimer);
				}
			} catch {
				// Still down; keep polling.
			}
		}, 5000);
	}

	onDestroy(() => {
		if (eventSource) eventSource.close();
		if (reconnectTimer) clearInterval(reconnectTimer);
	});

	function reload() {
		window.location.reload();
	}

	function handleBackdrop(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			// Only allow close-on-backdrop while not running. Mid-install close
			// would just disconnect SSE; the install continues regardless.
			if (phase === "confirm" || phase === "failed" || phase === "preflighting" || phase === "complete") {
				onClose();
			}
		}
	}

	// Kick off preflight as soon as the modal mounts.
	doPreflight();
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4"
	onclick={handleBackdrop}
>
	<div class="bg-canvas border border-line rounded-2xl max-w-xl w-full max-h-[85vh] flex flex-col shadow-2xl">
		<header class="flex items-start justify-between gap-4 px-6 py-4 border-b border-line-soft shrink-0">
			<div class="min-w-0">
				<h2 class="text-lg font-semibold text-ink flex items-center gap-2">
					<Download size={18} class="text-brand" />
					{title}
				</h2>
				{#if subtitle}
					<p class="text-xs text-ink-muted mt-0.5">{subtitle}</p>
				{/if}
			</div>
			{#if phase === "confirm" || phase === "failed" || phase === "complete" || phase === "preflighting"}
				<button
					type="button"
					onclick={onClose}
					aria-label="Close install dialog"
					class="text-ink-faint hover:text-ink p-1 rounded-md hover:bg-surface-warm transition-colors"
				>
					<X size={18} />
				</button>
			{/if}
		</header>

		<div class="flex-1 overflow-auto px-6 py-5 text-sm">
			{#if phase === "preflighting"}
				<div class="flex items-center gap-2 text-ink-muted">
					<Loader2 size={16} class="animate-spin" /> Checking compatibility and reserving install slot...
				</div>
			{:else if phase === "confirm" && preflight}
				{#if preflight.compatibility && !preflight.compatibility.compatible}
					<div class="bg-coral/10 border border-coral/40 rounded-lg p-4 mb-4">
						<div class="flex items-start gap-2">
							<ShieldAlert size={16} class="text-coral shrink-0 mt-0.5" />
							<div>
								<p class="font-medium text-ink mb-1">Compatibility warning</p>
								{#each preflight.compatibility.warnings as w}
									<p class="text-ink-muted text-xs">{w}</p>
								{/each}
							</div>
						</div>
					</div>
				{/if}

				<div class="space-y-3 mb-4">
					<div class="bg-surface border border-line-soft rounded-lg px-4 py-3">
						<div class="text-xs uppercase tracking-wider text-ink-faint">Source</div>
						<div class="text-ink mt-0.5">{source === "rinkhals" ? "Rinkhals release" : "Anycubic stock firmware"}</div>
					</div>
					<div class="bg-surface border border-line-soft rounded-lg px-4 py-3">
						<div class="text-xs uppercase tracking-wider text-ink-faint">Version</div>
						<div class="text-ink mt-0.5">{version}</div>
					</div>
				</div>

				<div class="bg-surface-warm border border-accent/30 rounded-lg p-3 mb-4 text-xs flex items-start gap-2">
					<AlertTriangle size={14} class="text-accent shrink-0 mt-0.5" />
					<div class="text-ink-muted">
						This will download the SWU, extract it, run the printer's installer, and reboot. The portal will be unreachable for about a minute while the printer restarts. Do not unplug the printer during this process.
					</div>
				</div>

				<label class="flex items-start gap-2 text-xs text-ink-muted mb-4 cursor-pointer">
					<input type="checkbox" bind:checked={dryRun} class="accent-brand mt-0.5" />
					<span>
						<span class="text-ink">Dry-run only</span> &mdash; download and extract the SWU but do not run the installer or reboot. Useful if you want to verify the download path and SWU integrity before committing to a real flash. Off by default.
					</span>
				</label>

				<div class="flex justify-end gap-2">
					<button
						type="button"
						onclick={onClose}
						class="px-4 py-2 text-sm font-medium rounded-md border border-line-soft text-ink-muted hover:bg-surface-warm hover:text-ink transition-colors"
					>
						Cancel
					</button>
					<button
						type="button"
						onclick={doCommit}
						class="px-4 py-2 text-sm font-medium rounded-md bg-brand hover:bg-brand-hover text-white transition-colors"
					>
						{dryRun ? "Run dry-run" : "Confirm install"}
					</button>
				</div>
			{:else if phase === "starting" || phase === "running"}
				<div class="space-y-3">
					<div class="bg-surface border border-line-soft rounded-lg px-4 py-3">
						<div class="text-xs uppercase tracking-wider text-ink-faint">Status</div>
						<div class="text-ink mt-0.5 flex items-center gap-2">
							<Loader2 size={14} class="animate-spin text-brand" />
							{runState?.message ?? "Starting..."}
						</div>
						{#if runState?.dry_run}
							<div class="text-xs text-accent mt-1">Dry-run mode</div>
						{/if}
					</div>

					{#if runState && runState.state === "downloading" && runState.total_mb > 0}
						<div>
							<div class="flex items-center justify-between text-xs mb-1">
								<span class="text-ink-muted">Download</span>
								<span class="text-ink">{runState.download_pct}% ({runState.downloaded_mb.toFixed(1)} / {runState.total_mb.toFixed(1)} MB)</span>
							</div>
							<div class="h-2 bg-surface-warm rounded-full overflow-hidden">
								<div class="h-full bg-brand transition-all duration-300" style="width: {runState.download_pct}%"></div>
							</div>
						</div>
					{/if}

					{#if progressLog.length > 0}
						<details open class="text-xs">
							<summary class="cursor-pointer text-ink-muted hover:text-ink select-none">Install log ({progressLog.length} lines)</summary>
							<pre class="mt-2 bg-surface-warm border border-line-soft rounded-md p-3 text-[11px] leading-relaxed max-h-64 overflow-auto whitespace-pre-wrap text-ink-2">{progressLog.join('\n')}</pre>
						</details>
					{/if}
				</div>
			{:else if phase === "rebooting"}
				<div class="text-center py-4">
					<Loader2 size={28} class="animate-spin text-brand mx-auto mb-3" />
					<p class="text-ink font-medium mb-1">Printer is rebooting</p>
					<p class="text-ink-muted text-xs mb-4">
						The portal will reconnect automatically when the printer is back online. This usually takes about a minute.
					</p>
					{#if progressLog.length > 0}
						<details class="text-xs text-left">
							<summary class="cursor-pointer text-ink-muted hover:text-ink select-none">Install log ({progressLog.length} lines)</summary>
							<pre class="mt-2 bg-surface-warm border border-line-soft rounded-md p-3 text-[11px] leading-relaxed max-h-48 overflow-auto whitespace-pre-wrap text-ink-2 text-left">{progressLog.join('\n')}</pre>
						</details>
					{/if}
				</div>
			{:else if phase === "complete"}
				<div class="text-center py-4">
					<CheckCircle2 size={28} class="text-emerald mx-auto mb-3" />
					<p class="text-ink font-medium mb-1">{runState?.dry_run ? "Dry-run complete" : "Install complete"}</p>
					<p class="text-ink-muted text-xs mb-4">
						{#if runState?.dry_run}
							The SWU was downloaded and extracted successfully. No system changes were made.
						{:else}
							The printer has rebooted and is back online. Reload the page to see the updated firmware status.
						{/if}
					</p>
					<div class="flex justify-center gap-2">
						<button
							type="button"
							onclick={onClose}
							class="px-4 py-2 text-sm font-medium rounded-md border border-line-soft text-ink-muted hover:bg-surface-warm hover:text-ink transition-colors"
						>
							Close
						</button>
						{#if !runState?.dry_run}
							<button
								type="button"
								onclick={reload}
								class="px-4 py-2 text-sm font-medium rounded-md bg-brand hover:bg-brand-hover text-white transition-colors"
							>
								Reload portal
							</button>
						{/if}
					</div>
				</div>
			{:else if phase === "failed"}
				<div class="bg-coral/10 border border-coral/40 rounded-lg p-4 mb-4">
					<div class="flex items-start gap-2">
						<ShieldAlert size={16} class="text-coral shrink-0 mt-0.5" />
						<div class="text-xs">
							<p class="font-medium text-ink mb-1">Install failed</p>
							<p class="text-ink-muted">{commitError || preflightError || runState?.error || "Unknown failure"}</p>
						</div>
					</div>
				</div>
				{#if progressLog.length > 0}
					<details open class="text-xs mb-4">
						<summary class="cursor-pointer text-ink-muted hover:text-ink select-none">Install log ({progressLog.length} lines)</summary>
						<pre class="mt-2 bg-surface-warm border border-line-soft rounded-md p-3 text-[11px] leading-relaxed max-h-64 overflow-auto whitespace-pre-wrap text-ink-2">{progressLog.join('\n')}</pre>
					</details>
				{/if}
				<div class="flex justify-end gap-2">
					<button
						type="button"
						onclick={onClose}
						class="px-4 py-2 text-sm font-medium rounded-md border border-line-soft text-ink-muted hover:bg-surface-warm hover:text-ink transition-colors"
					>
						Close
					</button>
				</div>
			{/if}
		</div>
	</div>
</div>
