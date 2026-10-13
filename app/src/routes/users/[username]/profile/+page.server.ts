import type { Actions, PageServerLoad } from "./$types";
import { error, fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import { ALL_CAPABILITIES, type ApiKey, type Capability, type Profile, type UserUsage } from "$lib/types";

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

	// An admin manages the user's API keys from here (re-scope, revoke). Same degradation as usage.
	let apiKeys: ApiKey[] | null = null;
	if (can(locals.user, "can_admin")) {
		try {
			apiKeys = await api<ApiKey[]>(`/admin/users/${profile.id}/api-keys`, {
				token: locals.token,
				fetch,
			});
		} catch (err) {
			if (!(err instanceof ApiError)) throw err;
		}
	}

	// Viewing your own profile vs. an admin viewing someone else's — drives the heading copy.
	return { profile, usage, apiKeys, isSelf: profile.id === locals.user.id };
};

// Admin-only key management; the API enforces can_admin, these just relay its verdict.
async function keyRequest(
	locals: App.Locals,
	fetch: typeof globalThis.fetch,
	form: FormData,
	method: "PATCH" | "DELETE",
	body?: unknown,
) {
	if (!locals.user) redirect(303, "/login");
	const userId = Number(form.get("user_id"));
	const keyId = Number(form.get("key_id"));
	if (!userId || !keyId) return fail(400, { error: "Missing key." });
	try {
		await api(`/admin/users/${userId}/api-keys/${keyId}`, {
			method,
			token: locals.token,
			body,
			fetch,
		});
	} catch (err) {
		if (err instanceof ApiError) return fail(err.status, { error: err.message });
		throw err;
	}
	return { ok: true };
}

export const actions: Actions = {
	// `reset` hands the key back to the owner default; otherwise pin it to the ticked scopes.
	rescope: async ({ request, locals, fetch }) => {
		const form = await request.formData();
		const scopes =
			form.get("reset") === "1"
				? null
				: String(form.get("scopes") ?? "")
						.split(",")
						.map((s) => s.trim())
						.filter((s): s is Capability => (ALL_CAPABILITIES as string[]).includes(s));
		return keyRequest(locals, fetch, form, "PATCH", { scopes });
	},
	revoke: async ({ request, locals, fetch }) => {
		return keyRequest(locals, fetch, await request.formData(), "DELETE");
	},
};
