import type { Actions, PageServerLoad } from "./$types";
import { fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import type { Pointer } from "$lib/types";

export const load: PageServerLoad = async ({ locals }) => {
	// Authoring requires can_edit; bounce anonymous users to login, others to the browser.
	if (!locals.user) redirect(303, "/login?redirectTo=/concepts/new");
	if (!can(locals.user, "can_edit")) redirect(303, "/concepts");
};

/** Where a freshly named concept is now browsable, with the member pinned — the name may by
 *  then point at more than one concept. */
function conceptHref(taxonomy: string, name: string, id: number): string {
	return `/concepts/tax/${encodeURIComponent(taxonomy)}/${encodeURIComponent(name)}?cid=${id}`;
}

export const actions: Actions = {
	// Path 1: a name nothing yet stands behind — mint a concept and register the name for it.
	create: async ({ request, locals, fetch }) => {
		const form = await request.formData();
		const name = String(form.get("name") ?? "").trim();
		const display_name = String(form.get("display_name") ?? "").trim() || null;
		const description = String(form.get("description") ?? "").trim() || null;
		const taxonomy = String(form.get("taxonomy") ?? "corr_v1");
		const confirm_group = form.get("confirm_group") === "true";

		const values = { name, display_name, description, taxonomy };
		if (!name) return fail(400, { error: "A concept name is required.", values });

		let created: { id: number };
		try {
			created = await api<{ id: number; taxonomy: string; name: string }>("/concepts", {
				method: "POST",
				token: locals.token,
				body: { name, display_name, description, taxonomy, confirm_group },
				fetch,
			});
		} catch (err) {
			if (err instanceof ApiError) {
				// The name is already live for another concept. Legitimate (one identifier may
				// cover several substances) but never accidental, so it is confirmed, not retried.
				if (err.nameExists) return fail(409, { conflict: err.nameExists, values });
				return fail(err.status, { error: err.message, values });
			}
			throw err;
		}

		redirect(303, conceptHref(taxonomy, name, created.id));
	},

	// Path 2: the name belongs to a concept that already exists under another name (or in
	// another taxonomy) — add a pointer instead of a second concept meaning the same thing.
	addPointer: async ({ request, locals, fetch }) => {
		const form = await request.formData();
		const conceptId = Number(form.get("concept_id"));
		const name = String(form.get("name") ?? "").trim();
		const display_name = String(form.get("display_name") ?? "").trim() || null;
		const taxonomy = String(form.get("taxonomy") ?? "corr_v1");
		const confirm_group = form.get("confirm_group") === "true";

		const values = { name, display_name, taxonomy, concept_id: conceptId };
		if (!conceptId) return fail(400, { error: "Pick the concept this name belongs to.", values });
		if (!name) return fail(400, { error: "A name is required.", values });

		try {
			await api<Pointer>(`/concept/id/${conceptId}/pointers`, {
				method: "POST",
				token: locals.token,
				body: { taxonomy, identifier: name, display_name, confirm_group },
				fetch,
			});
		} catch (err) {
			if (err instanceof ApiError) {
				if (err.nameExists) return fail(409, { conflict: err.nameExists, values });
				// The other 409: this concept already holds the name. Nothing to confirm.
				return fail(err.status, { error: err.message, values });
			}
			throw err;
		}

		redirect(303, conceptHref(taxonomy, name, conceptId));
	},
};
