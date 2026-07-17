<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { ScrollText } from 'lucide-svelte';

    let logs = $state<string[]>([]);
    let ws: WebSocket | null = null;
    let autoScroll = $state(true);
    let logContainer: HTMLElement;

    let activeLog = $state('/tmp/rinkhals/rinkhals.log');
    // These are the live logs the running processes actually write, all under
    // RINKHALS_LOGS=/tmp/rinkhals (tmpfs) except Moonraker:
    //  - Rinkhals: tools.sh log() appends to /tmp/rinkhals/rinkhals.log for the
    //    whole session. (/useremain/rinkhals/rinkhals.log is only the early boot
    //    loader stub, written before tools.sh and then frozen, so it goes stale.)
    //  - gklib/gkapi: live logs in /tmp; the /useremain/log/*.log copies are the
    //    stock Anycubic files and go stale once Rinkhals takes over.
    //  - Moonraker: the bind-mounted printer_data log it actively writes.
    const logFiles = [
        { name: "Rinkhals", path: "/tmp/rinkhals/rinkhals.log" },
        { name: "Klipper (gklib)", path: "/tmp/gklib.log" },
        { name: "Moonraker", path: "/useremain/home/rinkhals/printer_data/logs/moonraker.log" },
        { name: "GKAPI", path: "/tmp/gkapi.log" }
    ];

    function connectWs() {
        if (ws) {
            ws.close();
        }
        logs = [];

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const hostname = typeof window !== 'undefined' ? window.location.host : 'localhost:8090';
        ws = new WebSocket(`${protocol}//${hostname}/api/logstream?path=${encodeURIComponent(activeLog)}`);

        ws.onmessage = (event) => {
            logs = [...logs, event.data];
            if (logs.length > 500) logs = logs.slice(logs.length - 500);

            if (autoScroll && logContainer) {
                setTimeout(() => {
                    logContainer.scrollTop = logContainer.scrollHeight;
                }, 10);
            }
        };

        ws.onerror = () => {
            logs = [...logs, '-- Connection error --'];
        };

        ws.onclose = () => {
            logs = [...logs, '-- Connection closed --'];
        };
    }

    onMount(() => {
        connectWs();
    });

    onDestroy(() => {
        if (ws) ws.close();
    });

    function switchLog(path: string) {
        activeLog = path;
        connectWs();
    }
</script>

<svelte:head>
    <title>Log Viewer - Rinkhals</title>
</svelte:head>

<div class="space-y-6 h-full flex flex-col max-w-7xl mx-auto w-full">
    <header class="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-4 pb-4 border-b border-line-soft">
        <div>
            <p class="text-xs uppercase tracking-wider text-ink-faint font-medium">Diagnostics</p>
            <h2 class="text-3xl font-semibold text-ink mt-1 tracking-tight flex items-center gap-2">
                <ScrollText size={26} class="text-brand" />
                System logs
            </h2>
        </div>
        <div class="flex flex-wrap gap-2 items-center">
            {#each logFiles as lf}
                <button
                    class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border
                        {activeLog === lf.path
                            ? 'bg-brand-soft text-brand border-brand/30'
                            : 'bg-canvas text-ink-muted hover:bg-surface-warm border-line-soft'}"
                    onclick={() => switchLog(lf.path)}
                >
                    {lf.name}
                </button>
            {/each}
            <button
                class="px-3 py-1.5 ml-2 rounded-lg text-sm font-medium border transition-colors
                    {autoScroll
                        ? 'bg-surface-warm text-accent-hover border-accent/30'
                        : 'bg-canvas text-ink-muted border-line-soft'}"
                onclick={() => autoScroll = !autoScroll}
            >
                Auto-scroll {autoScroll ? 'on' : 'off'}
            </button>
        </div>
    </header>

    <div class="flex-1 bg-canvas border border-line-soft rounded-xl overflow-hidden relative">
        <div class="px-4 py-2 border-b border-line-soft bg-surface text-[11px] text-ink-faint font-mono">
            {activeLog}
        </div>
        <div class="absolute inset-0 top-9 p-4 overflow-y-auto font-mono text-[13px] text-ink-2 whitespace-pre scroll-smooth bg-canvas" bind:this={logContainer}>
            {#each logs as line}
                <div class="hover:bg-surface px-1">{line}</div>
            {/each}
            {#if logs.length === 0}
                <div class="text-ink-faint italic">Waiting for log data...</div>
            {/if}
        </div>
    </div>
</div>
