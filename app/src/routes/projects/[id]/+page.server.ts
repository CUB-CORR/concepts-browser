import type { Actions, PageServerLoad } from "./$types";
import { error, fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import type { License, Project, ProjectActivity, UsageConcept, UserOption } from "$lib/types";

export const load: PageServerLoad = async ({ params, locals, fetch }) => {
	if (!locals.user) redirect(303, `/login?redirectTo=/projects/${params.id}`);

	let project: Project;
	try {
		project = await api<Project>(`/projects/${params.id}`, { token: locals.token, fetch });
	} catch (err) {
		if (err instanceof ApiError && err.status === 404) error(404, "Project not found");
		throw err;
	}

	// Activity and the concepts read under this project always; the lead options only matter
	// when the user can edit the lead field.
	const [activity, usage] = await Promise.all([
		api<ProjectActivity>(`/projects/${params.id}/activity`, { token: locals.token, fetch }),
		api<UsageConcept[]>(`/projects/${params.id}/usage`, { token: locals.token, fetch }),
	]);
	const userOptions = project.can_edit
		? await api<UserOption[]>("/projects/user-options", { token: locals.token, fetch })
		: [];
	// The license text is only needed to drive a (re-)approval prompt.
	const license =
		project.can_edit && !project.license_ok
			? await api<License | null>("/projects/license", { token: locals.token, fetch })
			: null;

	return { project, activity, usage, userOptions, license };
};

/** Shared write helper: PATCH the project and surface API errors as form failures. */
async function patch(id: string, token: string | null, fetch: typeof globalThis.fetch, body: unknown) {
	try {
		await api(`/projects/${id}`, { method: "PATCH", token, body, fetch });
	} catch (err) {
		if (err instanceof ApiError) {
			return fail(err.status, { error: err.status === 409 ? "That project name is already taken." : err.message });
		}
		throw err;
	}
	return null;
}

export const actions: Actions = {
	update: async ({ request, params, locals, fetch }) => {
		const form = await request.formData();
		const name = String(form.get("name") ?? "").trim();
		const description = String(form.get("description") ?? "").trim() || null;
		const ea_id = String(form.get("ea_id") ?? "").trim() || null;
		const lead_ids = form.getAll("lead_ids").map((v) => Number(v)).filter((n) => Number.isFinite(n));
		if (!name) return fail(400, { error: "A project name is required." });
		if (lead_ids.length === 0) return fail(400, { error: "A project needs at least one lead." });
		return (await patch(params.id, locals.token, fetch, { name, description, ea_id, lead_ids })) ?? { ok: true };
	},

	// Edit the study context (the PICO frame and the study team). Same endpoint and the same
	// lead-or-admin gate as the rest of the project edits — only the form is separate, because
	// it renders as its own card. An emptied field is sent as null, which clears it.
	saveStudyContext: async ({ request, params, locals, fetch }) => {
		const form = await request.formData();
		const body: Record<string, string | null> = {};
		for (const [field, key] of [
			["pico_population", "population"],
			["pico_intervention", "intervention"],
			["pico_comparison", "comparison"],
			["pico_outcome", "outcome"],
			["study_team", "team"],
		] as const) {
			const raw = form.get(key);
			if (raw != null) body[field] = String(raw).trim() || null;
		}
		return (await patch(params.id, locals.token, fetch, body)) ?? { ok: true };
	},

	complete: async ({ request, params, locals, fetch }) => {
		const form = await request.formData();
		const completed = form.get("completed") === "true";
		return (await patch(params.id, locals.token, fetch, { completed })) ?? { ok: true };
	},

	approve: async ({ params, locals, fetch }) => {
		return (await patch(params.id, locals.token, fetch, { accept_license: true })) ?? { ok: true };
	},

	delete: async ({ params, locals, fetch }) => {
		try {
			await api(`/projects/${params.id}/delete`, { method: "POST", token: locals.token, fetch });
		} catch (err) {
			if (err instanceof ApiError) return fail(err.status, { error: err.message });
			throw err;
		}
		redirect(303, "/projects");
	},
};
