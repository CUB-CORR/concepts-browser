import type { Cookies } from "@sveltejs/kit";
import { dev } from "$app/environment";

export const SESSION_COOKIE = "session";

/** httpOnly + sameSite=lax cookie holding the JWT . `secure` off in dev. */
export function setSession(cookies: Cookies, token: string, expiresAt: string): void {
	const expires = new Date(expiresAt);
	cookies.set(SESSION_COOKIE, token, {
		path: "/",
		httpOnly: true,
		sameSite: "lax",
		secure: !dev,
		expires: isNaN(expires.getTime()) ? undefined : expires,
	});
}

export function clearSession(cookies: Cookies): void {
	cookies.delete(SESSION_COOKIE, { path: "/" });
}
