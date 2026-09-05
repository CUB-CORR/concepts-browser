import type { TaxonomyName } from "$lib/types";

// What the taxonomy selector does while a concept page is open.
//
// A concept is one identity with a name per naming system, so switching taxonomy on its page
// should stay on the concept and change what it is called — not drop the reader back on the
// list. Everything here works off `ConceptDetail.names`, which the detail load already carries
// (every pointer of the concept, across taxonomies, retired ones flagged), so the switch costs
// no extra request.

/** Route id of the concept detail page — the one place the selector behaves differently. */
export const CONCEPT_ROUTE_ID = "/concepts/tax/[taxonomy]/[name]";

/** Query params that stay meaningful when only the *name* of the concept changes: the date
 *  lens, the open source tab, and a version/draft pin (both address the same concept id). */
const CARRIED_PARAMS = ["date", "source", "v", "draft"];

/** The instant the page is looking at: the date lens's end of day, or now when it is off.
 *  Mirrors `apiDate()` server-side, which is what resolution on the API uses. */
function lensInstant(date: string | null | undefined): number {
	const at = date ? Date.parse(`${date}T23:59:59Z`) : NaN;
	return Number.isNaN(at) ? Date.now() : at;
}

/** Was this pointer's window open at `at`? Same rule as `services.resolve_pointers`. */
function activeAt(n: TaxonomyName, at: number): boolean {
	const from = n.created_at ? Date.parse(n.created_at) : -Infinity;
	const until = n.deprecated_at ? Date.parse(n.deprecated_at) : Infinity;
	return from <= at && at < until;
}

/**
 * What the concept is called in `taxonomy` right now (or as of the date lens), or null when it
 * holds no live name there. A retired name counts as absent — it is not somewhere to navigate
 * to — and a primary name wins over an alias.
 */
export function liveNameIn(
	names: TaxonomyName[],
	taxonomy: string,
	date: string | null | undefined,
): TaxonomyName | null {
	const at = lensInstant(date);
	const live = names.filter((n) => n.taxonomy === taxonomy && activeAt(n, at));
	if (live.length === 0) return null;
	return live.find((n) => n.relationship !== "alias") ?? live[0];
}

/**
 * The concept's page under another taxonomy. `?cid=` pins the concept by id, so a name that
 * happens to name a group over there still lands on *this* concept rather than the group's
 * first member; `?taxonomy=` is what makes the selection stick (the cookie is written from it).
 */
export function conceptHrefIn(
	taxonomy: string,
	name: string,
	conceptId: number,
	current: URLSearchParams,
): string {
	const params = new URLSearchParams({ taxonomy });
	for (const key of CARRIED_PARAMS) {
		const value = current.get(key);
		if (value) params.set(key, value);
	}
	params.set("cid", String(conceptId));
	return `/concepts/tax/${encodeURIComponent(taxonomy)}/${encodeURIComponent(name)}?${params}`;
}
