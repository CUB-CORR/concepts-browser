import type { RequestHandler } from "./$types";
import { error, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import type { ConceptDetail } from "$lib/types";

// A concept id, resolved to the page that shows it: `/concepts/id/42` → the name URL with the
// member pinned. The id is the identity everything internal refers to (a successor link, a
// copied chip, an audit row), while the browsable page is addressed by a name — this is the
// one place that translation happens.
export const GET: RequestHandler = async ({ params, url, locals, fetch }) => {
	if (!locals.user) redirect(303, `/login?redirectTo=${encodeURIComponent(url.pathname)}`);
	if (!can(locals.user, "can_read")) redirect(303, "/pending");

	let concept: ConceptDetail;
	try {
		concept = await api<ConceptDetail>(`/concept/id/${encodeURIComponent(params.id)}`, {
			token: locals.token,
			fetch,
		});
	} catch (err) {
		if (err instanceof ApiError) error(err.status === 404 ? 404 : 502, err.message);
		throw err;
	}
	if (!concept.taxonomy || !concept.name)
		error(404, `Concept #${concept.id} holds no name to show it under.`);

	const date = url.searchParams.get("date");
	const query = new URLSearchParams({ cid: String(concept.id) });
	if (date) query.set("date", date);
	redirect(
		303,
		`/concepts/tax/${encodeURIComponent(concept.taxonomy)}/${encodeURIComponent(
			concept.name,
		)}?${query}`,
	);
};
