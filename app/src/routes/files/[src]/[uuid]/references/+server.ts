import type { RequestHandler } from "./$types";
import { error, json } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import type { FileReference } from "$lib/types";

// Which concepts read this file, asked for from the browser rather than in a `load`: the upload
// dialog needs it for a path the user has only just typed, and the library page is not about
// any one file. The file's own page gets the same list server-side.
export const GET: RequestHandler = async ({ params, locals, fetch }) => {
	if (!locals.user) error(401, "Not signed in");
	if (!can(locals.user, "can_read")) error(403, "Reading files requires the read capability.");

	try {
		const refs = await api<FileReference[]>(
			`/sources/${encodeURIComponent(params.src)}/files/${encodeURIComponent(params.uuid)}/references`,
			{ token: locals.token, fetch },
		);
		return json(refs);
	} catch (err) {
		if (err instanceof ApiError) error(err.status === 404 ? 404 : 502, err.message);
		throw err;
	}
};
