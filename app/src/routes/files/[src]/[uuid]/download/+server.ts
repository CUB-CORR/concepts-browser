import type { RequestHandler } from "./$types";
import { error } from "@sveltejs/kit";
import { apiRaw } from "$lib/server/api";
import { can } from "$lib/caps";

// Streams one source file through the BFF — the browser cannot call the API itself, the bearer
// token is server-side only. `?version=n` serves exactly that version's bytes, which is what a
// concept page's download link pins to; without it the API serves the current ones.
export const GET: RequestHandler = async ({ params, url, locals, fetch }) => {
	if (!locals.user) error(401, "Not signed in");
	// File *contents*, not metadata: `can_read_detail`, matching the API route this proxies.
	// Refused here rather than proxied, so the browser gets our message instead of a bare 502.
	if (!can(locals.user, "can_read_detail"))
		error(403, "Downloading file contents requires read-detail access.");

	const res = await apiRaw(
		`/sources/${encodeURIComponent(params.src)}/files/${encodeURIComponent(params.uuid)}/download`,
		{ token: locals.token, fetch, query: { version: url.searchParams.get("version") } },
	);
	if (!res.ok) error(res.status === 404 ? 404 : 502, "Could not download that file");

	return new Response(res.body, {
		headers: {
			"content-type": res.headers.get("content-type") ?? "application/octet-stream",
			"content-disposition": res.headers.get("content-disposition") ?? "attachment",
		},
	});
};
