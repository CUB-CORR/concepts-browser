import type { PageServerLoad } from "./$types";
import { api } from "$lib/server/api";
import { guardRead } from "$lib/server/files";
import type { Source } from "$lib/types";

// The way in to the file libraries: one per source. A file belongs to a source, so there is no
// such thing as "all files" — picking the source is the first step, not a filter.
export const load: PageServerLoad = async ({ url, locals, fetch }) => {
	guardRead(locals, url);
	const sources = await api<Source[]>("/sources", { token: locals.token, fetch });
	return { sources };
};
