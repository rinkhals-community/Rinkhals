<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import QRCode from "qrcode";
	import ReportField from "$lib/ReportField.svelte";
	import { printerState } from "$lib/printerState";
	import {
		Boxes,
		Play,
		Square,
		RotateCw,
		Sliders,
		Cpu,
		HardDrive,
		Search,
		X,
		RotateCcw,
		Loader2,
		AlertCircle,
		Download,
		CheckCircle2,
		RefreshCw,
		Package,
		ExternalLink,
		Trash2,
		AlertTriangle,
		Copy,
		Check
	} from "lucide-svelte";

	type Property = {
		key: string;
		display: string;
		type: string;
		options?: string[];
		default: string;
		value: string;
		overridden: boolean;
		advanced?: boolean;
	};

	type App = {
		id: string;
		name: string;
		description: string;
		version: string;
		source: "system" | "user";
		enabled: boolean;
		running: boolean;
		requirements?: { memory?: number; cpu?: number };
		properties: Property[];
	};

	type CatalogApp = {
		id: string;
		name: string;
		description: string;
		version: string;
		requirements?: { memory?: number; cpu?: number };
		depends?: string[];
		available_for_model: boolean;
		download_url?: string;
		asset_size?: number;
		installed: boolean;
		installed_version?: string;
		upstream?: { type: string; repo: string; strip_prefix?: string; branch?: string };
		upstream_version?: string;
		upstream_url?: string;
	};

	type Catalog = {
		release: string;
		fetched_at: string;
		model: string;
		asset_group: string;
		apps: CatalogApp[];
		notice?: string;
	};

	const apiHost = import.meta.env.DEV ? "http://localhost:8090" : "";

	let tab = $state<"installed" | "catalog">("installed");

	// Show-advanced is UX gating, not a security boundary. Persisted so the
	// preference survives reloads; default off so the typical user sees only
	// the knobs the app author considered safe to expose.
	let showAdvanced = $state(false);
	if (typeof window !== "undefined") {
		showAdvanced = window.localStorage.getItem("rinkhals-show-advanced") === "1";
	}
	$effect(() => {
		if (typeof window === "undefined") return;
		window.localStorage.setItem("rinkhals-show-advanced", showAdvanced ? "1" : "0");
	});

	// A property is shown when it isn't advanced, or when the user has opted in.
	function visibleProperties(props: Property[]): Property[] {
		return props.filter((p) => showAdvanced || !p.advanced);
	}
	function hasVisibleProperties(app: App): boolean {
		return visibleProperties(app.properties).length > 0;
	}

	let apps = $state<App[]>([]);
	let loading = $state(true);
	let error = $state("");

	let catalog = $state<Catalog | null>(null);
	let catalogLoading = $state(false);
	let catalogError = $state("");
	let installingId = $state<string | null>(null);

	let searchQuery = $state("");
	let stateFilter = $state<"all" | "enabled" | "disabled" | "running">("all");
	let sourceFilter = $state<"all" | "system" | "user">("all");
	let catalogSearch = $state("");

	let busyApps = $state<Set<string>>(new Set());
	let uninstallTarget = $state<App | null>(null);
	let uninstallRunning = $state(false);
	let configureApp = $state<App | null>(null);

	// Per-card description expansion. We only show the "Show more" affordance
	// when the description is actually overflowing its clamp, measured at
	// runtime so the threshold is correct regardless of viewport width or
	// font size. Card ids are unique across both tabs (installed app id ==
	// catalog app id for the same app), so a single Map works for both.
	let truncatedDescs = $state<Set<string>>(new Set());
	let expandedDescs = $state<Set<string>>(new Set());

	// Render a URL into a canvas as a QR code. The action re-renders whenever
	// the URL parameter changes, so polling /api/apps and seeing the property
	// value update automatically refreshes the displayed QR without any
	// manual coordination from the caller.
	function qrCanvas(node: HTMLCanvasElement, url: string) {
		const render = (value: string) => {
			if (!value) return;
			QRCode.toCanvas(node, value, {
				margin: 1,
				width: 220,
				color: { dark: "#1a1a1a", light: "#ffffff" },
				errorCorrectionLevel: "M"
			}).catch((e) => console.error("QR render failed", e));
		};
		render(url);
		return {
			update(newUrl: string) {
				render(newUrl);
			}
		};
	}

	let copiedKey = $state<string | null>(null);
	async function copyToClipboard(key: string, text: string) {
		try {
			await navigator.clipboard.writeText(text);
			copiedKey = key;
			setTimeout(() => {
				if (copiedKey === key) copiedKey = null;
			}, 1500);
		} catch (e) {
			showToast("Copy failed", "err");
		}
	}

	function toggleDesc(id: string) {
		const next = new Set(expandedDescs);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expandedDescs = next;
	}

	// Svelte action: measures whether the clamped description is overflowing
	// and adds the id to truncatedDescs if so. Re-checks on viewport resize.
	// Skipped while the card is expanded (no clamp -> would always look like
	// it fits, which would hide the toggle button mid-interaction).
	function descAction(node: HTMLElement, currentId: string) {
		let id = currentId;
		const check = () => {
			requestAnimationFrame(() => {
				if (expandedDescs.has(id)) return;
				const overflows = node.scrollHeight > node.clientHeight + 1;
				const has = truncatedDescs.has(id);
				if (overflows && !has) {
					truncatedDescs = new Set([...truncatedDescs, id]);
				} else if (!overflows && has) {
					const next = new Set(truncatedDescs);
					next.delete(id);
					truncatedDescs = next;
				}
			});
		};
		check();
		const ro = new ResizeObserver(check);
		ro.observe(node);
		return {
			update(newId: string) {
				id = newId;
				check();
			},
			destroy() {
				ro.disconnect();
			}
		};
	}
	let pendingConfig = $state<Record<string, string>>({});
	let configSaving = $state(false);
	let toast = $state<{ text: string; tone: "ok" | "err" } | null>(null);

	let pollHandle: ReturnType<typeof setInterval> | undefined;

	async function fetchApps() {
		try {
			const res = await fetch(`${apiHost}/api/apps`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const fresh: App[] = await res.json();
			apps = fresh;
			error = "";
		} catch (e: any) {
			error = e.message || String(e);
		} finally {
			loading = false;
		}
	}

	async function fetchCatalog(force = false) {
		catalogLoading = true;
		try {
			const url = `${apiHost}/api/catalog${force ? "?refresh=1" : ""}`;
			const res = await fetch(url);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			catalog = await res.json();
			catalogError = "";
		} catch (e: any) {
			catalogError = e.message || String(e);
		} finally {
			catalogLoading = false;
		}
	}

	async function installCatalogApp(entry: CatalogApp) {
		if (!entry.available_for_model || !entry.download_url) return;
		installingId = entry.id;
		try {
			const res = await fetch(`${apiHost}/api/catalog/${entry.id}/install`, { method: "POST" });
			const data = await res.json().catch(() => ({}));
			if (!res.ok || data.success === false) {
				throw new Error(data.output || `HTTP ${res.status}`);
			}
			// Refresh installed list first so we can locate the new app below.
			await Promise.all([fetchApps(), fetchCatalog(true)]);

			if (data.needs_config) {
				// Left disabled on purpose: open the configure drawer so the user
				// can set required values, then enable from there.
				showToast(`${entry.name} installed — configure it, then enable`);
				tab = "installed";
				const installed = apps.find((a) => a.id === entry.id);
				if (installed) openConfigure(installed);
			} else if (data.auto_enabled) {
				showToast(`${entry.name} installed and started`);
			} else {
				showToast(`${entry.name} installed`);
			}
		} catch (e: any) {
			showToast(e.message || "Install failed", "err");
		} finally {
			installingId = null;
		}
	}

	// Enable + start an app, optionally saving pending config first. Used by the
	// configure drawer to complete the "configure then enable" flow for apps that
	// were installed but left disabled because they needed configuration.
	async function saveAndEnable(app: App) {
		if (hasPendingChanges()) {
			await saveConfig();
		}
		try {
			await callApp(app.id, "/enable", { method: "POST" });
			await callApp(app.id, "/action", {
				method: "POST",
				body: JSON.stringify({ action: "start" })
			});
			showToast(`${app.name} enabled and started`);
			const refreshed = apps.find((a) => a.id === app.id);
			if (refreshed) configureApp = refreshed;
		} catch {
			// callApp already surfaced an error toast
		}
	}

	onMount(() => {
		fetchApps();
		fetchCatalog(false);
		pollHandle = setInterval(fetchApps, 5000);
	});

	onDestroy(() => {
		if (pollHandle) clearInterval(pollHandle);
	});

	function showToast(text: string, tone: "ok" | "err" = "ok") {
		toast = { text, tone };
		setTimeout(() => {
			toast = null;
		}, 2500);
	}

	function markBusy(id: string, on: boolean) {
		const next = new Set(busyApps);
		if (on) next.add(id);
		else next.delete(id);
		busyApps = next;
	}

	async function callApp(id: string, path: string, init: RequestInit = {}) {
		markBusy(id, true);
		try {
			const res = await fetch(`${apiHost}/api/apps/${id}${path}`, {
				...init,
				headers: { "Content-Type": "application/json", ...(init.headers || {}) }
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json().catch(() => ({}));
			if (data && data.success === false) {
				throw new Error(data.output || "Operation failed");
			}
			await fetchApps();
			return data;
		} catch (e: any) {
			showToast(e.message || "Operation failed", "err");
			throw e;
		} finally {
			markBusy(id, false);
		}
	}

	async function toggleEnabled(app: App) {
		try {
			await callApp(app.id, app.enabled ? "/disable" : "/enable", { method: "POST" });
			showToast(`${app.name} ${app.enabled ? "disabled" : "enabled"}`);
		} catch {
			// toast already shown
		}
	}

	async function confirmUninstall(app: App) {
		if (app.source !== "user") return;
		uninstallTarget = app;
	}

	async function performUninstall() {
		if (!uninstallTarget) return;
		const app = uninstallTarget;
		uninstallRunning = true;
		try {
			const res = await fetch(`${apiHost}/api/apps/${app.id}`, { method: "DELETE" });
			const data = await res.json().catch(() => ({}));
			if (!res.ok || data.success === false) {
				throw new Error(data.output || `HTTP ${res.status}`);
			}
			showToast(`${app.name} uninstalled`);
			// If the drawer is open on this app, close it: the app is gone.
			if (configureApp?.id === app.id) configureApp = null;
			// Refresh both lists. The catalog's "Installed" pill should flip back to "Install".
			await Promise.all([fetchApps(), fetchCatalog(true)]);
		} catch (e: any) {
			showToast(e.message || "Uninstall failed", "err");
		} finally {
			uninstallRunning = false;
			uninstallTarget = null;
		}
	}

	async function runAction(app: App, action: "start" | "stop" | "restart") {
		try {
			await callApp(app.id, "/action", {
				method: "POST",
				body: JSON.stringify({ action })
			});
			showToast(`${app.name}: ${action} sent`);
		} catch {}
	}

	function openConfigure(app: App) {
		configureApp = app;
		pendingConfig = {};
	}

	function closeConfigure() {
		configureApp = null;
		pendingConfig = {};
	}

	function pendingValue(prop: Property): string {
		return pendingConfig[prop.key] ?? prop.value;
	}

	function hasPendingChanges(): boolean {
		return Object.keys(pendingConfig).length > 0;
	}

	async function saveConfig() {
		if (!configureApp || !hasPendingChanges()) return;
		configSaving = true;
		try {
			const res = await fetch(`${apiHost}/api/apps/${configureApp.id}/config`, {
				method: "PUT",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(pendingConfig)
			});
			const data = await res.json().catch(() => ({}));
			if (!res.ok || data.success === false) {
				throw new Error(data.output || `HTTP ${res.status}`);
			}
			showToast("Configuration saved");
			await fetchApps();
			const refreshed = apps.find((a) => a.id === configureApp!.id);
			if (refreshed) configureApp = refreshed;
			pendingConfig = {};
		} catch (e: any) {
			showToast(e.message || "Save failed", "err");
		} finally {
			configSaving = false;
		}
	}

	async function resetProperty(prop: Property) {
		if (!configureApp) return;
		try {
			const res = await fetch(`${apiHost}/api/apps/${configureApp.id}/config/${prop.key}`, {
				method: "DELETE"
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			showToast(`${prop.display || prop.key} reset to default`);
			const fresh = { ...pendingConfig };
			delete fresh[prop.key];
			pendingConfig = fresh;
			await fetchApps();
			const refreshed = apps.find((a) => a.id === configureApp!.id);
			if (refreshed) configureApp = refreshed;
		} catch (e: any) {
			showToast(e.message || "Reset failed", "err");
		}
	}

	async function clearAllOverrides() {
		if (!configureApp) return;
		try {
			const res = await fetch(`${apiHost}/api/apps/${configureApp.id}/config`, {
				method: "DELETE"
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			showToast("All overrides cleared");
			pendingConfig = {};
			await fetchApps();
			const refreshed = apps.find((a) => a.id === configureApp!.id);
			if (refreshed) configureApp = refreshed;
		} catch (e: any) {
			showToast(e.message || "Clear failed", "err");
		}
	}

	let visibleCatalog = $derived(
		(catalog?.apps ?? []).filter((a) => {
			if (!catalogSearch) return true;
			const q = catalogSearch.toLowerCase();
			return (
				a.id.toLowerCase().includes(q) ||
				a.name.toLowerCase().includes(q) ||
				(a.description || "").toLowerCase().includes(q)
			);
		})
	);

	function formatSize(bytes?: number): string {
		if (!bytes || bytes <= 0) return "";
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function relativeTime(iso?: string): string {
		if (!iso) return "";
		try {
			const then = new Date(iso).getTime();
			const diffMs = Date.now() - then;
			const m = Math.floor(diffMs / 60000);
			if (m < 1) return "just now";
			if (m < 60) return `${m}m ago`;
			const h = Math.floor(m / 60);
			if (h < 24) return `${h}h ago`;
			return `${Math.floor(h / 24)}d ago`;
		} catch {
			return "";
		}
	}

	let visibleApps = $derived(
		apps.filter((a) => {
			if (searchQuery) {
				const q = searchQuery.toLowerCase();
				if (
					!a.id.toLowerCase().includes(q) &&
					!a.name.toLowerCase().includes(q) &&
					!(a.description || "").toLowerCase().includes(q)
				) {
					return false;
				}
			}
			if (stateFilter === "enabled" && !a.enabled) return false;
			if (stateFilter === "disabled" && a.enabled) return false;
			if (stateFilter === "running" && !a.running) return false;
			if (sourceFilter !== "all" && a.source !== sourceFilter) return false;
			return true;
		})
	);

	function statusPill(app: App): { label: string; classes: string } {
		if (!app.enabled) {
			return {
				label: "Disabled",
				classes: "bg-surface-accent text-ink-faint border-line-soft"
			};
		}
		if (app.running) {
			return {
				label: "Running",
				classes: "bg-brand-soft text-brand border-brand/30"
			};
		}
		return {
			label: "Stopped",
			classes: "bg-surface-warm text-accent-hover border-accent/30"
		};
	}
</script>

<svelte:head>
	<title>Apps - Rinkhals</title>
</svelte:head>

<div class="space-y-6 max-w-7xl mx-auto w-full">
	<header class="pb-4 border-b border-line-soft">
		<!-- Row 1: title + tab toggle (fixed positions) -->
		<div class="flex items-start justify-between gap-4">
			<div class="min-w-0">
				<p class="text-xs uppercase tracking-wider text-ink-faint font-medium">Apps</p>
				<h2 class="text-3xl font-semibold text-ink mt-1 tracking-tight flex items-center gap-2">
					<Boxes size={26} class="text-brand" />
					Apps
				</h2>
				<!-- Reserved subtitle slot; height fixed so swapping text doesn't shift layout -->
				<p class="text-ink-muted text-sm mt-2 h-5">
					{tab === "installed"
						? "Enable, start and configure the apps installed on this printer."
						: "Discover and install community apps from Rinkhals.Apps."}
				</p>
			</div>

			<div class="inline-flex bg-surface border border-line-soft rounded-lg p-0.5 shrink-0">
				<button
					type="button"
					onclick={() => (tab = "installed")}
					class="px-3 py-1.5 rounded-md text-sm font-medium transition-colors {tab === 'installed' ? 'bg-canvas text-brand shadow-sm' : 'text-ink-muted hover:text-ink'}"
				>
					Installed
				</button>
				<button
					type="button"
					onclick={() => (tab = "catalog")}
					class="px-3 py-1.5 rounded-md text-sm font-medium transition-colors {tab === 'catalog' ? 'bg-canvas text-brand shadow-sm' : 'text-ink-muted hover:text-ink'}"
				>
					Catalog
				</button>
			</div>
		</div>

		<!-- Row 2: filter slot, fixed height, contents swap per tab. The flex
		     wrapper has a stable min-height so the row below it never moves. -->
		<div class="flex flex-wrap items-center gap-2 mt-4 min-h-[40px]">
			{#if tab === "installed"}
				<div class="relative">
					<Search class="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" size={15} />
					<input
						bind:value={searchQuery}
						type="text"
						placeholder="Search..."
						class="bg-canvas text-ink rounded-lg pl-9 pr-3 py-2 border border-line-soft focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 text-sm w-52"
					/>
				</div>
				<select
					bind:value={stateFilter}
					class="bg-canvas text-ink border border-line-soft rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
				>
					<option value="all">All states</option>
					<option value="enabled">Enabled</option>
					<option value="disabled">Disabled</option>
					<option value="running">Running</option>
				</select>
				<select
					bind:value={sourceFilter}
					class="bg-canvas text-ink border border-line-soft rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/20"
				>
					<option value="all">All sources</option>
					<option value="system">System</option>
					<option value="user">User</option>
				</select>
				<label
					class="inline-flex items-center gap-2 px-3 py-2 bg-canvas border border-line-soft rounded-lg text-sm text-ink-2 cursor-pointer select-none"
					title="Reveal advanced settings in the Configure drawer"
				>
					<input type="checkbox" bind:checked={showAdvanced} class="rounded border-line text-brand focus:ring-brand/30" />
					<span>Advanced</span>
				</label>
			{:else}
				<div class="relative">
					<Search class="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" size={15} />
					<input
						bind:value={catalogSearch}
						type="text"
						placeholder="Search catalog..."
						class="bg-canvas text-ink rounded-lg pl-9 pr-3 py-2 border border-line-soft focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 text-sm w-52"
					/>
				</div>
				<button
					type="button"
					onclick={() => fetchCatalog(true)}
					disabled={catalogLoading}
					class="flex items-center gap-1.5 px-3 py-2 bg-canvas hover:bg-surface-warm border border-line-soft rounded-lg text-sm text-ink-2 disabled:opacity-50 transition-colors"
				>
					{#if catalogLoading}
						<Loader2 size={14} class="animate-spin" />
					{:else}
						<RefreshCw size={14} />
					{/if}
					Refresh
				</button>
			{/if}
		</div>

		<!-- Row 3: info strip, fixed height. Empty on the Installed tab so
		     switching tabs never shifts the grid below. -->
		<div class="mt-3 h-5 text-[11px] text-ink-faint flex flex-wrap items-center gap-3">
			{#if tab === "catalog" && catalog}
				<span class="inline-flex items-center gap-1">
					<Package size={12} /> Release <span class="font-mono text-ink-muted">{catalog.release || "(unknown)"}</span>
				</span>
				<span>Printer: <span class="font-mono text-ink-muted">{catalog.model || "(unknown)"}</span></span>
				{#if catalog.asset_group}
					<span>SWU group: <span class="font-mono text-ink-muted">{catalog.asset_group}</span></span>
				{/if}
				{#if catalog.fetched_at}
					<span>Fetched {relativeTime(catalog.fetched_at)}</span>
				{/if}
				<a
					href="https://github.com/rinkhals-community/Rinkhals.Apps"
					target="_blank"
					rel="noopener noreferrer"
					class="inline-flex items-center gap-1 text-brand hover:underline ml-auto"
				>
					Source <ExternalLink size={11} />
				</a>
			{/if}
		</div>
	</header>

	{#if !$printerState.can_install}
		<div class="bg-surface-warm border border-accent/40 rounded-xl px-4 py-3 flex items-start gap-3">
			<AlertCircle size={18} class="text-accent shrink-0 mt-0.5" />
			<div class="flex-1 text-sm">
				<p class="font-medium text-ink">Printer is busy</p>
				<p class="text-ink-muted mt-0.5">
					{$printerState.reason ?? "A print is in progress"}. Installs and uninstalls are disabled until the print completes. App start, stop, restart, and Configure remain available.
				</p>
			</div>
		</div>
	{/if}

	{#if tab === "installed"}
	{#if error}
		<div class="bg-surface-accent border border-coral/40 rounded-xl px-4 py-3 text-coral text-sm flex items-center gap-2">
			<AlertCircle size={16} />
			{error}
		</div>
	{/if}

	{#if loading && apps.length === 0}
		<div class="text-ink-faint animate-pulse">Loading apps...</div>
	{:else if visibleApps.length === 0}
		<div class="text-ink-faint italic">No apps match the current filters.</div>
	{:else}
		<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
			{#each visibleApps as app (app.id)}
				{@const pill = statusPill(app)}
				{@const isBusy = busyApps.has(app.id)}
				<div class="bg-canvas border border-line-soft rounded-xl p-5 flex flex-col gap-3 hover:border-brand/40 transition-colors">
					<div class="flex items-start justify-between gap-3">
						<div class="min-w-0">
							<div class="flex items-center gap-2 flex-wrap">
								<h3 class="text-base font-semibold text-ink truncate">{app.name}</h3>
								{#if app.version}
									<span class="text-[11px] text-ink-faint font-mono">v{app.version}</span>
								{/if}
								<span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded {app.source === 'user' ? 'bg-surface-warm text-accent-hover border border-accent/30' : 'bg-surface text-ink-muted border border-line-soft'}">
									{app.source}
								</span>
							</div>
							<p class="text-[11px] text-ink-faint font-mono mt-0.5">{app.id}</p>
						</div>

						<!-- Enable toggle -->
						<button
							type="button"
							onclick={() => toggleEnabled(app)}
							disabled={isBusy}
							title={app.enabled ? "Disable" : "Enable"}
							aria-label="Toggle enabled"
							class="shrink-0 relative inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-50 {app.enabled ? 'bg-brand' : 'bg-surface border border-line-soft'}"
						>
							<span class="inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform {app.enabled ? 'translate-x-6' : 'translate-x-1'}"></span>
						</button>
					</div>

					{#if app.description}
						<div>
							<p
								use:descAction={app.id}
								class="text-sm text-ink-muted {expandedDescs.has(app.id) ? '' : 'line-clamp-2'}"
							>{app.description}</p>
							{#if truncatedDescs.has(app.id) || expandedDescs.has(app.id)}
								<button
									type="button"
									onclick={() => toggleDesc(app.id)}
									class="text-[11px] text-brand hover:underline mt-0.5"
								>
									{expandedDescs.has(app.id) ? 'Show less' : 'Show more'}
								</button>
							{/if}
						</div>
					{/if}

					<div class="flex items-center gap-2 flex-wrap">
						<span class="px-2.5 py-1 rounded-full text-[11px] font-semibold uppercase tracking-wider border {pill.classes}">
							{pill.label}
						</span>
						{#if app.requirements?.memory}
							<span class="inline-flex items-center gap-1 text-[11px] text-ink-faint">
								<HardDrive size={11} /> {app.requirements.memory} MB
							</span>
						{/if}
						{#if app.requirements?.cpu}
							<span class="inline-flex items-center gap-1 text-[11px] text-ink-faint">
								<Cpu size={11} /> {app.requirements.cpu}%
							</span>
						{/if}
					</div>

					<div class="flex items-center gap-2 mt-auto pt-3 border-t border-line-soft">
						{#if app.enabled}
							{#if app.running}
								<button
									type="button"
									onclick={() => runAction(app, "stop")}
									disabled={isBusy}
									class="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface hover:bg-surface-warm border border-line-soft rounded-lg text-xs font-medium text-ink-2 disabled:opacity-50 transition-colors"
								>
									<Square size={13} /> Stop
								</button>
								<button
									type="button"
									onclick={() => runAction(app, "restart")}
									disabled={isBusy}
									class="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface hover:bg-surface-warm border border-line-soft rounded-lg text-xs font-medium text-ink-2 disabled:opacity-50 transition-colors"
								>
									<RotateCw size={13} /> Restart
								</button>
							{:else}
								<button
									type="button"
									onclick={() => runAction(app, "start")}
									disabled={isBusy}
									class="flex items-center gap-1.5 px-2.5 py-1.5 bg-brand hover:bg-brand-hover text-white rounded-lg text-xs font-medium disabled:opacity-50 transition-colors"
								>
									<Play size={13} /> Start
								</button>
							{/if}
						{/if}
						{#if hasVisibleProperties(app)}
							<button
								type="button"
								onclick={() => openConfigure(app)}
								class="ml-auto flex items-center gap-1.5 px-2.5 py-1.5 bg-canvas hover:bg-brand-soft border border-line-soft rounded-lg text-xs font-medium text-brand transition-colors"
							>
								<Sliders size={13} /> Configure
								{#if visibleProperties(app.properties).some((p) => p.overridden)}
									<span class="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-accent" title="Has overrides"></span>
								{/if}
							</button>
						{/if}
						{#if app.source === "user"}
							<button
								type="button"
								onclick={() => confirmUninstall(app)}
								disabled={isBusy || !$printerState.can_install}
								title={!$printerState.can_install ? "Disabled while printer is busy" : "Uninstall this app"}
								aria-label="Uninstall {app.name}"
								class="{hasVisibleProperties(app) ? '' : 'ml-auto '}p-1.5 rounded-lg text-ink-faint hover:text-coral hover:bg-surface-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
							>
								<Trash2 size={14} />
							</button>
						{/if}
						{#if isBusy}
							<Loader2 size={14} class="text-ink-faint animate-spin ml-auto" />
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
	{:else}
		<!-- Catalog tab -->
		{#if catalogError}
			<div class="bg-surface-accent border border-coral/40 rounded-xl px-4 py-3 text-coral text-sm flex items-center gap-2">
				<AlertCircle size={16} />
				{catalogError}
			</div>
		{/if}

		{#if catalog?.notice}
			<div class="bg-surface-warm border border-accent/30 rounded-xl px-4 py-3 text-accent-hover text-sm flex items-center gap-2">
				<AlertCircle size={16} />
				{catalog.notice}
			</div>
		{/if}

		{#if catalogLoading && !catalog}
			<div class="text-ink-faint animate-pulse">Loading catalog from Rinkhals.Apps...</div>
		{:else if !catalog || visibleCatalog.length === 0}
			<div class="text-ink-faint italic">No catalog entries match.</div>
		{:else}
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
				{#each visibleCatalog as entry (entry.id)}
					{@const installing = installingId === entry.id}
					{@const upgradeAvailable = entry.installed && entry.installed_version && entry.version && entry.installed_version !== entry.version}
					<div class="bg-canvas border border-line-soft rounded-xl p-5 flex flex-col gap-3 hover:border-brand/40 transition-colors">
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0">
								<div class="flex items-center gap-2 flex-wrap">
									<h3 class="text-base font-semibold text-ink truncate">{entry.name}</h3>
									{#if entry.version}
										<span class="text-[11px] text-ink-faint font-mono">v{entry.version}</span>
									{/if}
								</div>
								<p class="text-[11px] text-ink-faint font-mono mt-0.5">{entry.id}</p>
							</div>
							{#if entry.installed && !upgradeAvailable}
								<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-brand-soft text-brand text-[11px] font-semibold border border-brand/30">
									<CheckCircle2 size={11} />
									Installed
								</span>
							{:else if upgradeAvailable}
								<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-warm text-accent-hover text-[11px] font-semibold border border-accent/30">
									v{entry.installed_version} -&gt; v{entry.version}
								</span>
							{/if}
						</div>

						{#if entry.description}
							<div>
								<p
									use:descAction={entry.id}
									class="text-sm text-ink-muted {expandedDescs.has(entry.id) ? '' : 'line-clamp-3'}"
								>{entry.description}</p>
								{#if truncatedDescs.has(entry.id) || expandedDescs.has(entry.id)}
									<button
										type="button"
										onclick={() => toggleDesc(entry.id)}
										class="text-[11px] text-brand hover:underline mt-0.5"
									>
										{expandedDescs.has(entry.id) ? 'Show less' : 'Show more'}
									</button>
								{/if}
							</div>
						{/if}

						<div class="flex items-center gap-3 flex-wrap text-[11px] text-ink-faint">
							{#if entry.requirements?.memory}
								<span class="inline-flex items-center gap-1"><HardDrive size={11} /> {entry.requirements.memory} MB</span>
							{/if}
							{#if entry.requirements?.cpu}
								<span class="inline-flex items-center gap-1"><Cpu size={11} /> {entry.requirements.cpu}%</span>
							{/if}
							{#if entry.asset_size}
								<span class="inline-flex items-center gap-1"><Download size={11} /> {formatSize(entry.asset_size)}</span>
							{/if}
						</div>

						{#if entry.upstream_version}
							{@const stale = entry.upstream_version !== entry.version}
							<div class="flex items-center gap-2 text-[11px] {stale ? 'text-coral' : 'text-ink-faint'}">
								<span class="inline-flex items-center gap-1">
									Upstream:
									{#if entry.upstream_url}
										<a href={entry.upstream_url} target="_blank" rel="noopener noreferrer" class="font-mono hover:underline inline-flex items-center gap-0.5">
											{entry.upstream_version}<ExternalLink size={10} />
										</a>
									{:else}
										<span class="font-mono">{entry.upstream_version}</span>
									{/if}
								</span>
								{#if stale}
									<span class="px-1.5 py-0.5 rounded bg-surface-accent border border-coral/30 uppercase tracking-wider text-[9px] font-semibold" title="Bundled v{entry.version} is behind upstream">
										Bundled is behind
									</span>
								{/if}
							</div>
						{/if}

						<div class="flex items-center gap-2 mt-auto pt-3 border-t border-line-soft">
							{#if !entry.available_for_model}
								<span class="text-[11px] text-ink-faint italic">No SWU for this printer</span>
							{:else if entry.installed && !upgradeAvailable}
								<button
									type="button"
									onclick={() => installCatalogApp(entry)}
									disabled={installing || !$printerState.can_install}
									title={!$printerState.can_install ? "Disabled while printer is busy" : "Reinstall this app"}
									class="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface hover:bg-surface-warm border border-line-soft rounded-lg text-xs font-medium text-ink-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
								>
									{#if installing}
										<Loader2 size={13} class="animate-spin" /> Reinstalling...
									{:else}
										<RotateCw size={13} /> Reinstall
									{/if}
								</button>
							{:else}
								<button
									type="button"
									onclick={() => installCatalogApp(entry)}
									disabled={installing || !$printerState.can_install}
									title={!$printerState.can_install ? "Disabled while printer is busy" : (upgradeAvailable ? "Upgrade to the latest version" : "Install this app")}
									class="flex items-center gap-1.5 px-2.5 py-1.5 bg-brand hover:bg-brand-hover text-white rounded-lg text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
								>
									{#if installing}
										<Loader2 size={13} class="animate-spin" /> Installing...
									{:else}
										<Download size={13} /> {upgradeAvailable ? "Upgrade" : "Install"}
									{/if}
								</button>
							{/if}
							{#if entry.download_url}
								<a
									href={entry.download_url}
									target="_blank"
									rel="noopener noreferrer"
									class="ml-auto text-[11px] text-ink-faint hover:text-brand inline-flex items-center gap-1"
									title="Download SWU directly"
								>
									SWU <ExternalLink size={11} />
								</a>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>

<!-- Configure drawer -->
{#if configureApp}
	{@const app = configureApp}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-ink/40 backdrop-blur-sm z-40 flex items-stretch justify-end"
		onclick={closeConfigure}
	>
		<div
			class="bg-canvas border-l border-line w-full max-w-md h-full overflow-y-auto shadow-2xl"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="px-5 py-4 border-b border-line-soft flex items-start justify-between sticky top-0 bg-canvas">
				<div>
					<p class="text-xs uppercase tracking-wider text-ink-faint font-medium">Configure</p>
					<h3 class="text-lg font-semibold text-ink mt-0.5">{app.name}</h3>
					<p class="text-[11px] text-ink-faint font-mono">{app.id}</p>
				</div>
				<button
					type="button"
					onclick={closeConfigure}
					class="p-1.5 rounded-lg text-ink-muted hover:text-ink hover:bg-surface transition-colors"
					aria-label="Close"
				>
					<X size={18} />
				</button>
			</div>

			<div class="p-5 space-y-5">
				{#if !app.enabled}
					<div class="bg-surface-warm border border-accent/30 rounded-lg px-3 py-2.5 text-[13px] text-accent-hover">
						This app is installed but disabled. Adjust any settings below, then use <span class="font-medium">Enable app</span> to start it.
					</div>
				{/if}
				{#if visibleProperties(app.properties).length === 0}
					<p class="text-ink-muted text-sm italic">
						{#if app.properties.length > 0}
							This app has only advanced settings. Enable <span class="font-medium">Advanced</span> on the Apps page to see them.
						{:else}
							This app has no configurable properties.
						{/if}
					</p>
				{:else}
					{#each visibleProperties(app.properties) as prop (prop.key)}
						<div class="space-y-1.5">
							<div class="flex items-center justify-between gap-2">
								<label for="prop-{prop.key}" class="text-sm font-medium text-ink">
									{prop.display || prop.key}
								</label>
								{#if prop.overridden || pendingConfig[prop.key] !== undefined}
									<button
										type="button"
										onclick={() => resetProperty(prop)}
										class="text-[11px] text-ink-faint hover:text-brand inline-flex items-center gap-1 transition-colors"
									>
										<RotateCcw size={11} /> Reset
									</button>
								{/if}
							</div>

							{#if prop.type === "enum" && prop.options}
								<select
									id="prop-{prop.key}"
									value={pendingValue(prop)}
									onchange={(e) => {
										const v = (e.target as HTMLSelectElement).value;
										if (v === prop.value) {
											const fresh = { ...pendingConfig };
											delete fresh[prop.key];
											pendingConfig = fresh;
										} else {
											pendingConfig = { ...pendingConfig, [prop.key]: v };
										}
									}}
									class="w-full bg-canvas text-ink border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
								>
									{#each prop.options as opt}
										<option value={opt}>{opt}</option>
									{/each}
								</select>
							{:else if prop.type === "report"}
								<!-- A "report" property is read-only structured output written by
								     the app's daemon (e.g. Tailscale publishes its connection state
								     here). The value is a JSON-encoded string; we parse it and let
								     the renderer pick what to show. -->
								<ReportField value={prop.value} appId={app.id} />
							{:else if prop.type === "qr"}
								<!-- A "qr" property is read-only output written by the app's daemon
								     (e.g. Tailscale login URL, OctoEverywhere link). We render the
								     URL as a scannable QR code with the raw URL as a fallback. -->
								{#if prop.value}
									<div class="bg-surface border border-line-soft rounded-xl p-4 flex flex-col items-center gap-3">
										<canvas use:qrCanvas={prop.value} class="rounded-md bg-white"></canvas>
										<p class="text-[11px] text-ink-muted text-center">Scan with your phone, or open the URL below.</p>
										<div class="w-full flex items-stretch gap-1.5">
											<a
												href={prop.value}
												target="_blank"
												rel="noopener noreferrer"
												class="flex-1 min-w-0 px-2.5 py-1.5 bg-canvas border border-line-soft rounded-md text-[11px] font-mono text-brand hover:bg-brand-soft transition-colors truncate"
												title={prop.value}
											>
												{prop.value}
											</a>
											<button
												type="button"
												onclick={() => copyToClipboard(prop.key, prop.value)}
												class="shrink-0 px-2 py-1.5 bg-canvas hover:bg-surface-warm border border-line-soft rounded-md text-ink-muted hover:text-ink transition-colors"
												title="Copy URL"
												aria-label="Copy URL"
											>
												{#if copiedKey === prop.key}
													<Check size={13} class="text-brand" />
												{:else}
													<Copy size={13} />
												{/if}
											</button>
										</div>
										<p class="text-[11px] text-ink-faint text-center">
											URLs from the app may expire. If scanning fails, restart the app from its card to get a fresh code.
										</p>
									</div>
								{:else if app.running}
									<div class="bg-surface border border-line-soft rounded-xl p-4 text-center">
										<Loader2 size={22} class="text-brand animate-spin mx-auto mb-2" />
										<p class="text-sm text-ink">Waiting for the app to publish its login URL...</p>
										<p class="text-[11px] text-ink-faint mt-1">This usually takes a few seconds after startup.</p>
									</div>
								{:else}
									<div class="bg-surface-warm border border-accent/30 rounded-xl p-4 text-center text-ink-2">
										<p class="text-sm">Start the app to receive a login URL.</p>
										<p class="text-[11px] text-ink-muted mt-1">The daemon needs to be running to generate it.</p>
									</div>
								{/if}
							{:else}
								<input
									id="prop-{prop.key}"
									type="text"
									value={pendingValue(prop)}
									oninput={(e) => {
										const v = (e.target as HTMLInputElement).value;
										if (v === prop.value) {
											const fresh = { ...pendingConfig };
											delete fresh[prop.key];
											pendingConfig = fresh;
										} else {
											pendingConfig = { ...pendingConfig, [prop.key]: v };
										}
									}}
									class="w-full bg-canvas text-ink border border-line rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
								/>
							{/if}

							<p class="text-[11px] text-ink-faint">
								Default: <span class="font-mono">{prop.default || "—"}</span>
								{#if prop.overridden}
									&middot; <span class="text-accent-hover">user override active</span>
								{/if}
							</p>
						</div>
					{/each}
				{/if}
				{#if visibleProperties(app.properties).length > 0 && app.properties.length > visibleProperties(app.properties).length}
					<p class="text-[11px] text-ink-faint italic pt-2 border-t border-line-soft">
						{app.properties.length - visibleProperties(app.properties).length} advanced setting{app.properties.length - visibleProperties(app.properties).length === 1 ? "" : "s"} hidden. Toggle <span class="font-medium">Advanced</span> on the Apps page to reveal them.
					</p>
				{/if}
			</div>

			<div class="px-5 py-4 border-t border-line-soft flex items-center justify-between gap-2 sticky bottom-0 bg-canvas">
				<button
					type="button"
					onclick={clearAllOverrides}
					disabled={!app.properties.some((p) => p.overridden)}
					class="text-xs text-coral hover:underline disabled:opacity-40 disabled:no-underline"
				>
					Clear all overrides
				</button>
				<div class="flex items-center gap-2">
					<button
						type="button"
						onclick={closeConfigure}
						class="px-3 py-1.5 rounded-lg text-sm font-medium bg-surface hover:bg-surface-warm border border-line-soft text-ink"
					>
						Close
					</button>
					<button
						type="button"
						onclick={saveConfig}
						disabled={!hasPendingChanges() || configSaving}
						class="px-3 py-1.5 rounded-lg text-sm font-medium disabled:opacity-40 flex items-center gap-1.5 {app.enabled ? 'bg-brand hover:bg-brand-hover text-white' : 'bg-surface hover:bg-surface-warm border border-line-soft text-ink'}"
					>
						{#if configSaving}
							<Loader2 size={13} class="animate-spin" />
						{/if}
						Save
					</button>
					{#if !app.enabled}
						<button
							type="button"
							onclick={() => saveAndEnable(app)}
							disabled={configSaving}
							class="px-3 py-1.5 rounded-lg text-sm font-medium bg-brand hover:bg-brand-hover text-white disabled:opacity-40 flex items-center gap-1.5"
						>
							<Play size={13} />
							Enable app
						</button>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- Toast -->
<!-- Uninstall confirmation -->
{#if uninstallTarget}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4"
		onclick={() => !uninstallRunning && (uninstallTarget = null)}
	>
		<div
			class="bg-canvas border border-line rounded-2xl p-6 max-w-md w-full shadow-2xl"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="flex items-center text-coral mb-3">
				<AlertTriangle size={22} class="mr-2" />
				<h2 class="text-lg font-semibold text-ink">Uninstall {uninstallTarget.name}?</h2>
			</div>
			<p class="text-ink-2 text-sm mb-2">
				This removes the app and all its saved configuration. The app will be stopped first.
			</p>
			<p class="text-ink-muted text-xs mb-5">
				<span class="font-mono">{uninstallTarget.id}</span> &middot; user app
			</p>
			<div class="flex justify-end gap-2">
				<button
					type="button"
					onclick={() => (uninstallTarget = null)}
					disabled={uninstallRunning}
					class="px-4 py-2 rounded-lg font-medium bg-surface hover:bg-surface-warm border border-line-soft text-ink disabled:opacity-50"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={performUninstall}
					disabled={uninstallRunning || !$printerState.can_install}
					title={!$printerState.can_install ? "Disabled while printer is busy" : ""}
					class="px-4 py-2 rounded-lg font-medium bg-coral hover:opacity-90 text-white flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
				>
					{#if uninstallRunning}
						<Loader2 size={14} class="animate-spin" />
					{:else}
						<Trash2 size={14} />
					{/if}
					Uninstall
				</button>
			</div>
		</div>
	</div>
{/if}

{#if toast}
	<div class="fixed bottom-5 right-5 z-50">
		<div class="px-4 py-2.5 rounded-lg shadow-lg border text-sm font-medium {toast.tone === 'err' ? 'bg-surface-accent text-coral border-coral/40' : 'bg-canvas text-ink border-line-soft'}">
			{toast.text}
		</div>
	</div>
{/if}
