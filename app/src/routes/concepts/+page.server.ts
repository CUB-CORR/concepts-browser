import type { PageServerLoad } from "./$types";
import { redirect } from "@sveltejs/kit";
import { can } from "$lib/caps";
import { PAGE_SIZE, fetchTable, tableRequest } from "$lib/server/concept-table";

// The concept browser. Reads now require an authenticated user with can_read: bounce anonymous
// visitors to login and not-yet-approved users (no can_read) to the pending page.
//
// The list is a table over thousands of names, so every one of its controls is a query param
// read here and handed straight to the API — sorting, filtering and searching all happen
// there. That is also what makes a link to a particular view shareable: the URL *is* the
// table's state. What is *not* in the URL is how far down you have scrolled: this load renders
// the first slice, and the browser asks `/concepts/table` for the next as the reader reaches
// the bottom.
export const load: PageServerLoad = async ({ url, parent, locals, fetch }) => {
	if (!locals.user) redirect(303, "/login?redirectTo=/concepts");
	if (!can(locals.user, "can_read")) redirect(303, "/pending");

	const { taxonomy, date } = await parent();
	const req = tableRequest(url, taxonomy, date, locals.user);
	const table = await fetchTable(req, locals.token, fetch);

	return {
		table,
		// The initial value of the search box; everything else the controls show is read off
		// the URL in the browser, which the page updates without re-running this load.
		q: req.q,
		pageSize: PAGE_SIZE,
		// The query this slice answers. The page compares it against the live URL to tell its
		// own shallow updates (already fetched in the browser) from a real navigation.
		query: url.search,
	};
};
