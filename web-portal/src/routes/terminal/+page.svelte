<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { Terminal } from '@xterm/xterm';
	import { FitAddon } from '@xterm/addon-fit';
	import { Terminal as TerminalIcon, Plus, X } from 'lucide-svelte';
	import '@xterm/xterm/css/xterm.css';

	type Session = { id: string; title: string; connected: boolean };

	// Reactive list of tabs. Only plain data lives here.
	let sessions = $state<Session[]>([]);
	let activeId = $state('');

	// Live xterm / WebSocket instances are kept OUT of $state on purpose: the
	// reactive proxy would wrap the WebSocket and break it. Keyed by session id.
	type Runtime = { term: Terminal; fit: FitAddon; ws: WebSocket; ro: ResizeObserver };
	const runtimes = new Map<string, Runtime>();

	let seq = 0;

	function setConnected(id: string, value: boolean) {
		const s = sessions.find((x) => x.id === id);
		if (s) s.connected = value;
	}

	function newSession() {
		seq += 1;
		const s: Session = { id: `shell-${seq}`, title: `Shell ${seq}`, connected: false };
		sessions = [...sessions, s];
		activeId = s.id;
	}

	function closeSession(id: string) {
		const idx = sessions.findIndex((s) => s.id === id);
		if (idx === -1) return;
		sessions = sessions.filter((s) => s.id !== id);
		// Runtime teardown happens in the action's destroy() when the element unmounts.
		if (activeId === id) {
			const next = sessions[idx] ?? sessions[idx - 1] ?? sessions[0];
			activeId = next ? next.id : '';
		}
	}

	// Svelte action: wires up an xterm + PTY WebSocket for one session when its
	// container mounts, and tears everything down when it unmounts (tab closed or
	// page left). This is what makes the close button actually close the shell.
	function termAttach(node: HTMLElement, id: string) {
		const term = new Terminal({
			cursorBlink: true,
			theme: {
				background: '#1a1a1a',
				foreground: '#f5f5f5',
				cursor: '#ff9a00',
				selectionBackground: '#005aff55'
			},
			fontFamily: '"Fira Code", "JetBrains Mono", monospace',
			fontSize: 13
		});

		const fit = new FitAddon();
		term.loadAddon(fit);
		term.open(node);
		fit.fit();

		const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
		const wsHost = import.meta.env.DEV ? 'localhost:8080' : window.location.host;
		const ws = new WebSocket(`${protocol}//${wsHost}/api/terminal`);
		ws.binaryType = 'arraybuffer';

		ws.onopen = () => {
			ws.send(JSON.stringify({ cols: term.cols, rows: term.rows }));
			setConnected(id, true);
			if (id === activeId) term.focus();
		};

		ws.onmessage = (event) => {
			if (event.data instanceof ArrayBuffer) {
				term.write(new Uint8Array(event.data));
			} else {
				term.write(event.data);
			}
		};

		ws.onclose = () => {
			setConnected(id, false);
			term.write('\r\n\x1b[2m[connection closed]\x1b[0m\r\n');
		};

		term.onData((data) => {
			if (ws.readyState === WebSocket.OPEN) ws.send(data);
		});

		term.onResize((size) => {
			if (ws.readyState === WebSocket.OPEN) {
				ws.send(JSON.stringify({ cols: size.cols, rows: size.rows }));
			}
		});

		const ro = new ResizeObserver(() => {
			// Only meaningful while visible; fit on a display:none element is a no-op.
			if (node.offsetParent !== null) fit.fit();
		});
		ro.observe(node);

		runtimes.set(id, { term, fit, ws, ro });

		return {
			destroy() {
				ro.disconnect();
				try {
					ws.close();
				} catch {}
				term.dispose();
				runtimes.delete(id);
			}
		};
	}

	// When the active tab changes, refit + focus it once it's visible. Background
	// tabs keep running; their buffers retain output while hidden.
	$effect(() => {
		const rt = runtimes.get(activeId);
		if (!rt) return;
		requestAnimationFrame(() => {
			rt.fit.fit();
			rt.term.focus();
		});
	});

	// Open one shell to start. Closing every tab is allowed and shows an empty
	// state with an explicit "Open a shell" button, rather than auto-respawning.
	onMount(() => {
		newSession();
	});

	onDestroy(() => {
		// Safety net: actions normally tear down on unmount, but close any
		// stragglers if the component is disposed abruptly.
		for (const rt of runtimes.values()) {
			rt.ro.disconnect();
			try {
				rt.ws.close();
			} catch {}
			rt.term.dispose();
		}
		runtimes.clear();
	});
