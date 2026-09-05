import type { Actions, PageServerLoad } from "./$types";
import { error, fail, redirect } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { apiDate } from "$lib/server/prefs";
import { can } from "$lib/caps";
import type { ConceptDetail, Draft, HistoryRow, Pointer, SchemaIndex } from "$lib/types";

// The single concept page: detail + history + (for authoring) leaf schemas and open drafts.
//
// A name is allowed to point at several concepts, so the name route hands back a list and the
// page is about one member of it — `?cid=` pins which, defaulting to the first. Everything
// below the resolution step is addressed by that member's **id**: a group would make a second
// name lookup ambiguous, and the pinned member is precisely what must not be re-guessed.
export const load: PageServerLoad = async ({ params, url, parent, locals, fetch }) => {
	// Reading a concept requires an authenticated user with can_read (same gate as the list).
	if (!locals.user) redirect(303, `/login?redirectTo=${encodeURIComponent(url.pathname)}`);
	if (!can(locals.user, "can_read")) redirect(303, "/pending");

	const { date } = await parent();
	const { taxonomy, name } = params;

	// The detail route accepts at most one of {v, draft, date}; pick by precedence so an
	// explicit version/draft selection wins over the ambient global date filter (avoids the
	// API's 400).
	const v = url.searchParams.get("v");
	const draft = url.searchParams.get("draft");
	const selector: Record<string, string | undefined> = v
		? { v }
		: draft
			? { draft }
			: { date: apiDate(date) };

	const token = locals.token;
	try {
		// Resolution is always as-of the date lens only: `?v=`/`?draft=` address one concept's
		// history and are refused on a name that resolves to a group, so the pinned member is
		// re-read by id below when one of them is set.
		const members = await api<ConceptDetail[]>(
			`/concept/${encodeURIComponent(taxonomy)}/${encodeURIComponent(name)}`,
			{ token, query: { date: apiDate(date) }, fetch },
		);
		if (members.length === 0) error(404, `Concept '${name}' not found in taxonomy '${taxonomy}'`);

		const asked = Number(url.searchParams.get("cid"));
		const pinned = members.find((m) => m.id === asked) ?? members[0];
		const base = `/concept/id/${pinned.id}`;

		const [concept, history, drafts, schemas] = await Promise.all([
			v || draft ? api<ConceptDetail>(base, { token, query: selector, fetch }) : pinned,
			api<HistoryRow[]>(`${base}/history`, { token, fetch }),
			api<Draft[]>(`${base}/drafts`, { token, fetch }),
			api<SchemaIndex>("/schemas", { token, fetch }),
		]);
		return {
			concept,
			// The id route names the concept by whichever pointer it presents it under, which
			// need not be the one the page was reached by — keep the page's own.
			pointer: pinned.pointer,
			members,
			history,
			drafts,
			schemas,
			selected: { v: v ? Number(v) : null, draft: draft ? Number(draft) : null },
			activeSource: url.searchParams.get("source"),
		};
	} catch (err) {
		if (err instanceof ApiError) error(err.status === 404 ? 404 : 502, err.message);
		throw err;
	}
};

function parseJson(raw: FormDataEntryValue | null): { ok: true; value: unknown } | { ok: false } {
	if (raw == null) return { ok: true, value: undefined };
	try {
		return { ok: true, value: JSON.parse(String(raw)) };
	} catch {
		return { ok: false };
	}
}

/** Map an ApiError to a typed action failure, surfacing schema-validation errors inline. */
function failFromApi(err: unknown) {
	if (err instanceof ApiError) {
		return fail(err.status === 401 || err.status === 403 ? 403 : err.status || 502, {
			error: err.message,
			validationErrors: err.validationErrors,
		});
	}
	throw err;
}

/** The concept every write on this page addresses: the pinned member, sent as a hidden `cid`
 *  field (a form action's URL keeps no query string of its own). */
function conceptBase(form: FormData): string {
	const cid = Number(form.get("cid"));
	if (!cid) error(400, "The form did not say which concept it is about.");
	return `/concept/id/${cid}`;
}

