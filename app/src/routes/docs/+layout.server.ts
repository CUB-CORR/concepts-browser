import type { LayoutServerLoad } from "./$types";
import { guardRead } from "$lib/server/files";
import { docsNav } from "$lib/server/docs";

// The guide describes the repository, so it is gated exactly like a concept-browsing page:
// anonymous visitors go to sign-in, not-yet-approved accounts to /pending, and everybody with
// `can_read` gets in. It is deliberately not public — it names internal routes and workflows.
//
// The sidebar lists only the chapters this reader may open (see $lib/server/docs).
export const load: LayoutServerLoad = async ({ locals, url }) => {
	guardRead(locals, url);
	return { docsNav: docsNav(locals.user) };
};
