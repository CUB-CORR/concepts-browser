import type { RequestHandler } from "./$types";
import { error, json } from "@sveltejs/kit";
import { api } from "$lib/server/api";
import { can } from "$lib/caps";
import type { ConceptSearchResult } from "$lib/types";

// `GET /concepts/search` proxied for the pickers (add a pointer, choose a successor), which
// search as you type and therefore have to call from the browser — where the bearer token
// never goes. An empty term is answered here rather than upstream, which rejects it (422):
// a picker asks on every keystroke, including the one that empties the box.
export const GET: RequestHandler = async ({ url, locals, fetch }) => {
	if (!locals.user) error(401, "Not signed in");
	if (!can(locals.user, "can_read")) error(403, "Searching concepts requires the read capability.");

	const q = (url.searchParams.get("q") ?? "").trim();
	if (!q) return json([]);

	const results = await api<ConceptSearchResult[]>("/concepts/search", {
		token: locals.token,
		query: { q, limit: url.searchParams.get("limit") ?? 20 },
		fetch,
	});
	return json(results);
};
