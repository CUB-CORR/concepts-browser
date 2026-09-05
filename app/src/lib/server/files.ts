// The two file-library pages (`/files/[src]` and `/files/[src]/[uuid]`) offer the same two
// writes — upload a version, retire a file — so they share the implementations here rather
// than each keeping their own copy of the multipart assembly and the 409 handling.
import { fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import type { FileReference, FileUploadResult } from "$lib/types";

/** Reading a source's files is a plain read; the pages bounce like every other read page. */
export function guardRead(locals: App.Locals, url: URL): void {
	if (!locals.user) redirect(303, `/login?redirectTo=${encodeURIComponent(url.pathname)}`);
	if (!can(locals.user, "can_read")) redirect(303, "/pending");
}

/** `POST /sources/{key}/files` — a new file, or a new version of an existing one.
 *
 *  Gated on `can_publish`, not `can_edit`: an upload cascades into every concept whose current
 *  config references the file and publishes a version of each, which is publishing by another
 *  route. The API enforces it authoritatively; the check here only produces a better message. */
export async function uploadFile(
	src: string,
	form: FormData,
	locals: App.Locals,
	fetch: typeof globalThis.fetch,
) {
	if (!can(locals.user, "can_publish"))
		return fail(403, { error: "Uploading a file version requires the publish capability." });

	const file = form.get("file");
	const path = String(form.get("path") ?? "").trim();
	const message = String(form.get("message") ?? "").trim();
	// Set by the file page's replace control: put the bytes on *this* file whatever it is
	// currently called, which is what lets the new version carry a different name.
	const uuid = String(form.get("uuid") ?? "").trim();
	if (!(file instanceof File) || !file.size) return fail(400, { error: "Choose a file to upload." });
	if (!path) return fail(400, { error: "Give the file the path it is known by in this source." });

	const body = new FormData();
	body.set("path", path);
	body.set("file", file, file.name);
	if (message) body.set("message", message);
	if (uuid) body.set("uuid", uuid);

	try {
		const result = await api<FileUploadResult>(`/sources/${encodeURIComponent(src)}/files`, {
			method: "POST",
			token: locals.token,
			body,
			fetch,
		});
		// `result.path` is the file's path *after* the upload, which is the authority on a
		// rename — not the path that was sent.
		return { uploaded: result };
	} catch (err) {
		// A rename onto a path another file holds comes back as a structured 409 whose
		// `message` names the file in the way — worth showing instead of the error code.
		if (err instanceof ApiError)
			return fail(err.status || 502, { error: detailMessage(err) ?? err.message });
		throw err;
	}
}

/** The human sentence a structured error body carries, when it carries one. */
function detailMessage(err: ApiError): string | null {
	const detail = (err.body as { detail?: unknown })?.detail;
	const message = (detail as { message?: unknown })?.message;
	return typeof message === "string" ? message : null;
}

/** `DELETE /sources/{key}/files/{uuid}` — a soft delete, refused with 409 and the referencing
 *  concepts while any published config still reads the file. Those come back to the page so it
 *  can name them instead of just reporting a conflict. */
export async function deleteFile(
	src: string,
	uuid: string,
	locals: App.Locals,
	fetch: typeof globalThis.fetch,
) {
	if (!can(locals.user, "can_publish"))
		return fail(403, { error: "Retiring a file requires the publish capability." });

	try {
		await api(`/sources/${encodeURIComponent(src)}/files/${encodeURIComponent(uuid)}`, {
			method: "DELETE",
			token: locals.token,
			fetch,
		});
	} catch (err) {
		if (err instanceof ApiError)
			return fail(err.status || 502, { error: err.message, references: referencesOf(err) });
		throw err;
	}
	return { deleted: uuid };
}

/** The concept list a 409 carries, when it carries one. */
function referencesOf(err: ApiError): FileReference[] | null {
	const detail = (err.body as { detail?: unknown })?.detail;
	const list = (detail as { references?: unknown })?.references;
	return Array.isArray(list) ? (list as FileReference[]) : null;
}
