<script lang="ts">
    import { RefreshCw, Download, Server, Trash2, AlertTriangle, ShieldAlert, Terminal, Lock, Cpu, CheckCircle2, ArrowUpCircle } from 'lucide-svelte';
    import { firmwareStatus } from "$lib/firmwareStatus";
    import PatchesCard from "$lib/PatchesCard.svelte";

    let loadingAction = $state<string | null>(null);
    let logs = $state<string>('');
    let showConfirmDialog = $state<boolean>(false);
    let actionToConfirm = $state<{id: string, name: string, description: string, icon: any} | null>(null);

    let isChangingPassword = $state(false);
    let authSaving = $state(false);
    let p_username = $state('admin');
    let p_current = $state('');
    let p_new = $state('');
    let p_confirm = $state('');
    let p_error = $state('');
    let p_success = $state('');

    const tools = [
        {
            id: 'debug-bundle',
            name: 'Generate debug bundle',
            description: 'Collect system logs and configs into a downloadable ZIP',
            icon: Download,
            danger: false,
            action: async () => {
                loadingAction = 'debug-bundle';
                try {
                    const res = await fetch('/api/tools?action=debug-bundle', { method: 'POST' });
                    if (res.ok) {
                        const blob = await res.blob();
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = 'debug-bundle.zip';
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                        window.URL.revokeObjectURL(url);
                        logs = 'Debug bundle generated and downloaded successfully.\n' + logs;
                    } else {
                        logs = `Failed to generate debug bundle: ${res.statusText}\n` + logs;
                    }
                } catch (e: any) {
                    logs = `Error: ${e.message}\n` + logs;
                } finally {
                    loadingAction = null;
                }
            }
        },
        { id: 'backup-partitions', name: 'Backup partitions', description: 'Backup critical system partitions', icon: Server, danger: false },
        { id: 'config-reset', name: 'Reset Rinkhals configuration', description: 'Reset configuration files to default (restarts services)', icon: RefreshCw, danger: true },
        { id: 'clean-rinkhals', name: 'Clean old Rinkhals', description: 'Remove leftover files from previous Rinkhals installations', icon: Trash2, danger: true },
        { id: 'uninstall-rinkhals', name: 'Uninstall Rinkhals', description: 'Completely remove Rinkhals and reboot into factory firmware', icon: ShieldAlert, danger: true }
    ];

    async function executeTool(id: string) {
        loadingAction = id;
        logs = `Executing ${id}...\n` + logs;
        try {
            const res = await fetch(`/api/tools?action=${id}`, { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                logs = `Success (${id}):\n${data.output}\n` + logs;
            } else {
                logs = `Failed (${id}):\n${data.output || 'Unknown error'}\n` + logs;
            }
        } catch (e: any) {
            logs = `Error (${id}): ${e.message}\n` + logs;
        } finally {
            loadingAction = null;
        }
    }

    function confirmAction(tool: any) {
        if (tool.danger) {
            actionToConfirm = tool;
            showConfirmDialog = true;
        } else {
            if (tool.action) {
                tool.action();
            } else {
                executeTool(tool.id);
            }
        }
    }

    function executeConfirmed() {
        if (actionToConfirm) {
            if (actionToConfirm.action) {
                actionToConfirm.action();
            } else {
                executeTool(actionToConfirm.id);
            }
            showConfirmDialog = false;
            actionToConfirm = null;
        }
    }

    async function changePassword() {
        p_error = "";
        p_success = "";
        if (!p_current) {
            p_error = "Current password is required to authorize the change.";
            return;
        }
        if (p_new.length < 5) {
            p_error = "New password must be at least 5 characters.";
            return;
        }
        if (p_new !== p_confirm) {
            p_error = "New passwords do not match.";
            return;
        }
        authSaving = true;
        try {
            const creds = btoa(`${p_username}:${p_current}`);
            const host = import.meta.env.DEV ? "http://localhost:8090" : "";
            const testRes = await fetch(`${host}/api/auth/status`, {
                headers: { 'Authorization': `Basic ${creds}` }
            });

            if (!testRes.ok) {
                p_error = "Current username/password is incorrect.";
                authSaving = false;
                return;
            }

            const res = await fetch(`${host}/api/auth/change`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    'Authorization': `Basic ${creds}`
                },
                body: JSON.stringify({ username: p_username, password: p_new })
            });

            if (res.ok) {
                p_success = "Password updated successfully. You will need to log in again using your new credentials. Refreshing page in 3 seconds...";
                setTimeout(() => { window.location.reload(); }, 3000);
            } else {
                p_error = "Failed to update password.";
            }
        } catch (e) {
            p_error = "Network or server error updating credentials.";
        }
        authSaving = false;
    }
</script>

<svelte:head>
    <title>Management - Rinkhals</title>
</svelte:head>

