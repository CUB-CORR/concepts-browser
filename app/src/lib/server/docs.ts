/* THE USER GUIDE
 * ==============
 * The guide is a folder of Markdown files, not code. Two folders, merged by slug:
 *
 *   app/docs/          shipped with the image (bundled at build time)
 *   $DOCS_DIR          a deployment's own folder, read at runtime (optional)
 *
 * A file is `NN-slug.md`: the number orders it in the guide, the slug is its URL
 * (/docs/<slug>). A deployment file whose slug matches a shipped one takes it over:
 *
 *   - with a body, it replaces the shipped page's content;
 *   - with frontmatter only, it keeps the shipped content and overrides just those fields
 *     (title, summary, icon, admin_only — and the order, if its name carries a number);
 *   - with `hidden: true`, the page is gone: no sidebar entry, no card, no search hit, a 404.
 *
 * A new slug adds a page. Two slugs are special: `index` is the guide's landing page, and a
 * file whose frontmatter has `links:` is a link group — shown in the sidebar at its position
 * and in the top bar's Docs menu (99-external-links.md ships the default ones).
 *
 * The Markdown is parsed here into mdast and rendered by $lib/components/docs/Markdown.svelte
 * through the same components a hand-written page would use; see that component for the
 * directives (`:cap[...]`, `:::alert[...]`, …) the pages may use. Raw HTML is ignored.
 *
 * Parsed once and cached in production — a changed folder takes a restart. In development
 * every request re-reads both folders, so edits show on reload.
 *
 * Keeping the shipped guide current: the pages in app/docs describe the running app, not a
 * plan for it. Every change to a route, a control, a capability check or an API contract must
 * be reflected there in the same commit — a guide that documents a button that no longer
 * exists is worse than none, because a reader trusts it.
 */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { dev } from "$app/environment";
import { env } from "$env/dynamic/private";
import { parse as parseYaml } from "yaml";
import { fromMarkdown } from "mdast-util-from-markdown";
import { gfm } from "micromark-extension-gfm";
import { gfmFromMarkdown } from "mdast-util-gfm";
import { directive } from "micromark-extension-directive";
import { directiveFromMarkdown } from "mdast-util-directive";
import type { Heading, Nodes, RootContent } from "mdast";
import type { ContainerDirective } from "mdast-util-directive";
import type { DocCondition } from "$lib/docs/conditions";
import { can } from "$lib/caps";
import { described } from "$lib/docs/capabilities";
import type { DocEntry } from "$lib/docs/search";
import type {
	ChapterMeta,
	DocBody,
	DocLink,
	DocNode,
	DocsMenu,
	NavEntry,
} from "$lib/docs/types";
import type { User } from "$lib/types";

const builtIn = import.meta.glob("/docs/*.md", {
	query: "?raw",
	import: "default",
	eager: true,
}) as Record<string, string>;

/** `NN-slug.md` or `slug.md`. */
const FILE_NAME = /^(?:(\d+)-)?([a-z0-9][a-z0-9-]*)\.md$/;
const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/;
/** A `## Title {#id}` heading's explicit anchor. */
const HEADING_ID = /\s*\{#([A-Za-z0-9_-]+)\}\s*$/;

/** The directives Markdown.svelte renders, by kind; anything else is reported at load. */
const DIRECTIVES = {
	textDirective: ["cap", "badge", "app-name", "external"],
	leafDirective: ["data-model", "capability-chain", "capability-table", "py-template"],
	containerDirective: ["alert", "if", "unless"],
} as const;

interface SourceFile {
	slug: string;
	order: number | null;
	meta: Record<string, unknown>;
	body: string | null;
	origin: string;
}

interface Page {
	slug: string;
	order: number;
	meta: ChapterMeta;
	body: DocBody;
}

interface LinkGroup {
	slug: string;
	order: number;
	links: DocLink[];
}

interface Docs {
	/** Chapters and link groups in reading order. */
	nav: (({ kind: "chapter" } & Page) | ({ kind: "links" } & LinkGroup))[];
	chapters: Map<string, Page>;
	index: { title: string; body: DocBody };
}

// ---------------------------------------------------------------------------------------
// Reading the folders
// ---------------------------------------------------------------------------------------

function readSource(
	name: string,
	text: string,
	origin: string,
	warn: (m: string) => void,
): SourceFile | null {
	const m = FILE_NAME.exec(name);
	if (!m) {
		warn(`${origin}: ignored — name it NN-slug.md (lowercase letters, digits, dashes)`);
		return null;
	}
	let meta: Record<string, unknown> = {};
	let body = text;
	const fm = FRONTMATTER.exec(text);
	if (fm) {
		body = text.slice(fm[0].length);
		try {
			const parsed = parseYaml(fm[1]);
			if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
				meta = parsed as Record<string, unknown>;
			} else if (parsed != null) {
				warn(`${origin}: frontmatter is not a mapping — ignored`);
			}
		} catch (err) {
			warn(`${origin}: invalid frontmatter (${(err as Error).message}) — file ignored`);
			return null;
		}
	}
	return {
		slug: m[2],
		order: m[1] === undefined ? null : Number(m[1]),
		meta,
		body: body.trim() ? body : null,
		origin,
	};
}

