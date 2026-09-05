import type { PageServerLoad } from "./$types";
import { redirect } from "@sveltejs/kit";
import { api } from "$lib/server/api";
import { can } from "$lib/caps";
import type { AuditEventKind, AuditFilterOptions, AuditPage } from "$lib/types";

const PAGE_SIZE = 50;

// Admin-only: the audit log is a record of who read what. Anonymous → login; everyone else →
// concepts (same guard as the user-management page).
function guard(locals: App.Locals): void {
	if (!locals.user) redirect(303, "/login?redirectTo=/audit");
	if (!can(locals.user, "can_admin")) redirect(303, "/concepts");
}

const TABS: Record<string, AuditEventKind> = {
	calls: "api_call",
	emails: "email",
	logins: "login",
};

/** Every filter lives in the URL, so a filtered view is shareable and survives a reload.
 *  The date range is `from`/`to` — NOT `date`, which is the app-wide "as of" lens. */
function readFilters(url: URL) {
	const tab: AuditEventKind = TABS[url.searchParams.get("tab") ?? ""] ?? "login";
	const str = (k: string) => url.searchParams.get(k) || "";
	const num = (k: string) => (url.searchParams.get(k) ? Number(url.searchParams.get(k)) : null);

	// Each tab carries only the filters its event kind actually has columns for. A project or
	// concept means nothing for a login or an email, and a send status means nothing for a
	// request — applying a stale one across a tab switch would just empty the table.
	const isCalls = tab === "api_call";
	const isEmails = tab === "email";

	return {
		tab,
		from: str("from"),
		to: str("to"),
		userId: num("user"),
		projectId: isCalls ? str("project") : "",
		conceptId: isCalls ? num("concept") : null,
		// The API-calls tab is about external clients, so that's the default; "all" is the
		// explicit opt-out (app traffic is our own browsing, and mostly noise here).
		client: isCalls ? str("client") || "external" : "",
		emailStatus: isEmails ? str("status") : "",
		// The search box means "endpoint or concept" on the calls tab and "subject or
		// recipient" on the emails tab; the API ORs across all four, so one param serves both.
		q: isCalls || isEmails ? str("q") : "",
		page: Math.max(1, num("page") ?? 1),
	};
}

export const load: PageServerLoad = async ({ locals, url, fetch }) => {
	guard(locals);
	const f = readFilters(url);

	const [events, options] = await Promise.all([
		api<AuditPage>("/audit/events", {
			token: locals.token,
			fetch,
			query: {
				event: f.tab,
				client_type: f.client && f.client !== "all" ? f.client : null,
				user_id: f.userId,
				project_id: f.projectId || null,
				concept_id: f.conceptId,
				email_status: f.emailStatus && f.emailStatus !== "all" ? f.emailStatus : null,
				date_from: f.from || null,
				date_to: f.to || null,
				q: f.q || null,
				limit: PAGE_SIZE,
				offset: (f.page - 1) * PAGE_SIZE,
			},
		}),
		api<AuditFilterOptions>("/audit/filter-options", { token: locals.token, fetch }),
	]);

	return { events, options, filters: f, pageSize: PAGE_SIZE };
};
