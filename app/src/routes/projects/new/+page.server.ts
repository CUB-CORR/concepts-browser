import type { Actions, PageServerLoad } from "./$types";
import { fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import type { License, UserOption } from "$lib/types";

export const load: PageServerLoad = async ({ locals, fetch }) => {
	// Creating a project requires the add_project capability.
	if (!locals.user) redirect(303, "/login?redirectTo=/projects/new");
	if (!can(locals.user, "add_project")) redirect(303, "/projects");

	const [userOptions, license] = await Promise.all([
		api<UserOption[]>("/projects/user-options", { token: locals.token, fetch }),
		api<License | null>("/projects/license", { token: locals.token, fetch }),
	]);
	return { userOptions, license };
};

export const actions: Actions = {
	default: async ({ request, locals, fetch }) => {
		const form = await request.formData();
		const name = String(form.get("name") ?? "").trim();
		const description = String(form.get("description") ?? "").trim() || null;
		const ea_id = String(form.get("ea_id") ?? "").trim() || null;
		const accept_license = form.get("accept_license") === "on";
		// The lead multi-select posts one `lead_ids` entry per selected user.
		const lead_ids = form.getAll("lead_ids").map((v) => Number(v)).filter((n) => Number.isFinite(n));

		const values = { name, description, ea_id, lead_ids, accept_license };
		if (!name) return fail(400, { error: "A project name is required.", values });
		if (!accept_license) {
			return fail(400, { error: "You must accept the CORR license to create a project.", values });
		}

		let created: { id: string };
		try {
			created = await api<{ id: string }>("/projects", {
				method: "POST",
				token: locals.token,
				body: { name, description, ea_id, lead_ids, accept_license },
				fetch,
			});
		} catch (err) {
			if (err instanceof ApiError) {
				if (err.status === 409) return fail(409, { error: `A project named "${name}" already exists.`, values });
				return fail(err.status, { error: err.message, values });
			}
			throw err;
		}

		redirect(303, `/projects/${created.id}`);
	},
};
