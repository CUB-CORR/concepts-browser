import type { PageServerLoad } from "./$types";
import { redirect } from "@sveltejs/kit";
import { can } from "$lib/caps";

// The chapter describes the admin-only pages, so it is gated like them. It is already hidden
// from the sidebar, the landing cards, the prev/next footer and the guide's search (see
// `visibleChapters` in $lib/docs/chapters), and this is what makes typing the URL no different.
// Anonymous visitors are bounced to sign-in by the docs layout; the redirect here keeps the
// shape of the /users and /audit guards, and sends a signed-in non-admin back to the guide
// rather than out of it.
export const load: PageServerLoad = async ({ locals }) => {
	if (!locals.user) redirect(303, "/login?redirectTo=/docs/admin");
	if (!can(locals.user, "can_admin")) redirect(303, "/docs");
	return {};
};