function readBuiltIn(warn: (m: string) => void): SourceFile[] {
	return Object.entries(builtIn).flatMap(([path, text]) => {
		const name = path.slice(path.lastIndexOf("/") + 1);
		return readSource(name, text, `app${path}`, warn) ?? [];
	});
}

function readCustom(warn: (m: string) => void): SourceFile[] {
	const dir = env.DOCS_DIR;
	if (!dir) return [];
	if (!existsSync(dir) || !statSync(dir).isDirectory()) {
		warn(`DOCS_DIR=${dir} is not a directory — using the shipped guide only`);
		return [];
	}
	return readdirSync(dir)
		.filter((name) => name.endsWith(".md"))
		.sort()
		.flatMap((name) => {
			const path = join(dir, name);
			return readSource(name, readFileSync(path, "utf8"), path, warn) ?? [];
		});
}

function bySlug(files: SourceFile[], warn: (m: string) => void): Map<string, SourceFile> {
	const map = new Map<string, SourceFile>();
	for (const f of files) {
		const seen = map.get(f.slug);
		if (seen) warn(`${f.origin}: slug "${f.slug}" is also used by ${seen.origin} — ignored`);
		else map.set(f.slug, f);
	}
	return map;
}

// ---------------------------------------------------------------------------------------
// Parsing a page
// ---------------------------------------------------------------------------------------

function stripPositions(node: Nodes): void {
	delete node.position;
	if ("children" in node) for (const child of node.children) stripPositions(child);
}

/** The words of a node tree, for titles and the search index. */
function toText(nodes: readonly Nodes[]): string {
	let out = "";
	for (const node of nodes) {
		if (node.type === "text" || node.type === "inlineCode" || node.type === "code") {
			out += node.value + " ";
		} else if (node.type === "leafDirective" && node.name === "capability-table") {
			for (const [cap, d] of Object.entries(described)) out += `${cap} ${d.grants} ${d.where} `;
		} else if ("children" in node) {
			out += toText(node.children) + " ";
		}
	}
	return out;
}

function collapse(s: string): string {
	return s.replace(/\s+/g, " ").trim();
}

function slugify(s: string): string {
	return s
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/^-+|-+$/g, "");
}

function parseBody(markdown: string): DocBody {
	const tree = fromMarkdown(markdown, {
		extensions: [gfm(), directive()],
		mdastExtensions: [gfmFromMarkdown(), directiveFromMarkdown()],
	});
	stripPositions(tree);

	const body: DocBody = { intro: [], sections: [] };
	const add = (nodes: RootContent[], condition?: DocCondition) => {
		for (const node of nodes) {
			if (node.type === "heading" && node.depth === 2) {
				body.sections.push({ ...sectionHead(node), nodes: [], ...(condition ? { condition } : {}) });
			} else if (isConditional(node) && node.children.some(isSectionHeading)) {
				// A top-level `:::if` around whole sections: its sections carry the condition, and
				// whatever precedes its first heading stays conditional where it lands.
				const own: DocCondition = {
					negate: node.name === "unless",
					attributes: Object.fromEntries(
						Object.entries(node.attributes ?? {}).map(([k, v]) => [k, v ?? ""]),
					),
				};
				const first = node.children.findIndex(isSectionHeading);
				if (first > 0) place({ ...node, children: node.children.slice(0, first) });
				add(node.children.slice(first), own);
			} else {
				place(node);
			}
		}
	};
	const place = (node: RootContent) => (body.sections.at(-1)?.nodes ?? body.intro).push(node);
	add(tree.children);
	return body;
}

