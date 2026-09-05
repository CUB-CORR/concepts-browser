import type { Actions, PageServerLoad } from "./$types";
import { fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { can } from "$lib/caps";
import {
	ALL_CAPABILITIES,
	type AdminUser,
	type Capability,
	type DirectoryEntry,
} from "$lib/types";

// Parse a comma-separated capabilities field (mirrors the row toggles) into known caps.
function parseCapabilities(raw: string): Capability[] {
	return raw
		.split(",")
		.map((c) => c.trim())
		.filter(Boolean)
		.filter((c): c is Capability => (ALL_CAPABILITIES as string[]).includes(c));
}

// Admin-only. Anonymous → login; authenticated non-admins → concepts.
function guard(locals: App.Locals): void {
	if (!locals.user) redirect(303, "/login?redirectTo=/users");
	if (!can(locals.user, "can_admin")) redirect(303, "/concepts");
}

export const load: PageServerLoad = async ({ locals, fetch }) => {
	guard(locals);
	const users = await api<AdminUser[]>("/admin/users", { token: locals.token, fetch });
	return { users };
};

export const actions: Actions = {
	// Update one user's capabilities and/or active flag from the table row.
	update: async ({ request, locals, fetch }) => {
		guard(locals);
		const form = await request.formData();
		const userId = Number(form.get("user_id"));
		if (!userId) return fail(400, { error: "Missing user." });

		// Capabilities arrive as a comma-separated hidden field mirroring the row's toggles.
		const capabilities = parseCapabilities(String(form.get("capabilities") ?? ""));
		const is_active = form.get("is_active") === "true";

		try {
			await api(`/admin/users/${userId}`, {
				method: "PATCH",
				token: locals.token,
				body: { capabilities, is_active },
				fetch,
			});
		} catch (err) {
			if (err instanceof ApiError) return fail(err.status, { error: err.message, userId });
			throw err;
		}
		return { ok: true, userId };
	},

	// Search the LDAP directory (by uid or common name) to find someone to add proactively.
	search: async ({ request, locals, fetch }) => {
		guard(locals);
		const q = String((await request.formData()).get("q") ?? "").trim();
		if (!q) return { results: [] as DirectoryEntry[], q };
		try {
			const results = await api<DirectoryEntry[]>("/admin/directory", {
				token: locals.token,
				query: { q },
				fetch,
			});
			return { results, q };
		} catch (err) {
			if (err instanceof ApiError) return fail(err.status, { error: err.message, q });
			throw err;
		}
	},

	// Proactively add a directory user (by uid) with capabilities, before their first login.
	provision: async ({ request, locals, fetch }) => {
		guard(locals);
		const form = await request.formData();
		const username = String(form.get("username") ?? "").trim();
		if (!username) return fail(400, { error: "Missing username." });
		const capabilities = parseCapabilities(String(form.get("capabilities") ?? ""));

		try {
			await api("/admin/users", {
				method: "POST",
				token: locals.token,
				body: { username, capabilities },
				fetch,
			});
		} catch (err) {
			if (err instanceof ApiError) return fail(err.status, { error: err.message, username });
			throw err;
		}
		return { added: username };
	},
};
