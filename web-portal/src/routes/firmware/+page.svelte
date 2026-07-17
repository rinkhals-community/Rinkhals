<script lang="ts">
	import { onMount } from "svelte";
	import {
		Cpu,
		RefreshCw,
		FileText,
		Download,
		AlertCircle,
		CheckCircle2,
		Info,
		Beaker
	} from "lucide-svelte";
	import { printerState } from "$lib/printerState";
	import { firmwareStatus } from "$lib/firmwareStatus";
	import ReleaseNotesModal from "$lib/ReleaseNotesModal.svelte";
	import InstallModal from "$lib/InstallModal.svelte";

	// ---- Wire-shape types (must match firmware.go) ---------------------------

	interface AnycubicVersion {
		version: string;
		date: number;
		changes?: string;
		md5?: string;
		url: string;
		current: boolean;
	}
	interface AnycubicCatalog {
		model_code: string;
		model_name: string;
		versions: AnycubicVersion[];
		fetched_at: string;
		notice?: string;
	}
	interface RinkhalsRelease {
		tag: string;
		name: string;
		published_at: string;
		url: string;
		body: string;
		is_prerelease: boolean;
		current: boolean;
		asset_url?: string;
		asset_size?: number;
	}
	interface RinkhalsCatalog {
		releases: RinkhalsRelease[];
		fetched_at: string;
	}

	const apiHost = import.meta.env.DEV ? "http://localhost:8090" : "";

	type Tab = "anycubic" | "rinkhals";
	let tab = $state<Tab>("rinkhals");
	let includePrerelease = $state(false);

	let anycubic = $state<AnycubicCatalog | null>(null);
	let rinkhals = $state<RinkhalsCatalog | null>(null);
	let loadingAnycubic = $state(true);
	let loadingRinkhals = $state(true);
	let errAnycubic = $state<string | null>(null);
	let errRinkhals = $state<string | null>(null);
	let refreshing = $state(false);

	// Release-notes modal state. The body lives in the catalog already so the
	// modal doesn't need to refetch.
	let modalRelease = $state<{
		title: string;
		subtitle: string;
		body: string;
		url: string;
	} | null>(null);

	// Install modal state. The backend's preflight + commit + SSE handles the
	// actual flow; this modal just orchestrates the UI around it.
	let modalInstall = $state<{
		source: "rinkhals" | "anycubic";
		version: string;
		assetUrl: string;
		title: string;
		subtitle: string;
	} | null>(null);

	function openRinkhalsInstall(r: RinkhalsRelease) {
		if (!r.asset_url) return;
		modalInstall = {
			source: "rinkhals",
			version: r.tag,
			assetUrl: r.asset_url,
			title: r.current ? `Reinstall Rinkhals ${r.tag}` : `Install Rinkhals ${r.tag}`,
			subtitle: r.name || r.tag
		};
	}

	function openAnycubicInstall(v: AnycubicVersion) {
		if (!v.url) return;
		modalInstall = {
			source: "anycubic",
			version: v.version,
			assetUrl: v.url,
			title: v.current ? `Reinstall Anycubic ${v.version}` : `Install Anycubic ${v.version}`,
			subtitle: `Stock firmware ${v.version}`
		};
	}

	async function loadAnycubic() {
		loadingAnycubic = true;
		errAnycubic = null;
		try {
			const res = await fetch(`${apiHost}/api/firmware/anycubic`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			anycubic = await res.json();
		} catch (e: any) {
			errAnycubic = e.message || "Failed to load Anycubic catalog";
		} finally {
			loadingAnycubic = false;
		}
	}

	async function loadRinkhals() {
		loadingRinkhals = true;
		errRinkhals = null;
		try {
			const params = includePrerelease ? "?include_prerelease=1" : "";
			const res = await fetch(`${apiHost}/api/firmware/rinkhals${params}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			rinkhals = await res.json();
		} catch (e: any) {
			errRinkhals = e.message || "Failed to load Rinkhals releases";
		} finally {
			loadingRinkhals = false;
		}
	}

	async function refreshAll() {
		refreshing = true;
		try {
			await fetch(`${apiHost}/api/firmware/refresh`, { method: "POST" });
			// Re-fetch both feeds; the backend cache was busted by /refresh.
			await Promise.all([loadAnycubic(), loadRinkhals()]);
		} catch {
			// Errors surface through the per-feed states.
		} finally {
			refreshing = false;
		}
	}

	function reloadRinkhalsForToggle() {
		// Triggered by the prerelease toggle. The server cache holds the full
		// list regardless of the flag, so this re-renders without an upstream hit.
		loadRinkhals();
	}

	function formatUnix(ts?: number): string {
		if (!ts) return "";
		try {
			return new Date(ts * 1000).toLocaleDateString(undefined, {
				year: "numeric",
				month: "short",
				day: "numeric"
			});
		} catch {
			return "";
		}
	}

	function formatISO(iso?: string): string {
		if (!iso) return "";
		try {
			return new Date(iso).toLocaleDateString(undefined, {
				year: "numeric",
				month: "short",
				day: "numeric"
			});
		} catch {
			return "";
		}
	}

	function formatSize(bytes?: number): string {
		if (!bytes || bytes <= 0) return "";
		const mb = bytes / (1024 * 1024);
		if (mb < 1) return `${(bytes / 1024).toFixed(0)} KB`;
		return `${mb.toFixed(1)} MB`;
	}

	function openAnycubicNotes(v: AnycubicVersion) {
		modalRelease = {
			title: `Anycubic firmware ${v.version}`,
			subtitle: formatUnix(v.date),
			body: v.changes ?? "",
			url: ""
		};
	}

	function openRinkhalsNotes(r: RinkhalsRelease) {
		modalRelease = {
			title: r.name || `Rinkhals ${r.tag}`,
			subtitle: formatISO(r.published_at),
			body: r.body,
			url: r.url
		};
	}

	// Whether installs of any kind are allowed right now. Same source of truth
	// as the Apps page; Phase 2 will wire up the actual install handlers behind
	// these gates. For Phase 1B all install buttons are disabled regardless
	// (the install flow doesn't exist yet) but we still gate on can_install
	// so the disabled-reason tooltip matches reality when a print is running.
	const canInstall = $derived($printerState.can_install);

	onMount(() => {
		loadAnycubic();
		loadRinkhals();
	});
</script>

<header class="mb-6 flex items-start justify-between gap-4 flex-wrap">
	<div>
		<div class="text-xs uppercase tracking-wider text-ink-faint mb-1">Firmware</div>
		<h1 class="text-3xl font-semibold tracking-tight text-ink flex items-center gap-3">
			<Cpu size={28} class="text-brand" /> Firmware
		</h1>
		<p class="text-sm text-ink-muted mt-1">
			Browse available Anycubic stock firmware and Rinkhals releases for this printer.
			{#if $firmwareStatus.model_name}
				Current device: <span class="text-ink">{$firmwareStatus.model_name}</span>.
			{/if}
		</p>
	</div>
	<button
		type="button"
		onclick={refreshAll}
		disabled={refreshing}
		class="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg border border-line-soft text-ink-muted hover:bg-surface-warm hover:text-ink disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
		title="Re-fetch the upstream catalogs"
	>
		<RefreshCw size={14} class={refreshing ? "animate-spin" : ""} />
		{refreshing ? "Refreshing..." : "Refresh catalogs"}
	</button>
</header>

<!-- "Currently installed" summary card. Always visible regardless of tab. -->
<section class="bg-surface border border-line-soft rounded-xl p-5 mb-5">
	<div class="grid grid-cols-1 md:grid-cols-2 gap-5">
		<div>
			<div class="text-xs uppercase tracking-wider text-ink-faint mb-1">Anycubic firmware (installed)</div>
			<div class="text-xl font-semibold text-ink">
				{$firmwareStatus.current_firmware || "Unknown"}
			</div>
			{#if $firmwareStatus.latest_firmware}
				<div class="mt-1 text-xs text-ink-muted">
					Latest available: <span class="text-ink">{$firmwareStatus.latest_firmware}</span>
					{#if $firmwareStatus.firmware_update_available}
						<span class="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-brand/10 text-brand text-[10px] font-semibold uppercase tracking-wider">
							Update available
						</span>
					{:else}
						<span class="ml-2 inline-flex items-center gap-1 text-emerald text-xs">
							<CheckCircle2 size={12} /> Up to date
						</span>
					{/if}
				</div>
			{/if}
		</div>
		<div>
			<div class="text-xs uppercase tracking-wider text-ink-faint mb-1">Rinkhals (installed)</div>
			<div class="text-xl font-semibold text-ink">
				{$firmwareStatus.current_rinkhals || "Unknown"}
			</div>
			{#if $firmwareStatus.latest_rinkhals}
				<div class="mt-1 text-xs text-ink-muted">
					Latest release: <span class="text-ink">{$firmwareStatus.latest_rinkhals}</span>
					{#if $firmwareStatus.rinkhals_update_available}
						<span class="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-brand/10 text-brand text-[10px] font-semibold uppercase tracking-wider">
							Update available
						</span>
					{:else}
						<span class="ml-2 inline-flex items-center gap-1 text-emerald text-xs">
							<CheckCircle2 size={12} /> Up to date
						</span>
					{/if}
				</div>
			{/if}
		</div>
	</div>
	{#if $firmwareStatus.notice}
		<div class="mt-4 text-xs text-ink-muted flex items-center gap-1.5">
			<Info size={12} /> {$firmwareStatus.notice}
		</div>
	{/if}
</section>

<!-- Print-state banner: same shape and wording family as the Apps page so
     "installs are blocked right now" reads consistently across the portal. -->
{#if !canInstall}
	<div class="bg-surface-warm border border-accent/40 rounded-xl px-4 py-3 mb-5 flex items-start gap-3">
		<AlertCircle size={18} class="text-accent shrink-0 mt-0.5" />
		<div class="flex-1 text-sm">
			<p class="font-medium text-ink">Printer is busy</p>
			<p class="text-ink-muted mt-0.5">
				{$printerState.reason ?? "A print is in progress"}. Firmware installs are disabled until the print completes. You can still browse versions and read release notes.
			</p>
		</div>
	</div>
{/if}

<!-- Tabs -->
<div class="mb-4 inline-flex rounded-lg border border-line-soft overflow-hidden">
	<button
		type="button"
		onclick={() => (tab = "rinkhals")}
		class="px-4 py-2 text-sm font-medium transition-colors {tab === 'rinkhals' ? 'bg-brand text-white' : 'text-ink-muted hover:bg-surface-warm'}"
	>
		Rinkhals releases
	</button>
	<button
		type="button"
		onclick={() => (tab = "anycubic")}
		class="px-4 py-2 text-sm font-medium transition-colors border-l border-line-soft {tab === 'anycubic' ? 'bg-brand text-white' : 'text-ink-muted hover:bg-surface-warm'}"
	>
		Anycubic stock firmware
	</button>
</div>

{#if tab === "rinkhals"}
	<section>
		<div class="flex items-center justify-between mb-3">
			<p class="text-xs text-ink-muted">
				Source: <code class="text-[11px]">rinkhals-community/Rinkhals</code> releases
			</p>
			<label class="inline-flex items-center gap-2 text-xs text-ink-muted cursor-pointer">
				<input
					type="checkbox"
					bind:checked={includePrerelease}
					onchange={reloadRinkhalsForToggle}
					class="accent-brand"
				/>
				<Beaker size={12} class="text-ink-faint" />
				Show developer / test releases
			</label>
		</div>

		{#if loadingRinkhals && !rinkhals}
			<p class="text-sm text-ink-muted">Loading Rinkhals releases...</p>
		{:else if errRinkhals}
			<div class="bg-coral/10 border border-coral/40 rounded-lg p-4 text-sm text-ink">
				Could not load Rinkhals releases: {errRinkhals}
			</div>
		{:else if rinkhals && rinkhals.releases.length === 0}
			<p class="text-sm text-ink-muted italic">No releases match the current filter.</p>
		{:else if rinkhals}
			<div class="space-y-3">
				{#each rinkhals.releases as r}
					<article class="bg-surface border border-line-soft rounded-xl p-4 flex items-start gap-4">
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2 flex-wrap">
								<h3 class="text-base font-semibold text-ink truncate">{r.name || r.tag}</h3>
								<code class="text-[11px] text-ink-muted">{r.tag}</code>
								{#if r.current}
									<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-emerald/15 text-emerald text-[10px] font-semibold uppercase tracking-wider">
										<CheckCircle2 size={10} /> Installed
									</span>
								{/if}
								{#if r.is_prerelease}
									<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-accent/15 text-accent text-[10px] font-semibold uppercase tracking-wider">
										<Beaker size={10} /> Test build
									</span>
								{/if}
							</div>
							<div class="mt-1 text-xs text-ink-muted">
								Published {formatISO(r.published_at)}
								{#if r.asset_size}
									<span class="mx-1.5 text-ink-faint">|</span>
									Update bundle: {formatSize(r.asset_size)}
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-2 shrink-0">
							<button
								type="button"
								onclick={() => openRinkhalsNotes(r)}
								class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-line-soft text-ink-muted hover:bg-surface-warm hover:text-ink transition-colors"
							>
								<FileText size={12} /> Release notes
							</button>
							<button
								type="button"
								onclick={() => openRinkhalsInstall(r)}
								disabled={!canInstall || !r.asset_url}
								title={!canInstall ? ($printerState.reason || "Disabled while printer is busy") : (!r.asset_url ? "No update bundle available for this printer model" : (r.current ? "Reinstall this Rinkhals release" : "Install this Rinkhals release"))}
								class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-brand text-white hover:bg-brand-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
							>
								<Download size={12} /> {r.current ? "Reinstall" : "Install"}
							</button>
						</div>
					</article>
				{/each}
			</div>
		{/if}
	</section>
{:else if tab === "anycubic"}
	<section>
		<p class="text-xs text-ink-muted mb-3">
			Source: community-curated <code class="text-[11px]">Rinkhals.Firmwares</code> manifest. Anycubic does not publish a release feed directly.
		</p>

		{#if loadingAnycubic && !anycubic}
			<p class="text-sm text-ink-muted">Loading Anycubic firmware catalog...</p>
		{:else if errAnycubic}
			<div class="bg-coral/10 border border-coral/40 rounded-lg p-4 text-sm text-ink">
				Could not load Anycubic firmware catalog: {errAnycubic}
			</div>
		{:else if anycubic && anycubic.versions.length === 0}
			<p class="text-sm text-ink-muted italic">No Anycubic firmware versions found in the manifest.</p>
		{:else if anycubic}
			<div class="space-y-3">
				{#each anycubic.versions as v}
					<article class="bg-surface border border-line-soft rounded-xl p-4 flex items-start gap-4">
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2 flex-wrap">
								<h3 class="text-base font-semibold text-ink">{v.version}</h3>
								{#if v.current}
									<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-emerald/15 text-emerald text-[10px] font-semibold uppercase tracking-wider">
										<CheckCircle2 size={10} /> Installed
									</span>
								{/if}
							</div>
							<div class="mt-1 text-xs text-ink-muted">
								Released {formatUnix(v.date)}
								{#if v.md5}
									<span class="mx-1.5 text-ink-faint">|</span>
									<code class="text-[11px]">md5 {v.md5.slice(0, 8)}</code>
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-2 shrink-0">
							<button
								type="button"
								onclick={() => openAnycubicNotes(v)}
								disabled={!v.changes}
								title={v.changes ? "" : "No changelog provided in manifest"}
								class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-line-soft text-ink-muted hover:bg-surface-warm hover:text-ink disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
							>
								<FileText size={12} /> Changelog
							</button>
							<button
								type="button"
								onclick={() => openAnycubicInstall(v)}
								disabled={!canInstall || !v.url}
								title={!canInstall ? ($printerState.reason || "Disabled while printer is busy") : (v.current ? "Reinstall this stock firmware version" : "Install this stock firmware version")}
								class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-brand text-white hover:bg-brand-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
							>
								<Download size={12} /> {v.current ? "Reinstall" : "Install"}
							</button>
						</div>
					</article>
				{/each}
			</div>
		{/if}
	</section>
{/if}

{#if modalRelease}
	<ReleaseNotesModal
		title={modalRelease.title}
		subtitle={modalRelease.subtitle}
		body={modalRelease.body}
		externalUrl={modalRelease.url}
		onClose={() => (modalRelease = null)}
	/>
{/if}

{#if modalInstall}
	<InstallModal
		source={modalInstall.source}
		version={modalInstall.version}
		assetUrl={modalInstall.assetUrl}
		title={modalInstall.title}
		subtitle={modalInstall.subtitle}
		onClose={() => (modalInstall = null)}
	/>
{/if}
