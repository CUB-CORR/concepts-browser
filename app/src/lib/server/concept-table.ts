// What a `/concepts` URL asks the API for. The page's `load` and the `/concepts/table` proxy
// the browser calls while you type both go through here, so the first slice SvelteKit renders
// and every slice fetched afterwards are read off the same URL by the same rules — the one
// thing that would otherwise drift as controls are added.
import { api } from "$lib/server/api";
import { apiDate } from "$lib/server/prefs";
import { can } from "$lib/caps";
import type { ConceptTablePage, User } from "$lib/types";

/** How many rows a slice holds. One page of scrolling, not one screenful. */
export const PAGE_SIZE = 50;

export interface TableRequest {
	/** The query params the API takes, ready to hand to `api()`. */
	query: Record<string, string | number | boolean | string[] | undefined>;
	/** True when anything narrows the list — what decides whether an export needs ids. */
	filtered: boolean;
	q: string;
	status: string[];
	sort: string | null;
	dir: "asc" | "desc";
	includeDeprecated: boolean;
}

/** Read a `/concepts` URL into an API request. `page` is 1-based; the scroll asks for 2, 3, … */
export function tableRequest(
	url: URL,
	taxonomy: string,
	date: string,
	user: User | null | undefined,
	page = 1,
): TableRequest {
	// Retired names are off by default — they still resolve, but listing them by default would
	// bury the live vocabulary under every spelling it ever had.
	const includeDeprecated = url.searchParams.get("include_deprecated") === "true";
	const q = url.searchParams.get("q") ?? "";
	const status = url.searchParams.getAll("status");
	const source = url.searchParams.getAll("source");
	const type = url.searchParams.getAll("type");
	const configured = url.searchParams.get("configured") ?? "all";
	// No `sort` in the URL means "whatever this view is for": the API answers a search by
	// relevance and everything else by most-used-first. Only an explicit column click is sent.
	const sort = url.searchParams.get("sort");
	const dir = url.searchParams.get("dir") === "asc" ? "asc" : "desc";

	// The export takes concept ids so the file matches what the admin is looking at. Only an
	// admin can export, and only a *filtered* view needs the ids at all — an unfiltered export
	// is sent as "everything in the taxonomy" — so this is the one case that asks for them.
	const filtered =
		q !== "" || status.length > 0 || source.length > 0 || type.length > 0 || configured !== "all";
	// The ids describe the whole matched set, not a slice, so only the first one asks for them.
	const wantIds = filtered && page === 1 && can(user, "can_admin");

	return {
		query: {
			taxonomy,
			date: apiDate(date),
			include_deprecated: includeDeprecated || undefined,
			q: q || undefined,
			status,
			source,
			type,
			configured: configured === "all" ? undefined : configured,
			sort: sort || undefined,
			dir,
			page,
			page_size: PAGE_SIZE,
			include_ids: wantIds || undefined,
		},
		filtered,
		q,
		status,
		sort,
		dir,
		includeDeprecated,
	};
}

/** Fetch one slice of the table for a `/concepts` URL. */
export function fetchTable(
	req: TableRequest,
	token: string | null | undefined,
	fetch: typeof globalThis.fetch,
): Promise<ConceptTablePage> {
	return api<ConceptTablePage>("/concepts/table", { token, query: req.query, fetch });
}
