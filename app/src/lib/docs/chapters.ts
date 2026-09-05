/* KEEPING THIS GUIDE CURRENT
* ==========================
* The pages under `src/routes/docs/` are the in-app user guide. They describe the running
* app, not a plan for it: every change to a route, a control, a capability check or an API
* contract must be reflected here in the same commit. A guide that documents a button that
* no longer exists is worse than no guide, because a reader trusts it.
*
* The chapter list below is the single source of truth for the sidebar, the landing cards
* and the prev/next footer — add a chapter here and in `src/routes/docs/<slug>/+page.svelte`,
* nowhere else.
*/

import BookOpenIcon from "@lucide/svelte/icons/book-open";
import CompassIcon from "@lucide/svelte/icons/compass";
import SearchIcon from "@lucide/svelte/icons/search";
import DatabaseIcon from "@lucide/svelte/icons/database";
import PencilIcon from "@lucide/svelte/icons/pencil";
import ShieldIcon from "@lucide/svelte/icons/shield";
import PlugIcon from "@lucide/svelte/icons/plug";
import PackageIcon from "@lucide/svelte/icons/package";
import RocketIcon from "@lucide/svelte/icons/rocket";
import SettingsIcon from "@lucide/svelte/icons/settings";
import type { Component } from "svelte";
import { can } from "$lib/caps";
import type { User } from "$lib/types";

export interface Chapter {
	/** Route segment under /docs — "" is the landing page and is not listed as a chapter. */
	slug: string;
	title: string;
	/** One sentence, used on the landing card and as the page lede. */
	summary: string;
	icon: Component;
	/** Hidden from everyone without `can_admin`: sidebar, landing cards, prev/next and the
	 *  guide's search all go through `visibleChapters`. The route enforces it authoritatively
	 *  in `routes/docs/<slug>/+page.server.ts`. */
	adminOnly?: boolean;
}

export const chapters: Chapter[] = [
	{
		slug: "orientation",
		title: "Orientation",
		summary:
			"What this repository is, how a concept is put together, and what every part of the chrome around it does.",
		icon: CompassIcon,
	},
	{
		slug: "quick-start",
		title: "Quick start",
		summary:
			"From a fresh account to a variable in a data frame: a key, a project, one environment variable and a corr-vars snippet.",
		icon: RocketIcon,
	},
	{
		slug: "concepts",
		title: "Browsing concepts",
		summary:
			"The concept list, the detail page, source tabs, version history, documentation and retired concepts.",
		icon: BookOpenIcon,
	},
	{
		slug: "search",
		title: "Search and navigation",
		summary:
			"Finding a concept by any of its names, the taxonomy selector, the as-of date lens and stable links.",
		icon: SearchIcon,
	},
	{
		slug: "files",
		title: "Data files",
		summary:
			"The per-source file libraries, uuids and versions, which concepts read a file, and what an upload cascades into.",
		icon: DatabaseIcon,
	},
	{
		slug: "editing",
		title: "Editing and publishing",
		summary:
			"Drafts, the editor, validation, the review queue, publishing a version, naming, renaming and retiring.",
		icon: PencilIcon,
	},
	{
		slug: "capabilities",
		title: "Capabilities",
		summary:
			"The capability chain, what each one grants, why code is gated apart from definitions, and how to get one you are missing.",
		icon: ShieldIcon,
	},
	{
		slug: "clients",
		title: "Connecting clients",
		summary:
			"Programmatic access: API keys, the required project slug, curl requests and locked content.",
		icon: PlugIcon,
	},
	{
		slug: "corr-vars",
		title: "CORR Vars",
		summary:
			"The Python library that evaluates these definitions: installing it, configuring it, and resolving concepts into a cohort.",
		icon: PackageIcon,
	},
	{
		slug: "admin",
		title: "Administration",
		summary:
			"Admin-only: user management, granting capabilities, projects, their study context and licences, and the audit log.",
		icon: SettingsIcon,
		adminOnly: true,
	},
];

/** The chapters `user` may see, in reading order. Every list the guide renders — the sidebar,
 *  the landing cards, the prev/next footer, the search index — goes through here, so a gated
 *  chapter disappears from all of them at once. */
export function visibleChapters(user: User | null | undefined): Chapter[] {
	if (can(user, "can_admin")) return chapters;
	return chapters.filter((c) => !c.adminOnly);
}

export function chapterBySlug(slug: string): Chapter | undefined {
	return chapters.find((c) => c.slug === slug);
}

/** The chapters either side of `slug`, for the prev/next footer. Walks the list `user` can
 *  actually see, so the footer never offers a door that would bounce them. */
export function neighbours(
	slug: string,
	user?: User | null,
): { prev?: Chapter; next?: Chapter } {
	const visible = visibleChapters(user);
	const i = visible.findIndex((c) => c.slug === slug);
	if (i < 0) return {};
	return { prev: visible[i - 1], next: visible[i + 1] };
}
