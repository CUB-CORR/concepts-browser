import type { PageServerLoad } from "./$types";
import { error, redirect } from "@sveltejs/kit";
import { docsChapter } from "$lib/server/docs";

// One chapter of the guide. A hidden or unknown slug is a 404. An admin-only chapter is already
// missing from the sidebar, the landing cards, the prev/next footer and the search index for
// everyone else, and this is what makes typing its URL no different: anonymous visitors go to
// sign-in, a signed-in non-admin back to the guide rather than out of it.
export const load: PageServerLoad = async ({ params, locals }) => {
	const chapter = docsChapter(params.slug, locals.user);
	if (chapter === "missing") error(404, "No such chapter in the user guide");
	if (chapter === "forbidden") {
		if (!locals.user) redirect(303, `/login?redirectTo=/docs/${params.slug}`);
		redirect(303, "/docs");
	}
	return { chapter };
};
