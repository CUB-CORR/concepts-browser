/* The prose behind the guide's capability table (`::capability-table`). It lives in code rather
 * than in the Markdown so the table iterates $lib/types.ALL_CAPABILITIES — a capability can never
 * be added to the app without appearing in it — and the "entails" column reads CAPABILITY_CHAIN,
 * so it cannot drift from the rule $lib/caps.hasCapability actually applies. Mirrors
 * api/security.ALL_CAPABILITIES. The search index reads `described` too (see $lib/server/docs). */

import { CAPABILITY_CHAIN } from "$lib/caps";

export const described: Record<string, { grants: string; where: string }> = {
	can_read: {
		grants:
			"Browse the repository: the concept list, search, a concept's JSON definition, its version history, its documentation, the data-file libraries, projects — and this guide. The entry ticket; without it you land on the approval-pending page.",
		where: "/concepts, /files, /projects, /docs",
	},
	can_read_detail: {
		grants:
			"Read what a concept *computes*, not just what it declares: the Python snippets, and the bytes of the data files those snippets read. Everything can_read sees, plus the code behind it.",
		where: "concept pages, /files",
	},
	can_edit: {
		grants:
			"Create concepts, write and update drafts, edit documentation, rename concepts, manage taxonomy names and request that a concept be retired. Nothing an editor does is visible to readers until it is published.",
		where: "/concepts/new, the editor on a concept page",
	},
	can_publish: {
		grants:
			"Turn a draft into a published version, work the review queue and decide deprecation requests, set a concept's documentation status, and upload a new version of a data file — which cascades a new published version into every concept that reads it.",
		where: "/review, concept pages, /files",
	},
	create_api_key: {
		grants:
			"Mint and revoke personal API keys for programmatic access. Ordinary keys are read-only; only an administrator can widen a key's scopes.",
		where: "/api-keys",
	},
	add_project: {
		grants: "Register a new project, which is what an API client names on every read.",
		where: "/projects/new",
	},
	can_admin: {
		grants:
			"Everything above, implicitly — plus user management, granting and revoking capabilities, and the audit log. Administrators are the only ones who can widen an API key's scopes.",
		where: "/users, /audit",
	},
};

/** The routes in a `where` column that are pages of their own, and so get a link. */
export const routeHref: Record<string, string> = {
	"/concepts": "/concepts",
	"/files": "/files",
	"/projects": "/projects",
	"/docs": "/docs",
	"/concepts/new": "/concepts/new",
	"/review": "/review",
	"/api-keys": "/api-keys",
	"/projects/new": "/projects/new",
	"/users": "/users",
	"/audit": "/audit",
};

/** The lesser chain capabilities a chain member entails, for the table's first column. */
export function entails(cap: string): readonly string[] {
	const rank = (CAPABILITY_CHAIN as readonly string[]).indexOf(cap);
	return rank <= 0 ? [] : (CAPABILITY_CHAIN as readonly string[]).slice(0, rank);
}
