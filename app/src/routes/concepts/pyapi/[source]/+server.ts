import type { RequestHandler } from "./$types";
import { error } from "@sveltejs/kit";
import { apiRaw } from "$lib/server/api";
import { can } from "$lib/caps";

// The code editor's completion surface for one source (`GET /sources/{key}/pyapi`), proxied so
// the browser can fetch it without ever seeing the bearer token.
//
// It is deliberately *not* part of the page's `load`: the document is ~250 KB of generated
// names, which would be serialized into every concept page's SSR payload for the benefit of
// the few visitors who open the editor. The editor asks for it lazily instead, alongside
// Monaco itself. A deployment without the vars-sync sidecar has no such file — the API 404s,
// and the editor keeps its curated fallback list.
export const GET: RequestHandler = async ({ params, locals, fetch }) => {
	if (!locals.user) error(401, "Not signed in");
	if (!can(locals.user, "can_read")) error(403, "Reading requires the read capability.");

	const res = await apiRaw(`/sources/${encodeURIComponent(params.source)}/pyapi`, {
		token: locals.token,
		fetch,
	});
	if (!res.ok) error(res.status === 404 ? 404 : 502, "No Python API surface for this source");

	return new Response(res.body, {
		headers: {
			"content-type": "application/json",
			// Regenerated only when the sidecar runs; a few minutes of browser cache saves
			// re-sending a quarter of a megabyte every time the editor opens.
			"cache-control": "private, max-age=300",
		},
	});
};
