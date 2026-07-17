<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { Save, FileText, AlertCircle, Loader2 } from 'lucide-svelte';

    let filePath = $state($page.url.searchParams.get("path") || "");

    let content = $state('');
    let loading = $state(false);
    let saving = $state(false);
    let isFileLoaded = $state(false);
    let message = $state({ text: '', isError: false });

    async function loadFile() {
        if (!filePath.trim()) {
            message = { text: "Please enter a valid path to load", isError: true };
            return;
        }

        loading = true;
        message = { text: '', isError: false };
        try {
            const res = await fetch(`/api/download?path=${encodeURIComponent(filePath)}`);
            if (res.ok) {
                content = await res.text();
                isFileLoaded = true;
            } else {
                message = { text: `Failed to load: ${res.statusText}`, isError: true };
                content = '';
                isFileLoaded = false;
            }
        } catch (e: any) {
            message = { text: `Error: ${e.message}`, isError: true };
            content = '';
            isFileLoaded = false;
        } finally {
            loading = false;
        }
    }

    async function saveFile() {
        if (!isFileLoaded && !content) return;

        saving = true;
        message = { text: '', isError: false };
        try {
            const res = await fetch('/api/saveFile', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: filePath, content })
            });

            if (res.ok) {
                message = { text: 'File saved successfully', isError: false };
                setTimeout(() => message.text = '', 3000);
            } else {
                message = { text: `Failed to save: ${res.statusText}`, isError: true };
            }
        } catch (e: any) {
            message = { text: `Error: ${e.message}`, isError: true };
        } finally {
            saving = false;
        }
    }

    onMount(() => {
        if (filePath) {
            loadFile();
        }
    });
</script>

<svelte:head>
    <title>Text Editor - Rinkhals</title>
</svelte:head>

<div class="space-y-6 h-full flex flex-col max-w-7xl mx-auto w-full">
    <header class="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-4 pb-4 border-b border-line-soft">
        <div>
            <p class="text-xs uppercase tracking-wider text-ink-faint font-medium">Configuration</p>
            <h2 class="text-3xl font-semibold text-ink mt-1 tracking-tight flex items-center gap-2">
                <FileText size={26} class="text-brand" />
                Text editor
            </h2>
        </div>

        <div class="flex flex-wrap items-center gap-3">
            {#if message.text}
                <div class="flex items-center text-sm {message.isError ? 'text-coral' : 'text-brand'}">
                    {#if message.isError}<AlertCircle size={15} class="mr-1.5" />{/if}
                    {message.text}
                </div>
            {/if}

            <div class="flex items-center bg-canvas rounded-lg p-1 border border-line-soft">
                <input
                    type="text"
                    bind:value={filePath}
                    placeholder="Enter file path..."
                    class="bg-transparent border-none text-ink px-2 py-1.5 focus:outline-none w-64 text-sm font-mono"
                    onkeypress={(e) => e.key === 'Enter' && loadFile()}
                />
                <button
                    onclick={loadFile}
                    disabled={loading}
                    class="px-3 py-1.5 bg-surface hover:bg-surface-warm border border-line-soft rounded text-sm text-ink font-medium transition-colors disabled:opacity-50"
                >
                    Load
                </button>
            </div>

            <button
                onclick={saveFile}
                disabled={saving || loading || !content}
                class="flex items-center px-4 py-2 bg-brand hover:bg-brand-hover text-white rounded-lg font-medium transition-colors disabled:opacity-50 gap-2 shadow-sm"
            >
                {#if saving}
                    <Loader2 size={16} class="animate-spin" />
                    Saving...
                {:else}
                    <Save size={16} />
                    Save file
                {/if}
            </button>
        </div>
    </header>

    <div class="flex-1 rounded-xl overflow-hidden border border-line-soft relative bg-canvas">
        {#if loading}
            <div class="absolute inset-0 bg-canvas/70 flex flex-col items-center justify-center z-10 backdrop-blur-sm">
                <Loader2 size={40} class="text-brand animate-spin mb-3" />
                <span class="text-ink-2 font-medium text-sm">Loading contents...</span>
            </div>
        {:else if !isFileLoaded && !content}
            <div class="absolute inset-0 flex flex-col items-center justify-center text-ink-faint">
                <FileText size={40} class="mb-3 opacity-60" />
                <p class="text-base font-medium text-ink-muted">No file loaded</p>
                <p class="text-sm">Enter a file path above, or start typing to create a new file.</p>
            </div>
        {/if}

        <textarea
            bind:value={content}
            oninput={() => { if(!isFileLoaded) isFileLoaded = true; }}
            class="w-full h-full bg-transparent text-ink-2 font-mono text-[13px] p-4 focus:outline-none resize-none relative z-0 {(!isFileLoaded && !content) ? 'opacity-0' : 'opacity-100'}"
            placeholder="File content..."
            spellcheck="false"
        ></textarea>
    </div>
</div>
