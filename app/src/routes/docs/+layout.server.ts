import type { LayoutServerLoad } from "./$types";
import { guardRead } from "$lib/server/files";

// The guide describes the repository, so it is gated exactly like a concept-browsing page:
// anonymous visitors go to sign-in, not-yet-approved accounts to /pending, and everybody with
// `can_read` gets in. It is deliberately not public — it names internal routes and workflows.
//
// `brand` and the capability helpers are client-safe, so the pages need no other server data;
// the signed-in user comes from the root layout.
export const load: LayoutServerLoad = async ({ locals, url }) => {
	guardRead(locals, url);
	return {};
};
