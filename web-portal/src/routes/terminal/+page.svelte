<script lang="ts">
	// The actual terminal UI (tabs, xterm, PTY WebSockets) lives in
	// $lib/TerminalPanel.svelte, mounted once by the root layout so shells
	// survive navigating to other pages. This route only needs to exist so
	// SvelteKit has something to match /terminal to, and to own the page title.
</script>

<svelte:head>
	<title>Terminal - Rinkhals</title>
</svelte:head>
