/* The user guide's data, as the server hands it to the pages. Client-safe: nothing here
 * touches the file system — loading and parsing live in $lib/server/docs. */

/// <reference types="mdast-util-directive" />
import type { RootContent } from "mdast";
import type { DocCondition } from "./conditions";

/** One parsed Markdown node (mdast, with GFM and directive nodes), stripped of positions. */
export type DocNode = RootContent;

/** A chapter as the sidebar, the landing cards and the prev/next footer list it. */
export interface ChapterMeta {
	slug: string;
	title: string;
	/** One sentence, used on the landing card and as the page lede. */
	summary: string;
	/** A name from $lib/docs/icons; unknown names fall back to a generic page icon. */
	icon: string;
	adminOnly: boolean;
}

/** An entry of a link group: shown in the guide's sidebar and in the top bar's Docs menu. */
export interface DocLink {
	/** Optional handle for `:external[...]{id=...}` and `:::if{link=...}` in the pages. */
	id?: string;
	label: string;
	href: string;
}

/** The guide's navigation, in reading order: chapters, interleaved with link groups at the
 *  position their file's number puts them. */
export type NavEntry =
	| ({ kind: "chapter" } & ChapterMeta)
	| { kind: "links"; slug: string; links: DocLink[] };

/** A `## Title {#id}` heading and everything up to the next one. */
export interface DocSectionData {
	id: string;
	title: string;
	nodes: DocNode[];
	/** Set when a top-level `:::if` / `:::unless` wraps the section (see $lib/docs/conditions). */
	condition?: DocCondition;
}

/** A page's body: what comes before its first section, then the sections. */
export interface DocBody {
	intro: DocNode[];
	sections: DocSectionData[];
}

/** What every page gets from the root layout: enough to render the Docs menu and to know
 *  which chapters a link may point at without bouncing the reader. */
export interface DocsMenu {
	links: DocLink[];
	/** Slugs of the chapters this reader may open. */
	slugs: string[];
}

/** Links leave the app when they are absolute, or point at the API (which the proxy serves
 *  beside the app, e.g. its generated reference under /api/public/docs). */
export function isExternalHref(href: string): boolean {
	return /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("/api/") || href === "/api";
}
