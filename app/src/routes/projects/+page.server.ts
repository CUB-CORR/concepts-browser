import type { PageServerLoad } from "./$types";
import { redirect } from "@sveltejs/kit";
import { api } from "$lib/server/api";
import type { Project } from "$lib/types";

// The project list is only for signed-in users; anonymous visitors are bounced to login.
export const load: PageServerLoad = async ({ locals, fetch }) => {
	if (!locals.user) redirect(303, "/login?redirectTo=/projects");
	const projects = await api<Project[]>("/projects", { token: locals.token, fetch });
	return { projects };
};
