/* SEARCHING THE GUIDE
 * ===================
 * The server builds the index from the parsed Markdown (see $lib/server/docs): one entry per
 * `## Section {#id}` of every chapter the reader may open, so a hit links straight at the
 * paragraph it came from and a gated chapter never surfaces as one. It is fetched on the
 * first keystroke and kept for the session; scoring happens here, in the browser.
 *
 * Only a section's content is indexed — a chapter's intro, before its first heading, is not.
 */

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

// ---------------------------------------------------------------------------------------
// The index
// ---------------------------------------------------------------------------------------

const building = new Map<string, Promise<DocEntry[]>>();

/** The index for `user`, fetched once per session and audience; later calls reuse it. A
 *  failed fetch is not cached, so the next keystroke tries again. */
export function docIndex(user?: User | null): Promise<DocEntry[]> {
	const key = `${user?.id ?? ""}:${[...(user?.capabilities ?? [])].sort().join(",")}`;
	let index = building.get(key);
	if (!index) {
		index = fetch("/docs/search-index.json").then((res) => {
			if (!res.ok) throw new Error(`search index: HTTP ${res.status}`);
			return res.json() as Promise<DocEntry[]>;
		});
		index.catch(() => building.delete(key));
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
