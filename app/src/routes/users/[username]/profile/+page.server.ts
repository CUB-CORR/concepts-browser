import type { PageServerLoad } from "./$types";
import { error, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import type { Profile, UserUsage } from "$lib/types";

export const load: PageServerLoad = async ({ params, locals, fetch }) => {
	if (!locals.user) {
		redirect(303, `/login?redirectTo=/users/${params.username}/profile`);
	}

	let profile: Profile;
	try {
		profile = await api<Profile>(`/auth/users/${encodeURIComponent(params.username)}/profile`, {
			token: locals.token,
			fetch,
		});
	} catch (err) {
		if (err instanceof ApiError && err.status === 404) error(404, "User not found");
		if (err instanceof ApiError && err.status === 403) {
			error(403, "You are not allowed to view this profile.");
		}
		throw err;
	}

	// What this user has done with the API, from the audit-log rollup. The endpoint enforces the
	// same rule as the profile itself (self, or an admin), so a viewer who got this far is
	// allowed it — but a failure here must not cost them the page, so it degrades to null.
	let usage: UserUsage | null = null;
	try {
		usage = await api<UserUsage>(`/usage/users/${profile.id}`, { token: locals.token, fetch });
	} catch (err) {
		if (!(err instanceof ApiError)) throw err;
	}

	// Viewing your own profile vs. an admin viewing someone else's — drives the heading copy.
	return { profile, usage, isSelf: profile.id === locals.user.id };
};
