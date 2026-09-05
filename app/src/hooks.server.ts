import type { Handle } from "@sveltejs/kit";
import { api, ApiError } from "$lib/server/api";
import { SESSION_COOKIE } from "$lib/server/session";
import type { User } from "$lib/types";

// On every request: read the session cookie and, if present, resolve the user via
// `GET /auth/me`. An invalid/expired token clears the cookie and leaves the user null.
export const handle: Handle = async ({ event, resolve }) => {
	event.locals.user = null;
	event.locals.token = null;

	const token = event.cookies.get(SESSION_COOKIE);
	if (token) {
		try {
			event.locals.user = await api<User>("/auth/me", { token, fetch: event.fetch });
			event.locals.token = token;
		} catch (err) {
			// 401 ⇒ stale token: drop it so the UI shows logged-out. Other errors (API down)
			// shouldn't nuke the cookie — surface as logged-out for this request only.
			if (err instanceof ApiError && err.status === 401) {
				event.cookies.delete(SESSION_COOKIE, { path: "/" });
			}
		}
	}

	return resolve(event);
};
