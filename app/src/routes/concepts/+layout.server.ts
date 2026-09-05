import type { LayoutServerLoad } from "./$types";
import { redirect } from "@sveltejs/kit";
import { api } from "$lib/server/api";
import { can } from "$lib/caps";
import type { Source, Taxonomy } from "$lib/types";

// Reference lists for the /concepts subtree: the taxonomy switcher (concepts/+layout.svelte),
// the list/new pages (taxonomies) and the detail page's source tabs (sources). Reads require an
// authenticated user with can_read, so guard here — bounce anonymous visitors to login and
// not-yet-approved users to pending — before fetching, which also keeps the token attached.
export const load: LayoutServerLoad = async ({ locals, url, fetch }) => {
	if (!locals.user) redirect(303, `/login?redirectTo=${encodeURIComponent(url.pathname)}`);
	if (!can(locals.user, "can_read")) redirect(303, "/pending");

	const [taxonomies, sources] = await Promise.all([
		api<Taxonomy[]>("/taxonomies", { token: locals.token, fetch }),
		api<Source[]>("/sources", { token: locals.token, fetch }),
	]);

	return { taxonomies, sources };
};
