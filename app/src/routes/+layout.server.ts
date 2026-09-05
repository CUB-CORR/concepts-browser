import type { LayoutServerLoad } from "./$types";
import { resolvePrefs } from "$lib/server/prefs";
import { api } from "$lib/server/api";
import { can } from "$lib/caps";
import type { PendingCounts } from "$lib/types";

// Runs for every page: exposes the session user and the resolved taxonomy/date prefs. The
// reference lists (taxonomies/sources) are fetched by `concepts/+layout.server.ts` instead —
// they're only needed under /concepts, and fetching them here would 401 on the anonymous
// login/pending pages (reads require can_read).
export const load: LayoutServerLoad = async ({ locals, url, cookies, fetch }) => {
	const prefs = resolvePrefs(url, cookies);

	return {
		user: locals.user,
		taxonomy: prefs.taxonomy,
		date: prefs.date,
		counts: await pendingCounts(locals, fetch),
	};
};

// The nav badges. Only asked for when the user can see at least one of the two queues, so the
// anonymous and read-only pages don't pay for a call that would come back empty anyway; a
// failure degrades to no badges rather than taking down every page in the app.
async function pendingCounts(
	locals: App.Locals,
	fetch: typeof globalThis.fetch,
): Promise<PendingCounts | null> {
	if (!can(locals.user, "can_publish") && !can(locals.user, "can_admin")) return null;
	try {
		return await api<PendingCounts>("/auth/pending-counts", { token: locals.token, fetch });
	} catch {
		return null;
	}
}
