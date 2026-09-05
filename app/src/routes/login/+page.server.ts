import type { Actions, PageServerLoad } from "./$types";
import { fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { setSession, clearSession } from "$lib/server/session";

function safeRedirect(target: string | null): string {
	// Only allow same-app relative paths as a post-login destination.
	return target && target.startsWith("/") && !target.startsWith("//") ? target : "/concepts";
}

export const load: PageServerLoad = async ({ locals, url }) => {
	if (locals.user) redirect(303, safeRedirect(url.searchParams.get("redirectTo")));
	return { redirectTo: url.searchParams.get("redirectTo") ?? "" };
};

export const actions: Actions = {
	// Login: exchange credentials for a JWT and store it in an httpOnly cookie. Named
	// (not default) because this file also exposes a `logout` action.
	login: async ({ request, cookies, fetch, url }) => {
		const form = await request.formData();
		const username = String(form.get("username") ?? "").trim();
		const password = String(form.get("password") ?? "");
		if (!username || !password) {
			return fail(400, { error: "Username and password are required.", username });
		}

		try {
			const { access_token, expires_at } = await api<{ access_token: string; expires_at: string }>(
				"/auth/login",
				{ method: "POST", body: { username, password }, fetch },
			);
			setSession(cookies, access_token, expires_at);
		} catch (err) {
			if (err instanceof ApiError && err.status === 401) {
				return fail(401, { error: "Invalid username or password.", username });
			}
			if (err instanceof ApiError && err.status === 403) {
				return fail(403, { error: "This account is disabled.", username });
			}
			return fail(502, { error: "Could not reach the authentication service.", username });
		}

		redirect(303, safeRedirect(form.get("redirectTo") as string | null ?? url.searchParams.get("redirectTo")));
	},

	logout: async ({ cookies }) => {
		clearSession(cookies);
		redirect(303, "/concepts");
	},
};
