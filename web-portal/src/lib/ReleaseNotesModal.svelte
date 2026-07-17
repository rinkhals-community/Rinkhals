<script lang="ts">
	import { X, ExternalLink } from "lucide-svelte";
	import { renderMarkdown } from "$lib/markdown";

	interface Props {
		title: string;
		subtitle?: string;
		body: string;
		externalUrl?: string;
		externalLabel?: string;
		onClose: () => void;
	}

	let { title, subtitle, body, externalUrl, externalLabel = "View on GitHub", onClose }: Props = $props();

	// Pre-render once; markdown bodies don't change while the modal is open.
	const html = $derived(renderMarkdown(body));

	function handleBackdrop(event: MouseEvent) {
		if (event.target === event.currentTarget) onClose();
	}

	function handleKey(event: KeyboardEvent) {
		if (event.key === "Escape") onClose();
	}
</script>

<svelte:window onkeydown={handleKey} />

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="fixed inset-0 bg-ink/40 backdrop-blur-sm flex items-center justify-center z-50 p-4"
	onclick={handleBackdrop}
>
	<div class="bg-canvas border border-line rounded-2xl max-w-2xl w-full max-h-[85vh] flex flex-col shadow-2xl">
		<header class="flex items-start justify-between gap-4 px-6 py-4 border-b border-line-soft shrink-0">
			<div class="min-w-0">
				<h2 class="text-lg font-semibold text-ink truncate">{title}</h2>
				{#if subtitle}
					<p class="text-xs text-ink-muted mt-0.5">{subtitle}</p>
				{/if}
			</div>
			<button
				type="button"
				onclick={onClose}
				aria-label="Close release notes"
				class="text-ink-faint hover:text-ink p-1 rounded-md hover:bg-surface-warm transition-colors shrink-0"
			>
				<X size={18} />
			</button>
		</header>

		<div class="flex-1 overflow-auto px-6 py-5">
			{#if html}
				<!-- The release-notes-prose class scopes typography styles (h1/h2/code/etc)
				     so we can render arbitrary markdown without it leaking into the rest of the UI. -->
				<div class="release-notes-prose text-sm text-ink leading-relaxed">
					{@html html}
				</div>
			{:else}
				<p class="text-sm text-ink-muted italic">No release notes provided.</p>
			{/if}
		</div>

		{#if externalUrl}
			<footer class="px-6 py-3 border-t border-line-soft flex justify-end shrink-0">
				<a
					href={externalUrl}
					target="_blank"
					rel="noopener noreferrer"
					class="inline-flex items-center gap-1.5 text-sm text-brand hover:underline"
				>
					{externalLabel}
					<ExternalLink size={14} />
				</a>
			</footer>
		{/if}
	</div>
</div>

<style>
	/* Minimal prose styles for rendered release notes. Tailwind v4's prose
	   plugin isn't pulled in, so we hand-roll just the elements release notes
	   actually use: headings, lists, code spans, code blocks, links, blockquotes. */
	:global(.release-notes-prose h1),
	:global(.release-notes-prose h2),
	:global(.release-notes-prose h3) {
		font-weight: 600;
		color: var(--color-ink, currentColor);
		margin-top: 1.25em;
		margin-bottom: 0.5em;
		line-height: 1.3;
	}
	:global(.release-notes-prose h1) { font-size: 1.15em; }
	:global(.release-notes-prose h2) { font-size: 1.05em; }
	:global(.release-notes-prose h3) { font-size: 1em; }
	:global(.release-notes-prose h1:first-child),
	:global(.release-notes-prose h2:first-child),
	:global(.release-notes-prose h3:first-child) {
		margin-top: 0;
	}
	:global(.release-notes-prose p) {
		margin: 0.75em 0;
	}
	:global(.release-notes-prose ul),
	:global(.release-notes-prose ol) {
		margin: 0.5em 0;
		padding-left: 1.5em;
	}
	:global(.release-notes-prose ul) { list-style: disc; }
	:global(.release-notes-prose ol) { list-style: decimal; }
	:global(.release-notes-prose li) {
		margin: 0.2em 0;
	}
	:global(.release-notes-prose a) {
		color: var(--color-brand, #3b82f6);
		text-decoration: underline;
	}
	:global(.release-notes-prose code) {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.875em;
		background: var(--color-surface-warm, rgba(0,0,0,0.05));
		padding: 0.1em 0.35em;
		border-radius: 0.25rem;
	}
	:global(.release-notes-prose pre) {
		background: var(--color-surface-warm, rgba(0,0,0,0.05));
		border: 1px solid var(--color-line-soft, rgba(0,0,0,0.1));
		border-radius: 0.5rem;
		padding: 0.75em 1em;
		overflow-x: auto;
		margin: 0.75em 0;
	}
	:global(.release-notes-prose pre code) {
		background: transparent;
		padding: 0;
		border-radius: 0;
	}
	:global(.release-notes-prose blockquote) {
		border-left: 3px solid var(--color-line, rgba(0,0,0,0.15));
		padding-left: 0.75em;
		color: var(--color-ink-muted, inherit);
		margin: 0.75em 0;
	}
	:global(.release-notes-prose hr) {
		border: none;
		border-top: 1px solid var(--color-line-soft, rgba(0,0,0,0.1));
		margin: 1em 0;
	}
	:global(.release-notes-prose strong) { font-weight: 600; }
	:global(.release-notes-prose em) { font-style: italic; }
</style>
