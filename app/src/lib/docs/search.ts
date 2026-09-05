/* SEARCHING THE GUIDE
 * ===================
 * The guide's chapters are hand-written Svelte components, not data, so there is nothing to
 * query at runtime. Rather than maintain a second copy of the prose that would immediately
 * drift, this module reads the chapter sources themselves — Vite's `import.meta.glob` with
 * `?raw` hands us each `+page.svelte` as a string — and reduces them to plain text keyed by
 * the `id` of the `DocSection` they sit in. Every section id is already an anchor, so a hit
 * links straight at the paragraph it came from.
 *
 * The glob is lazy: the sources are separate chunks, fetched on the first keystroke, so a
 * reader who never searches never downloads them.
 *
 * Consequences worth knowing when you write a chapter:
 *   - prose only lands in the index if it is inside a `<DocSection>`;
 *   - a code sample declared as a `const` in the page's `<script>` is indexed against the
 *     section that references it (`<CodeBlock code={curlRead} />`), as is any other string
 *     constant a section interpolates — that is how the capability table's prose is found;
 *   - a value imported from elsewhere (`pyTemplate(...)`) cannot be read from the source and
 *     is therefore not searchable.
 */

import { chapters, visibleChapters } from "./chapters";
import type { User } from "$lib/types";

/** One indexed section: the smallest thing a search result can point at. */
export interface DocEntry {
	slug: string;
	chapterTitle: string;
	sectionId: string;
	sectionTitle: string;
	/** The section's prose, flattened to a single line. */
	text: string;
	/** Position of the chapter in the guide, used to break ties in reading order. */
	order: number;
}

export interface DocHit extends DocEntry {
	href: string;
	score: number;
	/** The matched run of text with a little context either side, for the result list. */
	excerpt: { before: string; match: string; after: string };
}

const sources = import.meta.glob("/src/routes/docs/*/+page.svelte", {
	query: "?raw",
	import: "default",
}) as Record<string, () => Promise<string>>;

// ---------------------------------------------------------------------------------------
// Turning a component's source into text
// ---------------------------------------------------------------------------------------

const ENTITIES: Record<string, string> = {
	amp: "&",
	lt: "<",
	gt: ">",
	quot: '"',
	apos: "'",
	nbsp: " ",
	mdash: "—",
	ndash: "–",
	hellip: "…",
};

function unescapeEntities(s: string): string {
	return s.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (whole, body: string) => {
		if (body.startsWith("#")) {
			const code = body[1] === "x" || body[1] === "X"
				? parseInt(body.slice(2), 16)
				: parseInt(body.slice(1), 10);
			return Number.isFinite(code) ? String.fromCodePoint(code) : whole;
		}
		return ENTITIES[body.toLowerCase()] ?? whole;
	});
}

function collapse(s: string): string {
	return s.replace(/\s+/g, " ").trim();
}

/**
 * The string constants a page hoists into its `<script>`, keyed by name. The value of a
 * declaration is approximated by every string literal it contains joined together, which
 * covers both a lone template literal (a code sample) and an object of prose (the
 * capability table). Only search text is being built here, so the approximation is fine.
 */