export const actions: Actions = {
	// Edit the concept's clinical documentation in place. The API enforces the capability
	// split authoritatively (texts: can_edit, status: can_publish); the check here only
	// produces a friendlier error. Fields not present in the form are left unchanged.
	saveDocumentation: async ({ request, locals, fetch }) => {
		const form = await request.formData();
		const body: Record<string, string | null> = {};
		for (const [field, key] of [
			["doc_clinical", "clinical"],
			["doc_implementation", "implementation"],
			["doc_caveats", "caveats"],
			["doc_status", "status"],
		] as const) {
			const raw = form.get(key);
			if (raw != null) body[field] = String(raw).trim() || null;
		}
		const textEdit = Object.keys(body).some((f) => f !== "doc_status");
		if (textEdit && !can(locals.user, "can_edit"))
			return fail(403, { error: "Editing documentation requires the edit capability." });
		if ("doc_status" in body && !can(locals.user, "can_publish"))
			return fail(403, { error: "Changing the status requires the publish capability." });

		try {
			await api(`${conceptBase(form)}/documentation`, {
				method: "PATCH",
				token: locals.token,
				body,
				fetch,
			});
		} catch (err) {
			return failFromApi(err);
		}
		return { success: true };
	},

	// Create a draft for a source. Seed is decided client-side: `empty=true` with a fresh
	// {type, json} for an unconfigured source (or a type change), else copy from the latest
	// published version of this (concept, source).
	createDraft: async ({ request, locals, fetch }) => {
		if (!can(locals.user, "can_edit")) return fail(403, { error: "Editing requires sign-in." });
		const form = await request.formData();
		const source = String(form.get("source") ?? "");
		const empty = form.get("empty") === "true";
		const type = (form.get("type") as string) || undefined;
		const json = parseJson(form.get("json"));
		const py = form.get("py") != null ? String(form.get("py")) : undefined;
		if (!json.ok) return fail(400, { error: "Config JSON is not valid JSON." });

		let draft: Draft;
		try {
			draft = await api<Draft>(`${conceptBase(form)}/drafts`, {
				method: "POST",
				token: locals.token,
				body: {
					source,
					empty,
					type,
					json: json.value,
					py,
					message: (form.get("message") as string) || null,
					change_type: (form.get("change_type") as string) || "improvement",
				},
				fetch,
			});
		} catch (err) {
			return failFromApi(err);
		}
		redirect(303, keepPin(form, `source=${encodeURIComponent(source)}&draft=${draft.id}`));
	},

	// Save edits to an open draft.
	saveDraft: async ({ request, locals, fetch }) => {
		if (!can(locals.user, "can_edit")) return fail(403, { error: "Editing requires sign-in." });
		const form = await request.formData();
		const draftId = String(form.get("draftId") ?? "");
		const json = parseJson(form.get("json"));
		const py = form.get("py") != null ? String(form.get("py")) : undefined;
		if (!json.ok) return fail(400, { error: "Config JSON is not valid JSON." });

		try {
			await api(`${conceptBase(form)}/drafts/${draftId}`, {
				method: "PUT",
				token: locals.token,
				body: {
					json: json.value,
					py,
					message: (form.get("message") as string) || null,
					change_type: (form.get("change_type") as string) || undefined,
				},
				fetch,
			});
		} catch (err) {
			return failFromApi(err);
		}
		return { saved: true };
	},

	// Publish an open draft → assigns the next version and makes it active.
	publishDraft: async ({ request, locals, fetch }) => {
		if (!can(locals.user, "can_publish"))
			return fail(403, { error: "Publishing requires the can_publish capability." });
		const form = await request.formData();
		const draftId = String(form.get("draftId") ?? "");
		const source = String(form.get("source") ?? "");

		try {
			await api(`${conceptBase(form)}/drafts/${draftId}/publish`, {
				method: "POST",
				token: locals.token,
				body: {
					message: (form.get("message") as string) || null,
					change_type: (form.get("change_type") as string) || null,
					notify: form.get("notify") === "true",
				},
				fetch,
			});
		} catch (err) {
			return failFromApi(err);
		}
		redirect(303, keepPin(form, source ? `source=${encodeURIComponent(source)}` : ""));
	},

	// Rename: point the new identifier at the concept, then retire the old pointer — in that
	// order, so the concept is never nameless in between and the orphan guard never fires.
	// A name already taken by *another* concept comes back as a `name_exists` 409, which the
	// dialog turns into "this name exists — create a group?" and re-sends confirmed.
	rename: async ({ request, params, locals, fetch }) => {
		if (!can(locals.user, "can_edit"))
			return fail(403, { error: "Renaming requires the edit capability." });
		const form = await request.formData();
		const base = conceptBase(form);
		const taxonomy = String(form.get("taxonomy") || params.taxonomy);
		const identifier = String(form.get("identifier") ?? "").trim();
		const displayName = String(form.get("display_name") ?? "").trim() || null;
		const pointerId = Number(form.get("pointerId"));
		const confirmGroup = form.get("confirm_group") === "true";
		if (!identifier) return fail(400, { error: "The new name cannot be empty." });
		if (!pointerId) return fail(400, { error: "The form did not say which name to retire." });

		try {
			await api<Pointer>(`${base}/pointers`, {
				method: "POST",
				token: locals.token,
				body: {
					taxonomy,
					identifier,
					display_name: displayName,
					confirm_group: confirmGroup,
				},
				fetch,
			});
		} catch (err) {
			if (err instanceof ApiError && err.nameExists)
				return fail(409, { conflict: err.nameExists, values: { identifier, displayName } });
			return failFromApi(err);
		}

		try {
			await api<Pointer>(`${base}/pointers/${pointerId}/deprecate`, {
				method: "POST",
				token: locals.token,
				fetch,
			});
		} catch (err) {
			// The new name is live either way; say so rather than pretend the rename failed.
			if (err instanceof ApiError)
				return fail(err.status || 502, {
					error: `'${identifier}' now names this concept, but the old name could not be retired: ${err.message}`,
				});
			throw err;
		}

		const cid = form.get("cid");
		redirect(
			303,
			`/concepts/tax/${encodeURIComponent(taxonomy)}/${encodeURIComponent(identifier)}?cid=${cid}`,
		);
	},

	// Name this concept in a taxonomy it has no name in yet, then follow it there. Same single
	// write as a rename's first half — a pointer is registered, nothing is edited in place — but
	// with no old name to retire: the concept simply gains a second vocabulary. Hand-typed names
	// are `origin=user` server-side, which the reference import leaves alone.
	addName: async ({ request, url, locals, fetch }) => {
		if (!can(locals.user, "can_edit"))
			return fail(403, { error: "Naming a concept requires the edit capability." });
		const form = await request.formData();
		const base = conceptBase(form);
		const taxonomy = String(form.get("taxonomy") ?? "").trim();
		const identifier = String(form.get("identifier") ?? "").trim();
		const displayName = String(form.get("display_name") ?? "").trim() || null;
		const confirmGroup = form.get("confirm_group") === "true";
		if (!taxonomy) return fail(400, { error: "The form did not say which taxonomy to name it in." });
		if (!identifier) return fail(400, { error: "The name cannot be empty." });

		try {
			await api<Pointer>(`${base}/pointers`, {
				method: "POST",
				token: locals.token,
				body: {
					taxonomy,
					identifier,
					display_name: displayName,
					confirm_group: confirmGroup,
				},
				fetch,
			});
		} catch (err) {
			// An identifier already live for another concept is a group — confirmable, so it
			// comes back to the dialog rather than reading as a failure.
			if (err instanceof ApiError && err.nameExists)
				return fail(409, { conflict: err.nameExists, values: { identifier, displayName } });
			return failFromApi(err);
		}

		// `?taxonomy=` is what makes the switch stick (the cookie is written from it), `?cid=`
		// keeps the reader on this concept should the new name turn out to name a group too.
		const query = new URLSearchParams({ taxonomy, cid: String(form.get("cid")) });
		const date = url.searchParams.get("date");
		if (date) query.set("date", date);
		redirect(
			303,
			`/concepts/tax/${encodeURIComponent(taxonomy)}/${encodeURIComponent(identifier)}?${query}`,
		);
	},

	// File a request to retire this concept. Editors ask; a reviewer (can_publish) decides on
	// /review — nothing here changes the concept.
	requestDeprecation: async ({ request, locals, fetch }) => {
		if (!can(locals.user, "can_edit"))
			return fail(403, { error: "Requesting deprecation requires the edit capability." });
		const form = await request.formData();
		const reason = String(form.get("reason") ?? "").trim();
		const successor = Number(form.get("successor_id"));
		// The name the request was filed from. The API retires only this pointer when the concept
		// answers to others, so losing it here would turn "retire this name" back into "retire the
		// concept".
		const pointerId = Number(form.get("pointer_id"));
		if (!reason) return fail(400, { error: "Say why this should be retired." });

		try {
			await api(`${conceptBase(form)}/deprecation-request`, {
				method: "POST",
				token: locals.token,
				body: { reason, successor_id: successor || null, pointer_id: pointerId || null },
				fetch,
			});
		} catch (err) {
			return failFromApi(err);
		}
		return { deprecationRequested: true };
	},

	// Discard an unpublished draft. Drops the ?draft= pin afterwards so we fall back to the
	// published view for the same source tab.
	deleteDraft: async ({ request, locals, fetch }) => {
		if (!can(locals.user, "can_edit")) return fail(403, { error: "Editing requires sign-in." });
		const form = await request.formData();
		const draftId = String(form.get("draftId") ?? "");
		const source = String(form.get("source") ?? "");

		try {
			await api(`${conceptBase(form)}/drafts/${draftId}`, {
				method: "DELETE",
				token: locals.token,
				fetch,
			});
		} catch (err) {
			return failFromApi(err);
		}
		redirect(303, keepPin(form, source ? `source=${encodeURIComponent(source)}` : ""));
	},
};

/** A same-page redirect target that keeps the pinned member — dropping `?cid=` would silently
 *  move a group page to its first member. */
function keepPin(form: FormData, query: string): string {
	const cid = form.get("cid");
	const qs = [query, cid ? `cid=${cid}` : ""].filter(Boolean).join("&");
	return qs ? `?${qs}` : "?";
}
