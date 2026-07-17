<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import { Box, Video, MonitorPlay, Activity, HardDrive, Printer, Thermometer, ExternalLink, ArrowUpCircle } from "lucide-svelte";
	import { firmwareStatus } from "$lib/firmwareStatus";

	type AppInfo = { id: string; name: string; url?: string; port: string; icon: any; status: string; accent: string; };

	let apps = $state<AppInfo[]>([]);
	let loading = $state(true);
	let metrics = $state<{
		uptime: string,
		cpuUsage: number,
		memTotalMB: number,
		memAvailableMB: number,
		memInUseMB: number,
		memCachedMB: number,
		memFreeMB: number,
		diskUsage: number
	} | null>(null);
	let printer = $state<{state: string, bedTemp: number, hotendTemp: number} | null>(null);

	const appBlueprints: Record<string, Partial<AppInfo>> = {
		"25-mainsail": { port: "4409", icon: Box, accent: "text-brand" },
		"26-fluidd": { port: "4408", icon: Box, accent: "text-brand" },
		"30-mjpg-streamer": { port: "8080", icon: Video, accent: "text-accent" },
		"50-remote-display": { port: "5800", icon: MonitorPlay, accent: "text-coral" }
	};

	let pollingInterval: any;

	const fetchData = async () => {
		const hostname = window.location.hostname;
		const protocol = window.location.protocol;

		try {
			const res = await fetch('/api/services');
			if (res.ok) {
				const services: {id: string, name: string, status: string}[] = await res.json();
				apps = services
					.filter(s => appBlueprints[s.id])
					.map(s => {
						const bp = appBlueprints[s.id]!;
						return {
							id: s.id,
							name: s.name,
							url: `${protocol}//${hostname}:${bp.port}`,
							port: bp.port || "",
							icon: bp.icon,
							status: s.status,
							accent: bp.accent || "text-ink-faint"
						};
					});
			}
		} catch (e) {
			console.error("Failed to load services", e);
		} finally {
			loading = false;
		}

		try {
			const res = await fetch('/api/metrics');
			if (res.ok) {
				metrics = await res.json();
			}
		} catch (e) {
			console.error("Failed to load metrics", e);
		}

		try {
			const res = await fetch(`${protocol}//${hostname}:7125/printer/objects/query?webhooks&extruder=temperature&heater_bed=temperature&print_stats`);
			if (res.ok) {
				const data = await res.json();
				printer = {
					state: data?.result?.status?.print_stats?.state || "unknown",
					bedTemp: data?.result?.status?.heater_bed?.temperature || 0,
					hotendTemp: data?.result?.status?.extruder?.temperature || 0
				};
			} else {
				printer = null;
			}
		} catch (e) {
			printer = null;
		}
	};

	onMount(() => {
		fetchData();
		pollingInterval = setInterval(fetchData, 5000);
	});

	onDestroy(() => {
		if (pollingInterval) clearInterval(pollingInterval);
	});
</script>

<svelte:head>
	<title>Dashboard - Rinkhals</title>
</svelte:head>

