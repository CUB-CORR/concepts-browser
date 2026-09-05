import type { RequestHandler } from "./$types";
import { error } from "@sveltejs/kit";
import { apiRaw } from "$lib/server/api";
import { apiDate } from "$lib/server/prefs";
import { can } from "$lib/caps";

// Streams the admin concepts export (CSV/XLSX) through the BFF. A POST because the client
// sends the concept ids of its filtered list; the file comes back as a download.
export const POST: RequestHandler = async ({ request, locals, fetch }) => {
	if (!locals.user) error(401, "Not signed in");
	if (!can(locals.user, "can_admin")) error(403, "Admin only");

	const body = await request.json();
	// The client sends the date lens as the page's YYYY-MM-DD pref; the API expects the same
	// inclusive end-of-day timestamp the list reads use.
	const res = await apiRaw("/concepts/export", {
		method: "POST",
		token: locals.token,
		body: { ...body, date: body.date ? apiDate(body.date) : undefined },
		fetch,
	});
	if (!res.ok) error(res.status, "Export failed");

	return new Response(res.body, {
		headers: {
			"content-type": res.headers.get("content-type") ?? "application/octet-stream",
			"content-disposition": res.headers.get("content-disposition") ?? "attachment",
		},
	});
};