</script>

<svelte:head>
	<title>Terminal - Rinkhals</title>
</svelte:head>

<div class="h-full flex flex-col space-y-4 max-w-7xl mx-auto w-full">
	<header class="flex items-end justify-between pb-4 border-b border-line-soft">
		<div>
			<p class="text-xs uppercase tracking-wider text-ink-faint font-medium">Shell</p>
			<h2 class="text-3xl font-semibold text-ink mt-1 tracking-tight flex items-center gap-2">
				<TerminalIcon size={26} class="text-brand" />
				Console
			</h2>
		</div>
		<span class="text-xs text-ink-faint">{sessions.length} open</span>
	</header>

	<div class="bg-canvas rounded-xl border border-line-soft flex-1 flex flex-col overflow-hidden">
		<!-- Tab bar -->
		<div class="flex items-center gap-1 px-2 py-1.5 border-b border-line-soft bg-surface overflow-x-auto">
			{#each sessions as s (s.id)}
				<div
					class="group flex items-center gap-1.5 pl-3 pr-1.5 py-1.5 rounded-lg text-sm cursor-pointer transition-colors shrink-0
						{s.id === activeId
							? 'bg-canvas text-ink border border-line-soft shadow-sm'
							: 'text-ink-muted hover:bg-canvas/60'}"
					onclick={() => (activeId = s.id)}
					onkeydown={(e) => e.key === 'Enter' && (activeId = s.id)}
					role="tab"
					tabindex="0"
					aria-selected={s.id === activeId}
				>
					{#if !s.connected}
						<span class="w-1.5 h-1.5 rounded-full bg-accent shrink-0" title="Disconnected"></span>
					{/if}
					<span class="font-medium whitespace-nowrap">{s.title}</span>
					<button
						type="button"
						class="p-0.5 rounded hover:bg-surface-accent hover:text-coral text-ink-faint transition-colors"
						title="Close shell"
						aria-label="Close {s.title}"
						onclick={(e) => {
							e.stopPropagation();
							closeSession(s.id);
						}}
					>
						<X size={13} />
					</button>
				</div>
			{/each}

			<button
				type="button"
				class="ml-1 p-1.5 rounded-lg text-ink-muted hover:bg-canvas hover:text-brand transition-colors shrink-0"
				title="New shell"
				aria-label="New shell"
				onclick={newSession}
			>
				<Plus size={16} />
			</button>
		</div>

		<!-- Terminal area -->
		<div class="flex-1 relative bg-[#1a1a1a]">
			{#if sessions.length === 0}
				<div class="absolute inset-0 flex flex-col items-center justify-center gap-3 text-ink-faint">
					<TerminalIcon size={32} class="opacity-60" />
					<p class="text-sm">No shell open</p>
					<button
						type="button"
						onclick={newSession}
						class="flex items-center gap-1.5 px-3 py-1.5 bg-brand hover:bg-brand-hover text-white rounded-lg text-sm font-medium transition-colors"
					>
						<Plus size={14} /> Open a shell
					</button>
				</div>
			{:else}
				{#each sessions as s (s.id)}
					<div class="absolute inset-0 {s.id === activeId ? '' : 'hidden'}">
						<div use:termAttach={s.id} class="absolute inset-0 p-3"></div>
					</div>
				{/each}
			{/if}
		</div>
	</div>
</div>
