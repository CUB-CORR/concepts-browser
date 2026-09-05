import type { Actions, PageServerLoad } from "./$types";
import { fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import type { DeprecationRequest, OpenDraft } from "$lib/types";

const STATUSES = ["pending", "approved", "rejected"] as const;
type Status = (typeof STATUSES)[number] | "all";

// Everything waiting for a decision, in one place: the drafts somebody wrote and did not
// publish, and the concepts somebody asked to retire. Both are otherwise only visible on the
// single concept page they belong to, which is how work sits unnoticed.
//
// Looking and deciding are the same capability, `can_publish` (the API gates both queues that
// way); the actions below re-check it because a page load is not an authorization.
function guard(locals: App.Locals, url: URL): void {
	if (!locals.user) redirect(303, `/login?redirectTo=${encodeURIComponent(url.pathname)}`);
	if (!can(locals.user, "can_publish")) redirect(303, "/concepts");
}

export const load: PageServerLoad = async ({ url, locals, fetch }) => {
	guard(locals, url);
	const asked = url.searchParams.get("status");
	const status: Status = (STATUSES as readonly string[]).includes(asked ?? "")
		? (asked as Status)
		: asked === "all"
			? "all"
			: "pending";

	const [drafts, requests] = await Promise.all([
		api<OpenDraft[]>("/drafts", { token: locals.token, fetch }),
		api<DeprecationRequest[]>("/deprecation-requests", {
			token: locals.token,
			query: { status: status === "all" ? undefined : status },
			fetch,
		}),
	]);
	return { drafts, requests, status, canDecide: can(locals.user, "can_publish") };
};

async function decide(
	locals: App.Locals,
	fetch: typeof globalThis.fetch,
	requestId: string,
	decision: "approve" | "reject",
	body?: unknown,
) {
	try {
		await api(`/deprecation-requests/${requestId}/${decision}`, {
			method: "POST",
			token: locals.token,
			body: body ?? {},
			fetch,
		});
	} catch (err) {
		if (err instanceof ApiError) return fail(err.status || 502, { error: err.message, requestId });
		throw err;
	}
	return { decided: requestId, decision };
}

export const actions: Actions = {
	// Retire the concept: stamps `deprecated_at` and the successor clients should follow. A
	// successor named here overrides the requester's suggestion; leaving it empty keeps it.
	approve: async ({ request, url, locals, fetch }) => {
		guard(locals, url);
		if (!can(locals.user, "can_publish"))
			return fail(403, { error: "Deciding a request requires the publish capability." });
		const form = await request.formData();
		const requestId = String(form.get("requestId") ?? "");
		if (!requestId) return fail(400, { error: "Missing request." });
		const successor = Number(form.get("successor_id"));
		return decide(locals, fetch, requestId, "approve", successor ? { successor_id: successor } : {});
	},

	// Close the request without touching the concept.
	reject: async ({ request, url, locals, fetch }) => {
		guard(locals, url);
		if (!can(locals.user, "can_publish"))
			return fail(403, { error: "Deciding a request requires the publish capability." });
		const form = await request.formData();
		const requestId = String(form.get("requestId") ?? "");
		if (!requestId) return fail(400, { error: "Missing request." });
		return decide(locals, fetch, requestId, "reject");
	},
};
