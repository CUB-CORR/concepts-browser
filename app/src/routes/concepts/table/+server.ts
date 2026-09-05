import type { RequestHandler } from "./$types";
import { error, json } from "@sveltejs/kit";
import { can } from "$lib/caps";
import { resolvePrefs } from "$lib/server/prefs";
import { fetchTable, tableRequest } from "$lib/server/concept-table";

// `GET /concepts/table` proxied for the browser. The concepts page calls this on every
// keystroke and every time the reader scrolls to the bottom, which is exactly why it exists:
// a full SvelteKit navigation would re-run the layout loads and re-render the page for what
// is really "give me rows", and the bearer token never leaves the server, so the browser
// cannot call the API itself.
//
// It takes the same query string the page URL carries — the request is built by the same
// `tableRequest` the page's `load` uses — plus `page`, which is the only piece of table state
// that is not in the URL (a scroll position is not something you share).
export const GET: RequestHandler = async ({ url, locals, cookies, fetch }) => {
	if (!locals.user) error(401, "Not signed in");
	if (!can(locals.user, "can_read")) error(403, "Browsing concepts requires the read capability.");

	const { taxonomy, date } = resolvePrefs(url, cookies);
	const page = Math.max(1, Number(url.searchParams.get("page") ?? 1) || 1);
	const req = tableRequest(url, taxonomy, date, locals.user, page);

	return json(await fetchTable(req, locals.token, fetch));
};