<div class="space-y-8 max-w-7xl mx-auto">
	<header class="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-4 pb-4 border-b border-line-soft">
		<div>
			<p class="text-xs uppercase tracking-wider text-ink-faint font-medium">Overview</p>
			<h2 class="text-3xl font-semibold text-ink mt-1 tracking-tight">
				System status
			</h2>
		</div>

		{#if printer}
			<div class="flex items-center gap-2 text-sm flex-wrap">
				<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-warm border border-accent/30 text-ink">
					<Printer size={15} class={printer.state === 'printing' ? 'text-accent animate-pulse' : 'text-ink-muted'} />
					<span class="font-medium">{printer.state.toUpperCase()}</span>
				</span>
				<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-canvas border border-line-soft text-ink-2">
					<Thermometer size={15} class="text-coral" />
					{printer.hotendTemp.toFixed(1)}° / {printer.bedTemp.toFixed(1)}°
				</span>
				{#if $firmwareStatus.firmware_update_available || $firmwareStatus.rinkhals_update_available}
					<a
						href="/firmware"
						class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-brand-soft border border-brand/30 text-brand text-sm hover:bg-brand hover:text-white transition-colors"
						title="Open the Firmware page"
					>
						<ArrowUpCircle size={14} />
						<span class="font-medium">Firmware update available</span>
					</a>
				{/if}
			</div>
		{:else}
			<div class="flex items-center gap-2 text-sm flex-wrap">
				<div class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-canvas border border-line-soft text-ink-muted">
					<Printer size={15} /> Moonraker offline
				</div>
				{#if $firmwareStatus.firmware_update_available || $firmwareStatus.rinkhals_update_available}
					<a
						href="/firmware"
						class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-brand-soft border border-brand/30 text-brand hover:bg-brand hover:text-white transition-colors"
						title="Open the Firmware page"
					>
						<ArrowUpCircle size={14} />
						<span class="font-medium">Firmware update available</span>
					</a>
				{/if}
			</div>
		{/if}
	</header>

	<!-- Metrics row: CPU + Storage -->
	<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
		<div class="bg-canvas border border-line-soft rounded-xl p-4 flex items-center gap-4">
			<div class="w-10 h-10 rounded-lg bg-brand-soft flex items-center justify-center">
				<Activity size={20} class="text-brand" />
			</div>
			<div>
				<p class="text-xs uppercase tracking-wider text-ink-faint">CPU</p>
				<p class="text-lg font-semibold text-ink">{metrics ? `${metrics.cpuUsage}%` : "—"}</p>
			</div>
		</div>
		<div class="bg-canvas border border-line-soft rounded-xl p-4 flex items-center gap-4">
			<div class="w-10 h-10 rounded-lg bg-surface-accent flex items-center justify-center">
				<HardDrive size={20} class="text-coral" />
			</div>
			<div>
				<p class="text-xs uppercase tracking-wider text-ink-faint">Storage</p>
				<p class="text-lg font-semibold text-ink">{metrics ? `${metrics.diskUsage}%` : "—"}</p>
			</div>
		</div>
	</div>

	<!-- Memory: segmented bar. The dimension bracket spans the cached + free
	     part so it's obvious that "available" (not "free") is the usable figure. -->
	<div class="bg-canvas border border-line-soft rounded-xl p-4">
		<div class="flex items-baseline justify-between">
			<p class="text-xs uppercase tracking-wider text-ink-faint">Memory</p>
			<p class="text-xs text-ink-faint">{metrics ? `${metrics.memTotalMB} MB total` : ""}</p>
		</div>

		{#if metrics}
			{@const total = metrics.memTotalMB || 1}
			{@const inUsePct = (metrics.memInUseMB / total) * 100}
			{@const cachedPct = (metrics.memCachedMB / total) * 100}
			{@const freePct = (metrics.memFreeMB / total) * 100}

			<div class="mt-3 flex h-8 rounded-lg overflow-hidden bg-surface">
				<div class="h-full" style="width: {inUsePct}%; background: var(--color-coral);"></div>
				<div class="h-full" style="width: {cachedPct}%; background: repeating-linear-gradient(45deg, var(--color-accent) 0, var(--color-accent) 5px, var(--color-accent-hover) 5px, var(--color-accent-hover) 9px);"></div>
				<div class="h-full border-l border-line-soft" style="width: {freePct}%;"></div>
			</div>

			<div class="mt-1.5" style="margin-left: {inUsePct}%; width: {cachedPct + freePct}%;">
				<div class="h-2 border-l border-r border-b border-line"></div>
				<p class="text-center text-sm font-semibold text-ink mt-1">{metrics.memAvailableMB} MB available</p>
			</div>

			<div class="flex flex-wrap gap-x-5 gap-y-1 mt-3 text-xs text-ink-muted">
				<span class="inline-flex items-center gap-1.5">
					<span class="w-3 h-3 rounded-sm" style="background: var(--color-coral);"></span>
					In use {metrics.memInUseMB} MB
				</span>
				<span class="inline-flex items-center gap-1.5">
					<span class="w-3 h-3 rounded-sm" style="background: var(--color-accent);"></span>
					Cached {metrics.memCachedMB} MB
				</span>
				<span class="inline-flex items-center gap-1.5">
					<span class="w-3 h-3 rounded-sm bg-surface border border-line-soft"></span>
					Free {metrics.memFreeMB} MB
				</span>
			</div>
		{:else}
			<p class="text-lg font-semibold text-ink mt-2">—</p>
		{/if}
	</div>

	<!-- Services -->
	<section>
		<div class="flex items-baseline justify-between mb-4">
			<h3 class="text-lg font-semibold text-ink">Web interfaces</h3>
			<p class="text-xs text-ink-faint">Updated every 5s</p>
		</div>

		{#if loading}
			<div class="text-ink-faint animate-pulse">Scanning for running services...</div>
		{:else if apps.length === 0}
			<div class="text-ink-faint italic">No web interfaces are currently active or installed.</div>
		{:else}
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
				{#each apps as app}
					{@const Icon = app.icon}
					{@const isRunning = app.status === "Running"}
					<a
						href={isRunning ? app.url : "#"}
						target={isRunning ? "_blank" : undefined}
						class="group rounded-xl p-5 border block transition-all duration-150
							{isRunning
								? 'bg-canvas border-line-soft hover:border-brand hover:shadow-md hover:-translate-y-0.5'
								: 'bg-surface border-line-soft opacity-60 cursor-not-allowed'}"
						onclick={(e) => { if (!isRunning) e.preventDefault(); }}
					>
						<div class="flex items-center justify-between mb-4">
							<div class="w-11 h-11 rounded-lg bg-surface flex items-center justify-center group-hover:bg-brand-soft transition-colors">
								<Icon size={22} class={isRunning ? app.accent : 'text-ink-faint'} />
							</div>
							<span class="px-2.5 py-1 text-[11px] font-semibold rounded-full uppercase tracking-wider {isRunning ? 'bg-brand-soft text-brand' : 'bg-surface-accent text-coral'}">
								{app.status}
							</span>
						</div>
						<h4 class="text-base font-semibold {isRunning ? 'text-ink' : 'text-ink-faint'} mb-1 flex items-center gap-1.5">
							{app.name}
							{#if isRunning}
								<ExternalLink size={13} class="text-ink-faint group-hover:text-brand transition-colors" />
							{/if}
						</h4>
						<p class="text-sm {isRunning ? 'text-ink-muted' : 'text-ink-faint'}">
							{isRunning ? `Port ${app.port}` : 'Service is currently stopped'}
						</p>
					</a>
				{/each}
			</div>
		{/if}
	</section>
</div>
