import { marked } from "marked";
import DOMPurify from "dompurify";

// Configure marked once for the whole portal. GitHub-flavoured markdown is the
// closest match to release-notes bodies we render; `breaks: true` keeps
// single-newline behaviour matching how the bodies are authored in the GitHub
// release editor.
marked.setOptions({
	gfm: true,
	breaks: true
});

/**
 * Render a markdown string to HTML, sanitised so it's safe to drop into the DOM
 * via `{@html}`. Used by the release-notes modal; safe to reuse for any
 * Markdown-bodied content from untrusted (in our case, GitHub release bodies)
 * sources.
 *
 * Returns an empty string when the input is empty or non-string so callers can
 * pass `?.body` straight through.
 */
export function renderMarkdown(source: string | undefined | null): string {
	if (!source || typeof source !== "string") return "";
	const html = marked.parse(source) as string;
	return DOMPurify.sanitize(html, {
		USE_PROFILES: { html: true },
		ADD_ATTR: ["target", "rel"]
	});
}