function isSectionHeading(node: RootContent): boolean {
	return node.type === "heading" && node.depth === 2;
}

function isConditional(node: RootContent): node is ContainerDirective {
	return node.type === "containerDirective" && (node.name === "if" || node.name === "unless");
}

/** A `## Title {#id}` heading's anchor and plain-text title; the id defaults to the title
 *  slugified. */
function sectionHead(node: Heading): { id: string; title: string } {
	let id = "";
	const last = node.children.at(-1);
	if (last?.type === "text") {
		const m = HEADING_ID.exec(last.value);
		if (m) {
			id = m[1];
			last.value = last.value.slice(0, m.index);
		}
	}
	const title = collapse(toText(node.children));
	return { id: id || slugify(title), title };
}

function bodyNodes(body: DocBody): DocNode[] {
	return [...body.intro, ...body.sections.flatMap((s) => s.nodes)];
}

function walk(nodes: readonly Nodes[], visit: (node: Nodes) => void): void {
	for (const node of nodes) {
		visit(node);
		if ("children" in node) walk(node.children, visit);
	}
}

// ---------------------------------------------------------------------------------------
// Merging the folders
// ---------------------------------------------------------------------------------------

function str(value: unknown): string | undefined {
	return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function readLinks(value: unknown, origin: string, warn: (m: string) => void): DocLink[] {
	if (!Array.isArray(value)) {
		warn(`${origin}: \`links\` must be a list — ignored`);
		return [];
	}
	return value.flatMap((item) => {
		const label = str(item?.label);
		const href = str(item?.href);
		if (!label || !href) {
			warn(`${origin}: every link needs a label and an href — one ignored`);
			return [];
		}
		const id = str(item?.id);
		return [id ? { id, label, href } : { label, href }];
	});
}

function build(): Docs {
	const warnings: string[] = [];
	const warn = (m: string) => warnings.push(m);

	const shipped = bySlug(readBuiltIn(warn), warn);
	const custom = bySlug(readCustom(warn), warn);

	const nav: Docs["nav"] = [];
	const chapters = new Map<string, Page>();
	let index: Docs["index"] = { title: "User guide", body: { intro: [], sections: [] } };

	for (const slug of new Set([...shipped.keys(), ...custom.keys()])) {
		const base = shipped.get(slug);
		const over = custom.get(slug);
		const origin = over?.origin ?? base!.origin;
		const meta = { ...base?.meta, ...over?.meta };
		if (meta.hidden === true) continue;

		const text = over?.body ?? base?.body ?? null;
		const order = over?.order ?? base?.order ?? Number.POSITIVE_INFINITY;

		if (slug === "index") {
			index = { title: str(meta.title) ?? "User guide", body: parseBody(text ?? "") };
		} else if (meta.links !== undefined) {
			nav.push({ kind: "links", slug, order, links: readLinks(meta.links, origin, warn) });
		} else {
			if (!text) warn(`${origin}: page "${slug}" has no content`);
			if (!str(meta.title)) warn(`${origin}: page "${slug}" has no title`);
			if (order === Number.POSITIVE_INFINITY) {
				warn(`${origin}: page "${slug}" has no number — listed last (name it NN-${slug}.md)`);
			}
			const page: Page = {
				slug,
				order,
				meta: {
					slug,
					title: str(meta.title) ?? slug,
					summary: str(meta.summary) ?? "",
					icon: str(meta.icon) ?? "file-text",
					adminOnly: meta.admin_only === true,
				},
				body: parseBody(text ?? ""),
			};
			chapters.set(slug, page);
			nav.push({ kind: "chapter", ...page });
		}
	}

	nav.sort((a, b) => a.order - b.order || a.slug.localeCompare(b.slug));
	check(chapters, index, nav, warn);
	for (const w of warnings) {
		// In development the folders are re-read on every request; say each thing once.
		if (reported.has(w)) continue;
		reported.add(w);
		console.warn(`[docs] ${w}`);
	}
	return { nav, chapters, index };
}

/** Report what would otherwise only show as a broken page: a link into a chapter that does
 *  not exist (or was hidden), and a directive the renderer does not know. */
function check(
	chapters: Map<string, Page>,
	index: Docs["index"],
	nav: Docs["nav"],
	warn: (m: string) => void,
): void {
	const linkIds = new Set(
		nav.flatMap((e) => (e.kind === "links" ? e.links.flatMap((l) => l.id ?? []) : [])),
	);
	const pages: [string, DocBody][] = [
		["index", index.body],
		...[...chapters.values()].map((p): [string, DocBody] => [p.slug, p.body]),
	];
	for (const [slug, body] of pages) {
		walk(bodyNodes(body), (node) => {
			if (node.type === "link" && node.url.startsWith("/docs/")) {
				const target = /^\/docs\/([^/#?]+)/.exec(node.url)?.[1];
				if (target && !chapters.has(target)) {
					warn(`page "${slug}" links to ${node.url}, but there is no chapter "${target}"`);
				}
			}
			if (
				node.type === "textDirective" ||
				node.type === "leafDirective" ||
				node.type === "containerDirective"
			) {
				const known: readonly string[] = DIRECTIVES[node.type];
				if (!known.includes(node.name)) {
					warn(`page "${slug}": unknown directive "${node.name}" (rendered as plain text)`);
				}
				if (node.name === "external" && !linkIds.has(node.attributes?.id ?? "")) {
					warn(`page "${slug}": :external names link id "${node.attributes?.id}", which no link group defines`);
				}
			}
		});
	}
}

let cached: Docs | null = null;
const reported = new Set<string>();

function docs(): Docs {
	if (dev || !cached) cached = build();
	return cached;
}

// ---------------------------------------------------------------------------------------
// What the routes ask for
// ---------------------------------------------------------------------------------------

function visible(page: Page, user: User | null | undefined): boolean {
	return !page.meta.adminOnly || can(user, "can_admin");
}

/** The guide's sidebar: the chapters `user` may open, and the link groups. */
export function docsNav(user: User | null | undefined): NavEntry[] {
	return docs().nav.flatMap((e): NavEntry[] => {
		if (e.kind === "links") return [{ kind: "links", slug: e.slug, links: e.links }];
		return visible(e, user) ? [{ kind: "chapter", ...e.meta }] : [];
	});
}

/** The top bar's Docs menu and the chapters a link may point at, for every page. */
export function docsMenu(user: User | null | undefined): DocsMenu {
	const nav = docsNav(user);
	return {
		links: nav.flatMap((e) => (e.kind === "links" ? e.links : [])),
		slugs: user ? nav.flatMap((e) => (e.kind === "chapter" ? [e.slug] : [])) : [],
	};
}

export function docsIndex(): Docs["index"] {
	return docs().index;
}

export type ChapterResult =
	| { meta: ChapterMeta; body: DocBody; prev: ChapterMeta | null; next: ChapterMeta | null }
	| "missing"
	| "forbidden";

/** One chapter with its neighbours among the chapters `user` may open, so the prev/next
 *  footer never offers a door that would bounce them. */
export function docsChapter(slug: string, user: User | null | undefined): ChapterResult {
	const page = docs().chapters.get(slug);
	if (!page) return "missing";
	if (!visible(page, user)) return "forbidden";
	const around = docsNav(user).filter((e) => e.kind === "chapter");
	const i = around.findIndex((c) => c.slug === slug);
	const meta = (e: NavEntry | undefined) => (e?.kind === "chapter" ? strip(e) : null);
	return { meta: page.meta, body: page.body, prev: meta(around[i - 1]), next: meta(around[i + 1]) };
}

function strip(e: { kind: "chapter" } & ChapterMeta): ChapterMeta {
	const { kind: _kind, ...meta } = e;
	return meta;
}

/** The guide's search index: one entry per section of every chapter `user` may open. */
export function docsSearchEntries(user: User | null | undefined): DocEntry[] {
	const entries: DocEntry[] = [];
	let order = 0;
	for (const e of docs().nav) {
		if (e.kind !== "chapter" || !visible(e, user)) continue;
		for (const s of e.body.sections) {
			entries.push({
				slug: e.slug,
				chapterTitle: e.meta.title,
				sectionId: s.id,
				sectionTitle: s.title,
				text: collapse(toText(s.nodes as RootContent[])),
				order,
			});
		}
		order++;
	}
	return entries;
}
