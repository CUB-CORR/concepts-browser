// BFF client: the only thing that talks to FastAPI. Reads (in `load`) and writes (in form
// actions) go through here; the bearer token is injected server-side and never reaches the
// browser.
import { env } from "$env/dynamic/private";
import type { NameExistsConflict } from "$lib/types";

const baseUrl = () => (env.API_INTERNAL_URL || "http://localhost:8000").replace(/\/$/, "");

/** An array becomes a repeated param (`?status=a&status=b`) — how FastAPI binds a list. */
export type QueryValue = string | number | boolean | null | undefined | string[];

export interface ApiOptions {
	method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
	/** Bearer token for authenticated calls (from `locals.token`). */
	token?: string | null;
	/** Request body: JSON by default, or a `FormData` for the multipart upload endpoints
	 *  (whose content-type — boundary and all — only `fetch` can set correctly). */
	body?: unknown;
	/** Query params; null/undefined entries are dropped. */
	query?: Record<string, QueryValue>;
	/** SvelteKit's `event.fetch`, when available. */
	fetch?: typeof fetch;
}

/** A non-2xx response from the API, carrying the parsed error body. */
export class ApiError extends Error {
	constructor(
		readonly status: number,
		readonly body: unknown,
	) {
		super(ApiError.messageOf(status, body));
		this.name = "ApiError";
	}

	/** FastAPI puts errors under `detail` — a string, or a dict like {error, errors}. */
	static messageOf(status: number, body: unknown): string {
		const detail = (body as { detail?: unknown })?.detail ?? body;
		if (typeof detail === "string") return detail;
		if (detail && typeof detail === "object") {
			const d = detail as Record<string, unknown>;
			if (typeof d.error === "string") return d.error;
			if (typeof d.message === "string") return d.message;
		}
		return `API request failed (${status})`;
	}

	/** The `name_exists` 409 body, when this is one: an identifier already active in the
	 *  taxonomy for another concept. The caller re-sends with `confirm_group: true` once the
	 *  user has said they mean to form a group. A 409 without this body is a plain refusal
	 *  (e.g. this concept already holds the name) and has nothing to confirm. */
	get nameExists(): NameExistsConflict | null {
		const detail = (this.body as { detail?: unknown })?.detail;
		if (detail && typeof detail === "object" && (detail as Record<string, unknown>).error === "name_exists") {
			const d = detail as unknown as NameExistsConflict;
			return { taxonomy: d.taxonomy, name: d.name, members: d.members ?? [] };
		}
		return null;
	}

	/** Schema-validation errors from the write endpoints, if present. */
	get validationErrors(): { path: string; message: string }[] | null {
		const detail = (this.body as { detail?: unknown })?.detail;
		if (detail && typeof detail === "object" && Array.isArray((detail as Record<string, unknown>).errors)) {
			return (detail as { errors: { path: string; message: string }[] }).errors;
		}
		return null;
	}
}

/** Like `api`, but hands back the raw `Response` — for pass-through of binary bodies
 * (file downloads). Does not throw on non-2xx; callers inspect `res.ok` themselves. */
export async function apiRaw(path: string, opts: ApiOptions = {}): Promise<Response> {
	const { method = "GET", token, body, query, fetch: f = fetch } = opts;

	const url = new URL(baseUrl() + path);
	if (query) {
		for (const [k, v] of Object.entries(query)) {
			if (Array.isArray(v)) for (const one of v) url.searchParams.append(k, one);
			else if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, String(v));
		}
	}
	// Concept reads require a `project` param. For app traffic it's a placeholder the API
	// ignores (we authenticate as the app via the secret below); it exists only to satisfy the
	// required param. External integrators pass a real project name instead.
	if (method === "GET" && /^\/concepts?(\/|$)/.test(path) && !url.searchParams.has("project")) {
		url.searchParams.set("project", "internal");
	}

	// A FormData body goes out as multipart, untouched: `fetch` generates the boundary and the
	// matching content-type header, which we must therefore not set ourselves.
	const multipart = body instanceof FormData;

	const headers: Record<string, string> = {};
	if (token) headers.authorization = `Bearer ${token}`;
	if (body !== undefined && !multipart) headers["content-type"] = "application/json";
	// Mark every call as coming from our web app: the API treats requests carrying this
	// shared secret as internal browsing (no project required) and attributes their audit-log
	// rows to the app. External clients lack it and must name a project. Server-side only.
	if (env.APP_SHARED_SECRET) headers["x-app-secret"] = env.APP_SHARED_SECRET;

	return f(url, {
		method,
		headers,
		body: body === undefined ? undefined : multipart ? (body as FormData) : JSON.stringify(body),
	});
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
	const res = await apiRaw(path, opts);

	const text = await res.text();
	const parsed = text ? safeJson(text) : null;

	if (!res.ok) throw new ApiError(res.status, parsed);
	return parsed as T;
}

function safeJson(text: string): unknown {
	try {
		return JSON.parse(text);
	} catch {
		return text;
	}
}
