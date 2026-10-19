import type { PageServerLoad } from "./$types";
import { docsIndex } from "$lib/server/docs";

// The landing page: `index.md`'s intro above the chapter cards, its sections below them.
export const load: PageServerLoad = async () => {
	return { index: docsIndex() };
};
