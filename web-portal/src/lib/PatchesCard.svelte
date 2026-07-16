<script lang="ts">
	import { onMount } from "svelte";
	import { Layers, CheckCircle2, AlertTriangle, Loader2 } from "lucide-svelte";

	interface BinaryPatch {
		name: string;
		target: string;
		model: string;
		firmware_ver: string;
		patch_filename: string;
		size_bytes: number;
		applies_to_this: boolean;
	}

	interface ScriptHook {
		name: string;
		description: string;
		path: string;
		present: boolean;
	}

	interface PatchesResponse {
		model_code: string;
		firmware_version: string;
		rinkhals_version: string;
		binary_patches: BinaryPatch[];
		script_hooks: ScriptHook[];
		compatible_for_run: boolean;
	}

	const apiHost = import.meta.env.DEV ? "http://localhost:8090" : "";

	let data = $state<PatchesResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Group binary patches by the binary they target, so the user sees one card
	// per modified binary listing all the firmware versions covered.
	const groupedBinaries = $derived.by(() => {
		if (!data) return [] as Array<{ name: string; target: string; entries: BinaryPatch[] }>;
		const map = new Map<string, BinaryPatch[]>();
		for (const b of data.binary_patches) {
			const k = b.name;
			if (!map.has(k)) map.set(k, []);
			map.get(k)!.push(b);
		}
		return [...map.entries()].map(([name, entries]) => ({
			name,
			target: entries[0].target,
			entries: entries.slice().sort((a, b) => a.firmware_ver < b.firmware_ver ? 1 : -1)
		}));
	});

	function fmtSize(n: number): string {
		if (!n) return "";
		if (n < 1024) return `${n} B`;
		if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
		return `${(n / (1024 * 1024)).toFixed(1)} MB`;
	}

	onMount(async () => {
		try {
			const res = await fetch(`${apiHost}/api/firmware/patches`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			data = await res.json();
		} catch (e: any) {
			error = e.message || "Failed to load patches";
		} finally {
			loading = false;
		}
	});
</script>

<section class="bg-canvas rounded-xl border border-line-soft p-5">
	<div class="flex items-start gap-3 mb-4">
		<div class="w-11 h-11 rounded-lg bg-surface-warm text-accent flex items-center justify-center shrink-0">
			<Layers size={20} />
		</div>
		<div class="flex-1 min-w-0">
			<h3 class="text-base font-semibold text-ink">Rinkhals patches</h3>
			<p class="text-ink-muted text-sm mt-1">
				What Rinkhals modifies on top of the stock Anycubic firmware. Useful before swapping firmware versions: if a binary patch for the target version is missing, Rinkhals will boot stock until you install a matching release.
			</p>
		</div>
	</div>

	{#if loading}
		<div class="flex items-center gap-2 text-ink-muted text-sm">
			<Loader2 size={14} class="animate-spin" /> Loading patches...
		</div>
	{:else if error}
		<div class="bg-coral/10 border border-coral/40 rounded-lg p-3 text-sm text-ink">
			Could not load patches: {error}
		</div>
	{:else if data}
		{#if !data.compatible_for_run}
			<div class="bg-coral/10 border border-coral/40 rounded-lg p-3 mb-4 text-sm flex items-start gap-2">
				<AlertTriangle size={14} class="text-coral shrink-0 mt-0.5" />
				<div class="text-ink-muted">
					Rinkhals does not have binary patches for {data.model_code} firmware {data.firmware_version}. The Rinkhals services may not load correctly on this combination.
				</div>
			</div>
		{/if}

		<div class="mb-4">
			<h4 class="text-xs uppercase tracking-wider text-ink-faint mb-2">Binary patches</h4>
			{#if groupedBinaries.length === 0}
				<p class="text-sm text-ink-muted italic">No binary patches found.</p>
			{:else}
				<div class="space-y-2">
					{#each groupedBinaries as group}
						<div class="bg-surface border border-line-soft rounded-lg px-4 py-3">
							<div class="flex items-baseline justify-between gap-2 mb-2 flex-wrap">
								<div>
									<span class="font-medium text-ink">{group.name}</span>
									<code class="text-[11px] text-ink-muted ml-2">{group.target}</code>
								</div>
								<span class="text-[11px] text-ink-faint">{group.entries.length} version{group.entries.length === 1 ? "" : "s"}</span>
							</div>
							<div class="flex flex-wrap gap-1.5">
								{#each group.entries as e}
									<span
										class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[11px] {e.applies_to_this ? 'bg-emerald/15 text-emerald font-semibold' : 'bg-surface-warm text-ink-muted'}"
										title="{e.model} firmware {e.firmware_ver} - {fmtSize(e.size_bytes)}"
									>
										{#if e.applies_to_this}
											<CheckCircle2 size={10} />
										{/if}
										{e.model}_{e.firmware_ver}
									</span>
								{/each}
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<div>
			<h4 class="text-xs uppercase tracking-wider text-ink-faint mb-2">Script hooks</h4>
			<div class="space-y-2">
				{#each data.script_hooks as h}
					<div class="bg-surface border border-line-soft rounded-lg px-4 py-3">
						<div class="flex items-start justify-between gap-2 mb-1">
							<span class="font-medium text-ink text-sm">{h.name}</span>
							{#if h.present}
								<span class="inline-flex items-center gap-1 text-emerald text-[11px]">
									<CheckCircle2 size={11} /> active
								</span>
							{:else}
								<span class="inline-flex items-center gap-1 text-ink-faint text-[11px]">
									not present
								</span>
							{/if}
						</div>
						<p class="text-xs text-ink-muted">{h.description}</p>
						<code class="text-[11px] text-ink-faint">{h.path}</code>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</section>
