import type { Actions, PageServerLoad } from "./$types";
import { fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import { ALL_CAPABILITIES, type ApiKey, type ApiKeyCreated, type Capability } from "$lib/types";

// Gated by create_api_key. Anonymous → login; users without the capability → concepts.
function guard(locals: App.Locals): void {
	if (!locals.user) redirect(303, "/login?redirectTo=/api-keys");
	if (!can(locals.user, "create_api_key")) redirect(303, "/concepts");
}

export const load: PageServerLoad = async ({ locals, fetch }) => {
	guard(locals);
	const keys = await api<ApiKey[]>("/api-keys", { token: locals.token, fetch });
	// Only admins choose scopes; everyone else gets read-only keys. `create_api_key` is never a
	// scope (a key must not mint more keys), so it's excluded from the choices.
	const isAdmin = can(locals.user, "can_admin");
	const grantableScopes = isAdmin
		? ALL_CAPABILITIES.filter((c) => c !== "create_api_key")
		: [];
	return { keys, grantableScopes, isAdmin };
};

export const actions: Actions = {
	// Mint a key; the plaintext comes back once and is surfaced to the page.
	create: async ({ request, locals, fetch }) => {
		guard(locals);
		const form = await request.formData();
		const name = String(form.get("name") ?? "").trim();
		if (!name) return fail(400, { error: "Give the key a name." });

		const scopes = String(form.get("scopes") ?? "")
			.split(",")
			.map((s) => s.trim())
			.filter(Boolean)
			.filter((s): s is Capability => (ALL_CAPABILITIES as string[]).includes(s));

		const daysRaw = String(form.get("expires_in_days") ?? "").trim();
		const expires_in_days = daysRaw ? Number(daysRaw) : null;

		try {
			const created = await api<ApiKeyCreated>("/api-keys", {
				method: "POST",
				token: locals.token,
				body: { name, scopes, expires_in_days },
				fetch,
			});
			// Return the secret so the page can show it once; it is never fetchable again.
			return { created };
		} catch (err) {
			if (err instanceof ApiError) return fail(err.status, { error: err.message });
			throw err;
		}
	},

	// Revoke a key. Immediate: the next request with it is rejected.
	revoke: async ({ request, locals, fetch }) => {
		guard(locals);
		const keyId = Number((await request.formData()).get("key_id"));
		if (!keyId) return fail(400, { error: "Missing key." });
		try {
			await api(`/api-keys/${keyId}`, { method: "DELETE", token: locals.token, fetch });
		} catch (err) {
			if (err instanceof ApiError) return fail(err.status, { error: err.message });
			throw err;
		}
		return { revoked: keyId };
	},
};
