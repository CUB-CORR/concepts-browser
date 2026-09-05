import type { Actions, PageServerLoad } from "./$types";
import { error, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import { deleteFile, guardRead, uploadFile } from "$lib/server/files";
import type { FileReference, SourceFileDetail } from "$lib/types";

// One file: what it is, every version it has had, and — the part that matters before touching
// it — which concepts read it right now. That list is what a replace publishes.
export const load: PageServerLoad = async ({ params, url, locals, fetch }) => {
	guardRead(locals, url);
	const { src, uuid } = params;
	const base = `/sources/${encodeURIComponent(src)}/files/${encodeURIComponent(uuid)}`;

	try {
		const [file, references] = await Promise.all([
			api<SourceFileDetail>(base, { token: locals.token, fetch }),
			api<FileReference[]>(`${base}/references`, { token: locals.token, fetch }),
		]);
		return {
			src,
			file,
			references,
			canPublish: can(locals.user, "can_publish"),
			// The bytes need `can_read_detail`; this page's metadata and history do not.
			canDownload: can(locals.user, "can_read_detail"),
		};
	} catch (err) {
		if (err instanceof ApiError) error(err.status === 404 ? 404 : 502, err.message);
		throw err;
	}
};

export const actions: Actions = {
	// A new version of this file. The dialog sends the file's uuid along, so the upload lands on
	// this file and cannot create a second one — which also means the path it sends may be a new
	// one: a new version is allowed to rename the file.
	upload: async ({ params, request, locals, fetch }) =>
		uploadFile(params.src, await request.formData(), locals, fetch),

	// Retire the file. Refused while any published config still reads it, in which case the
	// page keeps rendering and names them.
	delete: async ({ params, locals, fetch }) => {
		const result = await deleteFile(params.src, params.uuid, locals, fetch);
		if ("status" in result) return result;
		redirect(303, `/files/${encodeURIComponent(params.src)}`);
	},
};