<div class="space-y-6 h-full flex flex-col max-w-7xl mx-auto w-full">
    <header class="pb-4 border-b border-line-soft">
        <p class="text-xs uppercase tracking-wider text-ink-faint font-medium">Administration</p>
        <h2 class="text-3xl font-semibold text-ink mt-1 tracking-tight">System management</h2>
        <p class="text-ink-muted text-sm mt-2">Perform maintenance tasks and configure the printer console.</p>
    </header>

    <!-- Firmware status card. Read-only summary that links to the Firmware page
         for the full catalog browse + (eventually) install flow. -->
    <section class="bg-canvas rounded-xl border border-line-soft p-5">
        <div class="flex items-start gap-3 mb-4">
            <div class="w-11 h-11 rounded-lg bg-brand-soft text-brand flex items-center justify-center shrink-0">
                <Cpu size={20} />
            </div>
            <div class="flex-1 min-w-0">
                <h3 class="text-base font-semibold text-ink">Firmware status</h3>
                <p class="text-ink-muted text-sm mt-1">
                    Current versions installed on this {$firmwareStatus.model_name || "printer"}.
                </p>
            </div>
            <a
                href="/firmware"
                class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-line-soft text-ink-muted hover:bg-surface-warm hover:text-ink transition-colors shrink-0"
            >
                Open Firmware
            </a>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div class="rounded-lg border border-line-soft bg-surface px-4 py-3">
                <div class="text-xs uppercase tracking-wider text-ink-faint mb-1">Anycubic firmware</div>
                <div class="text-lg font-semibold text-ink">{$firmwareStatus.current_firmware || "Unknown"}</div>
                {#if $firmwareStatus.latest_firmware}
                    <div class="mt-1 text-xs text-ink-muted flex items-center gap-1.5 flex-wrap">
                        <span>Latest: <span class="text-ink">{$firmwareStatus.latest_firmware}</span></span>
                        {#if $firmwareStatus.firmware_update_available}
                            <span class="inline-flex items-center gap-1 text-brand">
                                <ArrowUpCircle size={12} /> Update available
                            </span>
                        {:else}
                            <span class="inline-flex items-center gap-1 text-emerald">
                                <CheckCircle2 size={12} /> Up to date
                            </span>
                        {/if}
                    </div>
                {/if}
            </div>
            <div class="rounded-lg border border-line-soft bg-surface px-4 py-3">
                <div class="text-xs uppercase tracking-wider text-ink-faint mb-1">Rinkhals</div>
                <div class="text-lg font-semibold text-ink">{$firmwareStatus.current_rinkhals || "Unknown"}</div>
                {#if $firmwareStatus.latest_rinkhals}
                    <div class="mt-1 text-xs text-ink-muted flex items-center gap-1.5 flex-wrap">
                        <span>Latest: <span class="text-ink">{$firmwareStatus.latest_rinkhals}</span></span>
                        {#if $firmwareStatus.rinkhals_update_available}
                            <span class="inline-flex items-center gap-1 text-brand">
                                <ArrowUpCircle size={12} /> Update available
                            </span>
                        {:else}
                            <span class="inline-flex items-center gap-1 text-emerald">
                                <CheckCircle2 size={12} /> Up to date
                            </span>
                        {/if}
                    </div>
                {/if}
            </div>
        </div>
    </section>

    <PatchesCard />

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        {#each tools as tool}
            {@const Icon = tool.icon}
            <div class="bg-canvas rounded-xl p-5 border border-line-soft flex flex-col justify-between hover:border-brand/40 transition-colors">
                <div class="flex items-start mb-4">
                    <div class="w-11 h-11 rounded-lg flex items-center justify-center mr-3 shrink-0 {tool.danger ? 'bg-surface-accent text-coral' : 'bg-brand-soft text-brand'}">
                        <Icon size={20} />
                    </div>
                    <div>
                        <h3 class="font-semibold text-ink text-base">{tool.name}</h3>
                        <p class="text-ink-muted text-sm mt-1">{tool.description}</p>
                    </div>
                </div>
                <button
                    class="ml-auto w-full mt-2 py-2 px-4 rounded-lg font-medium transition-colors flex justify-center items-center
                    {tool.danger
                        ? 'bg-coral hover:opacity-90 text-white'
                        : 'bg-brand hover:bg-brand-hover text-white'}
                    {loadingAction ? 'opacity-50 cursor-not-allowed' : ''}"
                    disabled={loadingAction !== null}
                    onclick={() => confirmAction(tool)}
                >
                    {#if loadingAction === tool.id}
                        <div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></div>
                        Running...
                    {:else}
                        Execute
                    {/if}
                </button>
            </div>
        {/each}

        <!-- Password Change Card -->
        <div class="bg-canvas rounded-xl p-5 border border-line-soft flex flex-col justify-between hover:border-brand/40 transition-colors">
            <div>
                <div class="flex items-start mb-4">
                    <div class="w-11 h-11 rounded-lg bg-surface-warm text-accent flex items-center justify-center mr-3 shrink-0">
                        <Lock size={20} />
                    </div>
                    <div>
                        <h3 class="text-base font-semibold text-ink">Web authentication</h3>
                        <p class="text-ink-muted text-sm mt-1">Change the username and password used to access this portal.</p>
                    </div>
                </div>
            </div>
            <button
                class="w-full mt-2 px-4 py-2 rounded-lg font-medium transition-colors bg-surface hover:bg-surface-warm border border-line-soft text-ink"
                onclick={() => isChangingPassword = true}
            >
                Change credentials
            </button>
        </div>
    </div>

    <!-- Output Logs -->
    <div class="flex-1 mt-2 bg-canvas rounded-xl border border-line-soft flex flex-col min-h-64 overflow-hidden">
        <div class="px-4 py-2 border-b border-line-soft flex items-center justify-between bg-surface">
            <h3 class="font-medium text-sm text-ink-muted flex items-center">
                <Terminal size={15} class="mr-2 text-brand" /> Action output
            </h3>
        </div>
        <div class="p-4 flex-1 overflow-y-auto">
            <pre class="font-mono text-[13px] text-ink-2 whitespace-pre-wrap">{logs || 'No actions executed yet.'}</pre>
        </div>
    </div>
</div>

{#if showConfirmDialog}
    <div class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div class="bg-canvas border border-line rounded-2xl p-6 max-w-md w-full shadow-2xl">
            <div class="flex items-center text-coral mb-3">
                <AlertTriangle size={26} class="mr-2" />
                <h2 class="text-lg font-semibold text-ink">Dangerous action</h2>
            </div>

            <p class="text-ink-2 text-sm mb-2">
                Execute <strong class="text-ink">{actionToConfirm?.name}</strong>?
            </p>
            <p class="text-sm text-ink-muted mb-5">
                {actionToConfirm?.description}. This action cannot be easily undone.
            </p>

            <div class="flex justify-end gap-2">
                <button
                    class="px-4 py-2 rounded-lg font-medium bg-surface hover:bg-surface-warm border border-line-soft text-ink transition-colors"
                    onclick={() => { showConfirmDialog = false; actionToConfirm = null; }}
                >
                    Cancel
                </button>
                <button
                    class="px-4 py-2 rounded-lg font-medium bg-coral hover:opacity-90 text-white shadow-sm transition-colors"
                    onclick={executeConfirmed}
                >
                    Yes, execute
                </button>
            </div>
        </div>
    </div>
{/if}

{#if isChangingPassword}
    <div class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div class="bg-canvas border border-line rounded-2xl max-w-md w-full p-6 shadow-2xl">
            <h2 class="text-lg font-semibold text-ink mb-2 flex items-center gap-2">
                <Lock class="text-accent" size={20} /> Change credentials
            </h2>
            <p class="text-ink-muted text-sm mb-5 pb-4 border-b border-line-soft">
                Update the authentication required to reach this web interface.
            </p>

            <form onsubmit={(e) => { e.preventDefault(); changePassword(); }} class="space-y-4">
                <div>
                    <label class="block text-xs font-medium text-ink-muted mb-1" for="p_user">Username</label>
                    <input id="p_user" type="text" bind:value={p_username} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand" required />
                </div>
                <div>
                    <label class="block text-xs font-medium text-ink-muted mb-1" for="p_curr">Current password</label>
                    <input id="p_curr" type="password" bind:value={p_current} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand" required />
                </div>
                <div class="pt-2">
                    <label class="block text-xs font-medium text-ink-muted mb-1" for="p_new">New password</label>
                    <input id="p_new" type="password" bind:value={p_new} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand" required />
                </div>
                <div>
                    <label class="block text-xs font-medium text-ink-muted mb-1" for="p_conf">Confirm new password</label>
                    <input id="p_conf" type="password" bind:value={p_confirm} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand" required />
                </div>

                {#if p_error}
                    <p class="text-coral text-sm bg-surface-accent p-3 rounded-lg">{p_error}</p>
                {/if}
                {#if p_success}
                    <p class="text-brand text-sm bg-brand-soft p-3 rounded-lg">{p_success}</p>
                {/if}

                <div class="flex justify-end gap-2 pt-2">
                    <button
                        type="button"
                        class="px-4 py-2 rounded-lg font-medium bg-surface hover:bg-surface-warm border border-line-soft text-ink transition-colors"
                        onclick={() => { isChangingPassword = false; p_error = ''; p_success = ''; p_current = ''; p_new = ''; p_confirm = ''; }}
                        disabled={authSaving || p_success !== ''}
                    >
                        Cancel
                    </button>
                    <button
                        type="submit"
                        class="px-4 py-2 rounded-lg font-medium bg-brand hover:bg-brand-hover text-white shadow-sm transition-colors flex items-center justify-center disabled:opacity-50 {authSaving ? 'animate-pulse' : ''}"
                        disabled={authSaving || p_success !== ''}
                    >
                        {authSaving ? "Saving..." : "Save credentials"}
                    </button>
                </div>
            </form>
        </div>
    </div>
{/if}
