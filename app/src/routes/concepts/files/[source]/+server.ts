import type { RequestHandler } from "./$types";
import { error, json } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import type { SourceFileRecord } from "$lib/types";

// A source's file library, for the editor: the `getfile("…")` completions and the marker on a
// uuid that names no file. Fetched from the browser, like the pyapi surface next to it, rather
// than serialized into every concept page — only the few visitors who open the editor need it.
//
// A source with no files answers `[]`, which is a real answer (no completions, every uuid
// unknown); only a failed call falls back to offering nothing and flagging nothing.
export const GET: RequestHandler = async ({ params, locals, fetch }) => {
	if (!locals.user) error(401, "Not signed in");
	if (!can(locals.user, "can_read")) error(403, "Reading requires the read capability.");

	try {
		const files = await api<SourceFileRecord[]>(
			`/sources/${encodeURIComponent(params.source)}/files`,
			{ token: locals.token, fetch },
		);
		return json(files, { headers: { "cache-control": "private, max-age=30" } });
	} catch (err) {
		if (err instanceof ApiError) error(err.status === 404 ? 404 : 502, err.message);
		throw err;
	}
};
