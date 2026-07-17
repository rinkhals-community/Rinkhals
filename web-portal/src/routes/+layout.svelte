<script lang="ts">
	import { onMount } from "svelte";
	import { page } from "$app/stores";
	import "../app.css";
	import { LayoutDashboard, FolderOpen, Terminal, Settings, FileText, ScrollText, ShieldAlert, Sun, Moon, Monitor, Boxes, Cpu } from "lucide-svelte";
	import { themePreference, resolvedTheme, cycleTheme, type ThemePreference } from "$lib/theme";
	import TerminalPanel from "$lib/TerminalPanel.svelte";
	let { children } = $props();

	// The terminal panel is mounted here, once, for the lifetime of the app -
	// see TerminalPanel.svelte for why. Routing to /terminal only flips this
	// flag to swap CSS visibility; it never mounts/unmounts the panel.
	let onTerminalRoute = $derived($page.url.pathname.startsWith("/terminal"));

	const themeLabels: Record<ThemePreference, string> = {
		system: "System theme",
		light: "Light theme",
		dark: "Dark theme"
	};

	let showPasswordModal = $state(false);
	let newUsername = $state("admin");
	let newPassword = $state("");
	let confirmPassword = $state("");
	let errorMsg = $state("");

	const nav = [
		{ href: "/", label: "Dashboard", icon: LayoutDashboard },
		{ href: "/apps", label: "Apps", icon: Boxes },
		{ href: "/firmware", label: "Firmware", icon: Cpu },
		{ href: "/files", label: "File Browser", icon: FolderOpen },
		{ href: "/logs", label: "System Logs", icon: ScrollText },
		{ href: "/terminal", label: "Terminal", icon: Terminal },
		{ href: "/editor", label: "Text Editor", icon: FileText },
		{ href: "/management", label: "Manage Rinkhals", icon: Settings }
	];

	onMount(async () => {
		try {
			const host = import.meta.env.DEV ? "http://localhost:8090" : "";
			const res = await fetch(`${host}/api/auth/status`);
			if (res.ok) {
				const data = await res.json();
				if (data.is_default) {
					showPasswordModal = true;
				}
			}
		} catch (e) {
			console.error("Failed to fetch auth status", e);
		}
	});

	async function changePassword() {
		errorMsg = "";
		if (newPassword.length < 5) {
			errorMsg = "Password must be at least 5 characters.";
			return;
		}
		if (newPassword !== confirmPassword) {
			errorMsg = "Passwords do not match.";
			return;
		}
		try {
			const host = import.meta.env.DEV ? "http://localhost:8090" : "";
			const res = await fetch(`${host}/api/auth/change`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ username: newUsername, password: newPassword })
			});
			if (res.ok) {
				showPasswordModal = false;
				alert("Password changed out of default state. Please log in again using your new credentials. (The screen will refresh)");
				window.location.reload();
			} else {
				errorMsg = "Failed to update password. Server returned an error.";
			}
		} catch (e) {
			errorMsg = "Network error updating password.";
		}
	}
</script>

