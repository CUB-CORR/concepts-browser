import type { PageServerLoad } from "./$types";
import { redirect } from "@sveltejs/kit";
import { can } from "$lib/caps";

// The "waiting for approval" landing for authenticated users who have no can_read yet.
export const load: PageServerLoad = ({ locals }) => {
	if (!locals.user) redirect(303, "/login");
	// Already approved for reading ⇒ not pending; send them to the browser.
	if (can(locals.user, "can_read")) redirect(303, "/concepts");
	return { user: locals.user };
};