function scriptConstants(script: string): Map<string, string> {
	const consts = new Map<string, string>();
	const decl = /(?:^|\n)\s*(?:const|let)\s+([A-Za-z_$][\w$]*)[^=\n]*=/g;
	let m: RegExpExecArray | null;
	const starts: { name: string; from: number }[] = [];
	while ((m = decl.exec(script))) starts.push({ name: m[1], from: m.index + m[0].length });
	for (let i = 0; i < starts.length; i++) {
		const body = script.slice(starts[i].from, starts[i + 1]?.from ?? script.length);
		const literals = body.match(/`[^`]*`|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/g);
		if (!literals) continue;
		const text = literals
			.map((lit) => lit.slice(1, -1).replace(/\\n/g, " ").replace(/\\(.)/g, "$1"))
			.join("\n");
		if (text.trim()) consts.set(starts[i].name, text);
	}
	return consts;
}

/** Strip a section's markup down to the words a reader sees. */
function sectionText(markup: string, consts: Map<string, string>): string {
	// Constants referenced from an attribute (`code={curlRead}`) are pulled out before the
	// tags carrying them are discarded.
	const referenced = new Set<string>();
	for (const [, name] of markup.matchAll(/=\{([A-Za-z_$][\w$]*)/g)) referenced.add(name);

	let text = markup
		.replace(/<!--[\s\S]*?-->/g, " ")
		// Svelte control flow and render tags carry no prose.
		.replace(/\{[#/:@][^}]*\}/g, " ")
		.replace(/<[^>]*>/g, " ");

	// Whatever interpolations survive tag-stripping were in the body: resolve the ones that
	// name a constant, drop the rest (they are runtime values, not prose).
	text = text.replace(/\{([^{}]*)\}/g, (_whole, expr: string) => {
		const id = /([A-Za-z_$][\w$]*)/.exec(expr)?.[1];
		if (id) referenced.add(id);
		return " ";
	});

	for (const name of referenced) {
		const value = consts.get(name);
		if (value) text += "\n" + value;
	}

	return collapse(unescapeEntities(text));
}

/** Split one chapter source into its `DocSection`s. */
function parseChapter(slug: string, source: string): DocEntry[] {
	const chapterIndex = chapters.findIndex((c) => c.slug === slug);
	const chapter = chapters[chapterIndex];
	if (!chapter) return [];

	const script = /<script[^>]*>([\s\S]*?)<\/script>/.exec(source)?.[1] ?? "";
	const consts = scriptConstants(script);
	const body = source.replace(/<script[^>]*>[\s\S]*?<\/script>/g, " ");

	const open = /<DocSection\b([^>]*)>/g;
	const found: { id: string; title: string; from: number }[] = [];
	let m: RegExpExecArray | null;
	while ((m = open.exec(body))) {
		const attrs = m[1];
		const id = /\bid="([^"]*)"/.exec(attrs)?.[1];
		const title = /\btitle="([^"]*)"/.exec(attrs)?.[1];
		if (id && title) found.push({ id, title, from: m.index + m[0].length });
	}

	return found.map((s, i) => ({
		slug,
		chapterTitle: chapter.title,
		sectionId: s.id,
		sectionTitle: unescapeEntities(s.title),
		text: sectionText(body.slice(s.from, found[i + 1]?.from ?? body.length), consts),
		order: chapterIndex,
	}));
}

// ---------------------------------------------------------------------------------------
// The index
// ---------------------------------------------------------------------------------------

const building = new Map<string, Promise<DocEntry[]>>();

/**
 * Build the index of the chapters `user` may read, once per session and per audience;
 * subsequent calls reuse the same promise.
 *
 * A gated chapter's source chunk is never requested, so it neither reaches the reader's
 * browser nor surfaces as a hit. The route guard is still the authoritative check — anyone
 * with `can_read` can ask the dev server for a chunk by name — but nothing the guide itself
 * does hands the content over.
 */
export function docIndex(user?: User | null): Promise<DocEntry[]> {
	const allowed = new Set(visibleChapters(user).map((c) => c.slug));
	const key = [...allowed].sort().join(",");

	let index = building.get(key);
	if (!index) {
		index = Promise.all(
			Object.entries(sources).map(async ([path, load]) => {
				const slug = /\/docs\/([^/]+)\/\+page\.svelte$/.exec(path)?.[1];
				return slug && allowed.has(slug) ? parseChapter(slug, await load()) : [];
			}),
		).then((per) => per.flat().sort((a, b) => a.order - b.order));
		building.set(key, index);
	}
	return index;
}

// ---------------------------------------------------------------------------------------
// Scoring
// ---------------------------------------------------------------------------------------

function tokenise(query: string): string[] {
	return query.toLowerCase().split(/\s+/).filter(Boolean);
}

/** True when `token` starts a word in `haystack` (already lowercased). */
function atWordStart(haystack: string, token: string): boolean {
	let i = haystack.indexOf(token);
	while (i >= 0) {
		if (i === 0 || !/[a-z0-9]/.test(haystack[i - 1])) return true;
		i = haystack.indexOf(token, i + 1);
	}
	return false;
}

function excerptAround(text: string, token: string): DocHit["excerpt"] {
	const at = text.toLowerCase().indexOf(token);
	if (at < 0) return { before: text.slice(0, 120), match: "", after: "" };
	const start = Math.max(0, at - 60);
	const end = Math.min(text.length, at + token.length + 90);
	return {
		before: (start > 0 ? "…" : "") + text.slice(start, at),
		match: text.slice(at, at + token.length),
		after: text.slice(at + token.length, end) + (end < text.length ? "…" : ""),
	};
}

/**
 * Rank every section against `query`. All tokens must appear somewhere in the section —
 * a title match outweighs a body match, and a hit on the whole phrase outweighs both.
 */
export function searchDocs(entries: DocEntry[], query: string, limit = 8): DocHit[] {
	const tokens = tokenise(query);
	if (!tokens.length) return [];
	const phrase = query.toLowerCase().trim();

	const hits: DocHit[] = [];
	for (const entry of entries) {
		const title = (entry.sectionTitle + " " + entry.chapterTitle).toLowerCase();
		const text = entry.text.toLowerCase();

		let score = 0;
		let matched = true;
		for (const token of tokens) {
			const inTitle = title.includes(token);
			const inText = text.includes(token);
			if (!inTitle && !inText) {
				matched = false;
				break;
			}
			if (inTitle) score += atWordStart(title, token) ? 10 : 6;
			if (inText) score += atWordStart(text, token) ? 3 : 1;
		}
		if (!matched) continue;

		if (tokens.length > 1) {
			if (title.includes(phrase)) score += 12;
			else if (text.includes(phrase)) score += 6;
		}

		// Excerpt from the longest token, which is the most distinctive one the reader typed.
		const pick = [...tokens].sort((a, b) => b.length - a.length);
		const inBody = pick.find((t) => text.includes(t)) ?? tokens[0];
		hits.push({
			...entry,
			href: `/docs/${entry.slug}#${entry.sectionId}`,
			score,
			excerpt: excerptAround(entry.text, inBody),
		});
	}

	return hits
		.sort((a, b) => b.score - a.score || a.order - b.order)
		.slice(0, limit);
}
