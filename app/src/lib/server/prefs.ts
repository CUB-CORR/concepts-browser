import type { Cookies } from "@sveltejs/kit";

// The two top-bar selections that scope every read.
//   taxonomy — a durable preference (which naming system you work in): persisted in a cookie,
//              overridable via ?taxonomy=.
//   date     — the transient "view as of a date" lens: lives only in the URL (?date= / ?d=) so it
//              is shareable, can be cleared, and never resurrects on a fresh visit. Internal links
//              carry it (see withDate) to keep the lens applied across in-session navigation.
export const TAXONOMY_COOKIE = "taxonomy";
export const DEFAULT_TAXONOMY = "corr_v1";

export interface Prefs {
	/** Active taxonomy key; never empty (falls back to corr_v1). */
	taxonomy: string;
	/** Global date filter as YYYY-MM-DD, or "" when live/current. */
	date: string;
}

/** taxonomy: URL param → persisted cookie → default (persisted). date: URL only, no persistence. */
export function resolvePrefs(url: URL, cookies: Cookies): Prefs {
	const taxonomy =
		url.searchParams.get("taxonomy") || cookies.get(TAXONOMY_COOKIE) || DEFAULT_TAXONOMY;
	const date = url.searchParams.get("date") ?? url.searchParams.get("d") ?? "";

	cookies.set(TAXONOMY_COOKIE, taxonomy, {
		path: "/",
		httpOnly: false,
		sameSite: "lax",
		maxAge: 60 * 60 * 24 * 365,
	});

	return { taxonomy, date };
}

/** Forward the date filter to the API as an inclusive end-of-day UTC timestamp. */
export function apiDate(date: string): string | undefined {
	if (!date) return undefined;
	return `${date}T23:59:59Z`;
}
