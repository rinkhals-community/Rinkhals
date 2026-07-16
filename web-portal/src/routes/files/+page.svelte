<script lang="ts">
    import { Folder, FileText, Search, ArrowUp, Download, Trash2, Edit2, FolderPlus, MoveRight, AlertTriangle, Link2, Link2Off } from 'lucide-svelte';
    import { onMount } from 'svelte';

    let searchQuery = $state('');
    let currentPath = $state('/');
    let files = $state<any[]>([]);
    let loading = $state(true);
    let error = $state('');
    let selectedFiles = $state<Set<string>>(new Set());

    let showDeleteConfirm = $state(false);
    let showRenameModal = $state(false);
    let showMoveModal = $state(false);
    let showNewFolderModal = $state(false);

    let modalInput = $state('');
    let modalActionLoading = $state(false);

    const apiHost = import.meta.env.DEV ? 'http://localhost:8090' : '';

    async function loadFiles(path: string) {
        loading = true;
        error = '';
        selectedFiles = new Set();
        try {
            const res = await fetch(`${apiHost}/api/files?path=${encodeURIComponent(path)}`);
            if (!res.ok) throw new Error(await res.text());
            files = await res.json() || [];
            currentPath = path;
        } catch (err: any) {
            error = err.message;
        } finally {
            loading = false;
        }
    }

    onMount(() => {
        loadFiles('/');
    });

    function handleItemClick(file: any) {
        if (file.type === 'folder') {
            loadFiles(file.path);
        } else if (file.type === 'link') {
            // Symlinks resolve to one of three things; treat the link as its
            // target's nature for click purposes. Broken links don't navigate.
            if (file.targetType === 'folder') {
                loadFiles(file.path);
            }
            // file.targetType === 'file': click is a no-op; the row's
            //   Edit/Download buttons handle file actions.
            // file.targetType === 'broken': nothing to do.
        }
    }

    function handleDownload(e: Event, file: any) {
        e.stopPropagation();
        window.open(`${apiHost}/api/download?path=${encodeURIComponent(file.path)}`, '_blank');
    }

    function toggleSelection(e: Event, path: string) {
        e.stopPropagation();
        let newSet = new Set(selectedFiles);
        if (newSet.has(path)) newSet.delete(path);
        else newSet.add(path);
        selectedFiles = newSet;
    }

    function toggleAll(e: Event) {
        e.stopPropagation();
        if (selectedFiles.size === filteredFiles.length) {
            selectedFiles = new Set();
        } else {
            selectedFiles = new Set(filteredFiles.map((f: any) => f.path));
        }
    }

    function goUp() {
        if (currentPath === '/') return;
        const parts = currentPath.split('/').filter(Boolean);
        parts.pop();
        loadFiles('/' + parts.join('/'));
    }

    let filteredFiles = $derived(
        files?.filter((f: any) => f.name.toLowerCase().includes(searchQuery.toLowerCase())) || []
    );

    async function fsAction(action: string, targets: string[], destination?: string) {
        modalActionLoading = true;
        try {
            const res = await fetch(`${apiHost}/api/fs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action, targets, destination })
            });
            const data = await res.json();
            if (!data.success) {
                alert('Operation failed: ' + (data.errors ? data.errors.join(', ') : 'Unknown error'));
            } else {
                await loadFiles(currentPath);
            }
        } catch (e: any) {
            alert('Request error: ' + e.message);
        } finally {
            modalActionLoading = false;
            closeModals();
        }
    }

    function closeModals() {
        showDeleteConfirm = false;
        showRenameModal = false;
        showMoveModal = false;
        showNewFolderModal = false;
        modalInput = '';
    }

    function promptRename() {
        const selected = Array.from(selectedFiles)[0];
        const file = files.find((f: any) => f.path === selected);
        if (file) {
            modalInput = file.path;
            showRenameModal = true;
        }
    }
</script>

<svelte:head>
    <title>File Browser - Rinkhals</title>
</svelte:head>

<div class="space-y-6 max-w-7xl mx-auto">
    <header class="flex flex-col xl:flex-row xl:items-end xl:justify-between gap-4 pb-4 border-b border-line-soft">
        <div>
            <p class="text-xs uppercase tracking-wider text-ink-faint font-medium">Files</p>
            <h2 class="text-3xl font-semibold text-ink mt-1 tracking-tight">File browser</h2>
        </div>
        <div class="relative">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" size={16} />
            <input
                bind:value={searchQuery}
                type="text"
                placeholder="Search files..."
                class="bg-canvas text-ink rounded-lg pl-9 pr-4 py-2 border border-line-soft focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/20 transition-colors text-sm w-64"
            />
        </div>
    </header>

    <!-- Toolbar -->
    <div class="bg-canvas rounded-xl p-3 border border-line-soft flex items-center justify-between min-h-14">
        <div class="flex items-center gap-2">
            <button onclick={() => { showNewFolderModal = true; modalInput = currentPath === '/' ? '/NewFolder' : currentPath + '/NewFolder'; }}
                class="flex items-center px-3 py-1.5 bg-surface hover:bg-surface-warm border border-line-soft rounded-lg text-sm font-medium transition-colors text-ink">
                <FolderPlus size={15} class="mr-2 text-ink-muted" /> New folder
            </button>
        </div>

        <div class="flex items-center gap-2">
            {#if selectedFiles.size > 0}
                <span class="text-sm text-ink-muted mr-2">{selectedFiles.size} selected</span>
                <button
                    onclick={promptRename}
                    disabled={selectedFiles.size !== 1}
                    class="flex items-center px-3 py-1.5 bg-surface hover:bg-brand-soft border border-line-soft disabled:opacity-40 disabled:hover:bg-surface text-brand rounded-lg text-sm font-medium transition-colors">
                    <Edit2 size={15} class="mr-2" /> Rename
                </button>
                <button
                    onclick={() => { showMoveModal = true; modalInput = currentPath === '/' ? '/target_directory' : currentPath; }}
                    class="flex items-center px-3 py-1.5 bg-surface hover:bg-surface-warm border border-line-soft text-accent-hover rounded-lg text-sm font-medium transition-colors">
                    <MoveRight size={15} class="mr-2" /> Move
                </button>
                <button
                    onclick={() => showDeleteConfirm = true}
                    class="flex items-center px-3 py-1.5 bg-surface-accent hover:bg-coral hover:text-white border border-coral/30 text-coral rounded-lg text-sm font-medium transition-colors">
                    <Trash2 size={15} class="mr-2" /> Delete
                </button>
            {/if}
        </div>
    </div>

    <div class="bg-canvas rounded-xl border border-line-soft overflow-hidden">
        <div class="bg-surface px-5 py-3 border-b border-line-soft flex items-center">
            <button
                onclick={goUp}
                disabled={currentPath === '/'}
                class="p-1.5 -ml-1 mr-3 text-ink-muted hover:text-brand disabled:opacity-40 disabled:cursor-not-allowed transition-colors rounded-lg hover:bg-canvas"
            >
                <ArrowUp size={18} />
            </button>
            <span class="text-ink-2 font-mono text-sm">{currentPath}</span>
        </div>

        <table class="w-full text-left">
            <thead class="bg-surface text-ink-muted border-b border-line-soft">
                <tr>
                    <th class="px-5 py-3 w-12">
                        <input type="checkbox"
                            checked={filteredFiles.length > 0 && selectedFiles.size === filteredFiles.length}
                            onclick={toggleAll}
                            class="rounded border-line text-brand focus:ring-brand/30 cursor-pointer"
                        />
                    </th>
                    <th class="px-5 py-3 font-semibold text-xs uppercase tracking-wider">Name</th>
                    <th class="px-5 py-3 font-semibold text-xs uppercase tracking-wider">Size</th>
                    <th class="px-5 py-3 font-semibold text-xs uppercase tracking-wider hidden sm:table-cell">Modified</th>
                    <th class="px-5 py-3 font-semibold text-xs uppercase tracking-wider text-right">Actions</th>
                </tr>
            </thead>
            <tbody class="divide-y divide-line-soft">
                {#if loading}
                    <tr><td colspan="5" class="px-5 py-8 text-center text-ink-faint">Loading files...</td></tr>
                {:else if error}
                    <tr><td colspan="5" class="px-5 py-8 text-center text-coral">Error: {error}</td></tr>
                {:else if filteredFiles.length === 0}
                    <tr><td colspan="5" class="px-5 py-8 text-center text-ink-faint">No files found.</td></tr>
                {:else}
                    {#each filteredFiles as file}
                        {@const isLink = file.type === 'link'}
                        {@const linkBroken = isLink && file.targetType === 'broken'}
                        {@const linkToFolder = isLink && file.targetType === 'folder'}
                        {@const linkToFile = isLink && file.targetType === 'file'}
                        {@const navigable = file.type === 'folder' || linkToFolder}
                        <tr onclick={() => handleItemClick(file)}
                            class="hover:bg-surface-warm transition-colors group {navigable || linkToFile ? 'cursor-pointer' : 'cursor-default'} {selectedFiles.has(file.path) ? 'bg-brand-soft/40' : ''} {linkBroken ? 'opacity-60' : ''}"
                            title={isLink ? `Symlink → ${file.linkTarget}${linkBroken ? ' (broken)' : ''}` : ''}>
                            <td class="px-5 py-3" onclick={(e) => e.stopPropagation()}>
                                <input type="checkbox"
                                    checked={selectedFiles.has(file.path)}
                                    onclick={(e) => toggleSelection(e, file.path)}
                                    class="rounded border-line text-brand focus:ring-brand/30 cursor-pointer"
                                />
                            </td>
                            <td class="px-5 py-3">
                                <div class="flex items-center gap-3 text-ink min-w-0">
                                    {#if linkBroken}
                                        <Link2Off size={18} class="text-coral shrink-0" />
                                    {:else if isLink}
                                        <Link2 size={18} class="text-accent shrink-0" />
                                    {:else if file.type === 'folder'}
                                        <Folder size={18} class="text-brand shrink-0" />
                                    {:else if file.name.endsWith('.log')}
                                        <FileText size={18} class="text-accent shrink-0" />
                                    {:else}
                                        <FileText size={18} class="text-ink-faint shrink-0" />
                                    {/if}
                                    <span class="group-hover:text-brand transition-colors text-sm truncate {linkBroken ? 'line-through' : ''}">{file.name}</span>
                                    {#if isLink && file.linkTarget}
                                        <span class="text-ink-faint text-xs truncate">&rarr; {file.linkTarget}{linkBroken ? ' (broken)' : ''}</span>
                                    {/if}
                                </div>
                            </td>
                            <td class="px-5 py-3 text-ink-muted text-sm">
                                {navigable ? '—' : isLink ? '—' : (file.size / 1024).toFixed(1) + ' KB'}
                            </td>
                            <td class="px-5 py-3 text-ink-muted text-sm hidden sm:table-cell">{file.modified}</td>
                            <td class="px-5 py-3 text-right">
                                {#if file.type === 'file' || linkToFile}
                                    {#if file.isText}
                                        <a
                                            href="/editor?path={encodeURIComponent(file.path)}"
                                            class="inline-block p-1.5 text-ink-muted hover:text-brand hover:bg-brand-soft rounded-lg transition-colors mr-1"
                                            title="Edit File"
                                            onclick={(e) => e.stopPropagation()}
                                        >
                                            <Edit2 size={16} />
                                        </a>
                                    {/if}
                                    <button
                                        onclick={(e) => handleDownload(e, file)}
                                        class="p-1.5 text-ink-muted hover:text-accent hover:bg-surface-warm rounded-lg transition-colors"
                                        title="Download"
                                    >
                                        <Download size={16} />
                                    </button>
                                {/if}
                            </td>
                        </tr>
                    {/each}
                {/if}
            </tbody>
        </table>
    </div>
</div>

<!-- Modals -->
{#if showDeleteConfirm}
<div class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
    <div class="bg-canvas border border-line rounded-2xl p-6 max-w-md w-full shadow-2xl">
        <div class="flex items-center text-coral mb-3">
            <AlertTriangle size={22} class="mr-2" />
            <h2 class="text-lg font-semibold text-ink">Confirm deletion</h2>
        </div>
        <p class="text-ink-2 text-sm mb-5">Delete {selectedFiles.size} selected item(s)? This cannot be undone.</p>
        <div class="flex justify-end gap-2">
            <button onclick={closeModals} class="px-4 py-2 rounded-lg font-medium bg-surface hover:bg-surface-warm border border-line-soft text-ink">Cancel</button>
            <button onclick={() => fsAction('delete', Array.from(selectedFiles))} class="px-4 py-2 rounded-lg font-medium bg-coral hover:opacity-90 text-white flex items-center">
                {#if modalActionLoading}<div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></div>{/if}
                Yes, delete
            </button>
        </div>
    </div>
</div>
{/if}

{#if showRenameModal}
<div class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
    <div class="bg-canvas border border-line rounded-2xl p-6 max-w-md w-full shadow-2xl">
        <h2 class="text-lg font-semibold text-ink mb-4">Rename item</h2>
        <input type="text" bind:value={modalInput} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink mb-5 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand" />
        <div class="flex justify-end gap-2">
            <button onclick={closeModals} class="px-4 py-2 rounded-lg font-medium bg-surface hover:bg-surface-warm border border-line-soft text-ink">Cancel</button>
            <button onclick={() => fsAction('rename', Array.from(selectedFiles), modalInput)} class="px-4 py-2 rounded-lg font-medium bg-brand hover:bg-brand-hover text-white flex items-center">
                {#if modalActionLoading}<div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></div>{/if}
                Rename
            </button>
        </div>
    </div>
</div>
{/if}

{#if showMoveModal}
<div class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
    <div class="bg-canvas border border-line rounded-2xl p-6 max-w-md w-full shadow-2xl">
        <h2 class="text-lg font-semibold text-ink mb-4">Move {selectedFiles.size} item(s)</h2>
        <label for="move_dest" class="block text-xs text-ink-muted mb-1">Destination directory (absolute path)</label>
        <input id="move_dest" type="text" bind:value={modalInput} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink mb-5 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
        <div class="flex justify-end gap-2">
            <button onclick={closeModals} class="px-4 py-2 rounded-lg font-medium bg-surface hover:bg-surface-warm border border-line-soft text-ink">Cancel</button>
            <button onclick={() => fsAction('move', Array.from(selectedFiles), modalInput)} class="px-4 py-2 rounded-lg font-medium bg-accent hover:bg-accent-hover text-white flex items-center">
                {#if modalActionLoading}<div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></div>{/if}
                Move
            </button>
        </div>
    </div>
</div>
{/if}

{#if showNewFolderModal}
<div class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
    <div class="bg-canvas border border-line rounded-2xl p-6 max-w-md w-full shadow-2xl">
        <h2 class="text-lg font-semibold text-ink mb-4">New folder</h2>
        <label for="new_folder" class="block text-xs text-ink-muted mb-1">Folder path</label>
        <input id="new_folder" type="text" bind:value={modalInput} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink mb-5 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand" />
        <div class="flex justify-end gap-2">
            <button onclick={closeModals} class="px-4 py-2 rounded-lg font-medium bg-surface hover:bg-surface-warm border border-line-soft text-ink">Cancel</button>
            <button onclick={() => fsAction('mkdir', [], modalInput)} class="px-4 py-2 rounded-lg font-medium bg-brand hover:bg-brand-hover text-white flex items-center">
                {#if modalActionLoading}<div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></div>{/if}
                Create
            </button>
        </div>
    </div>
</div>
{/if}
