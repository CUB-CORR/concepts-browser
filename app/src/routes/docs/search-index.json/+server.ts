import type { RequestHandler } from "./$types";
import { error, json } from "@sveltejs/kit";
import { can } from "$lib/caps";
import { docsSearchEntries } from "$lib/server/docs";

// The guide's search index for the reader asking: one entry per section of every chapter they
// may open, so a gated chapter never reaches their browser as a hit. Scored client-side, see
// $lib/docs/search.
export const GET: RequestHandler = async ({ locals }) => {
	if (!can(locals.user, "can_read")) error(403, "Not allowed to read the user guide");
	return json(docsSearchEntries(locals.user));
};
