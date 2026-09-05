import type { Actions, PageServerLoad } from "./$types";
import { error } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import { deleteFile, guardRead, uploadFile } from "$lib/server/files";
import type { Source, SourceFileRecord } from "$lib/types";

// One source's file library: every data file its definitions read, at its current version.
//
// This is where files live now — not on a concept version. A config only pins (uuid, version),
// so replacing a file here is what publishes new concept versions, and `referenced_by` is the
// count that says how many.
export const load: PageServerLoad = async ({ params, url, locals, fetch }) => {
	guardRead(locals, url);
	const src = params.src;

	try {
		const [files, sources] = await Promise.all([
			api<SourceFileRecord[]>(`/sources/${encodeURIComponent(src)}/files`, {
				token: locals.token,
				fetch,
			}),
			api<Source[]>("/sources", { token: locals.token, fetch }),
		]);
		return {
			src,
			files,
			source: sources.find((s) => s.key === src) ?? null,
			canPublish: can(locals.user, "can_publish"),
			// Metadata is `can_read`; the bytes are `can_read_detail`. The page lists either way
			// and drops the download control rather than offering one that 403s.
			canDownload: can(locals.user, "can_read_detail"),
		};
	} catch (err) {
		if (err instanceof ApiError) error(err.status === 404 ? 404 : 502, err.message);
		throw err;
	}
};

export const actions: Actions = {
	// Add a file, or replace one at a path that already exists. Identical bytes come back
	// `unchanged` and mint nothing — the page says so rather than claiming a version.
	upload: async ({ params, request, locals, fetch }) =>
		uploadFile(params.src, await request.formData(), locals, fetch),

	// Retire a file. Refused while any published config still reads it; the page then names
	// the concepts rather than just reporting a conflict.
	delete: async ({ params, request, locals, fetch }) => {
		const form = await request.formData();
		return deleteFile(params.src, String(form.get("uuid") ?? ""), locals, fetch);
	},
};