<div class="flex h-screen bg-canvas text-ink font-sans">
	<aside class="w-64 bg-surface border-r border-line-soft flex flex-col">
		<div class="h-20 flex items-center px-5 border-b border-line-soft gap-3">
			<div class="w-11 h-11 rounded-xl bg-canvas border border-line-soft flex items-center justify-center overflow-hidden shrink-0">
				<img src="/assets/logo.png" alt="Rinkhals Logo" class="w-9 h-9 object-contain" />
			</div>
			<div class="leading-tight">
				<h1 class="text-lg font-semibold text-ink tracking-tight">Rinkhals</h1>
				<p class="text-[11px] uppercase tracking-wider text-ink-faint">Printer Console</p>
			</div>
		</div>

		<nav class="flex-1 py-5 px-3 space-y-1">
			{#each nav as item}
				{@const Icon = item.icon}
				{@const active = $page.url.pathname === item.href || (item.href !== "/" && $page.url.pathname.startsWith(item.href))}
				<a
					href={item.href}
					class="flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-sm font-medium
						{active
							? 'bg-brand-soft text-brand'
							: 'text-ink-muted hover:bg-surface-warm hover:text-ink'}"
				>
					<Icon size={18} class={active ? "text-brand" : "text-ink-faint"} />
					<span>{item.label}</span>
				</a>
			{/each}
		</nav>

		<div class="px-3 py-3 border-t border-line-soft flex items-center gap-2">
			<button
				type="button"
				onclick={cycleTheme}
				title="Theme: {themeLabels[$themePreference]} (click to cycle)"
				aria-label="Cycle theme"
				class="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-medium text-ink-muted hover:bg-surface-warm hover:text-ink transition-colors border border-line-soft"
			>
				{#if $themePreference === "system"}
					<Monitor size={14} class="text-ink-muted" />
				{:else if $themePreference === "light"}
					<Sun size={14} class="text-ink-muted" />
				{:else}
					<Moon size={14} class="text-ink-muted" />
				{/if}
				<span class="capitalize">{$themePreference}</span>
				{#if $themePreference === "system"}
					<span class="text-ink-faint">({$resolvedTheme})</span>
				{/if}
			</button>
		</div>
	</aside>

	<main class="flex-1 flex flex-col h-screen overflow-hidden">
		<div class="flex-1 overflow-auto bg-canvas relative">
			<div class="p-8 h-full {onTerminalRoute ? 'hidden' : ''}">
				{@render children()}
			</div>
			<!-- Always mounted (never destroyed by routing); only hidden when not
			     on /terminal. This is what keeps shells alive across navigation. -->
			<div class="absolute inset-0 p-8 {onTerminalRoute ? '' : 'hidden'}">
				<TerminalPanel active={onTerminalRoute} />
			</div>
		</div>
	</main>
</div>

{#if showPasswordModal}
<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4">
	<div class="bg-canvas border border-line rounded-2xl max-w-md w-full p-6 shadow-2xl relative" onclick={(e) => e.stopPropagation()}>
		<div class="absolute -top-3 -right-3 bg-coral text-white text-xs font-semibold px-3 py-1 rounded-full shadow">Action Required</div>
		<h2 class="text-xl font-semibold text-ink mb-2 flex items-center gap-2">
			<ShieldAlert class="text-coral" size={22} /> Security warning
		</h2>
		<p class="text-ink-2 text-sm mb-5 pb-4 border-b border-line-soft">
			Rinkhals Web is using the default credentials (<strong>admin</strong>/<strong>rinkhals</strong>). Because this app exposes a raw terminal, please set a new password before going further.
		</p>

		<form class="space-y-4" onsubmit={(e) => { e.preventDefault(); changePassword(); }}>
			<div>
				<label class="block text-xs font-medium text-ink-muted mb-1" for="user">Username</label>
				<input id="user" type="text" bind:value={newUsername} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand" required />
			</div>
			<div>
				<label class="block text-xs font-medium text-ink-muted mb-1" for="pass">New password</label>
				<input id="pass" type="password" bind:value={newPassword} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand" required />
			</div>
			<div>
				<label class="block text-xs font-medium text-ink-muted mb-1" for="pass2">Confirm password</label>
				<input id="pass2" type="password" bind:value={confirmPassword} class="w-full bg-canvas border border-line rounded-lg px-3 py-2 text-ink focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand" required />
			</div>

			{#if errorMsg}
				<p class="text-coral text-sm">{errorMsg}</p>
			{/if}

			<div class="pt-2 flex justify-end">
				<button type="submit" class="px-5 py-2 bg-brand hover:bg-brand-hover text-white font-medium rounded-lg transition-colors shadow-sm">
					Save credentials
				</button>
			</div>
		</form>
	</div>
</div>
{/if}
