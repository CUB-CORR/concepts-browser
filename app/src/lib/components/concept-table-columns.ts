// The concepts table's columns, in one place: their order, their labels, whether they can be
// hidden, and which server sort key each one asks for.
//
// The ids are *the server's sort keys* (`/concepts/table?sort=…`), so a header click needs no
// translation table between the two — a column that cannot be sorted simply has no key.
import type { ConceptTableRow } from "$lib/types";

export type ConceptColumnId =
	| "name"
	| "display_name"
	| "clinical"
	| "description"
	| "documentation"
	| "usage"
	| "mine"
	| "sources"
	| "types"
	| "status"
	| "edited"
	| "editor"
	| "names"
	| "version";

export interface ConceptColumnSpec {
	id: ConceptColumnId;
	label: string;
	/** False for the name column: a concepts table without the concept is not a view of it. */
	hideable: boolean;
	/** Shown when the reader has not chosen a set of columns. */
	visibleByDefault: boolean;
	/** True when `sort=<id>` is a key the API accepts. */
	sortable: boolean;
	/** Sensible first click direction — text reads best ascending, counts descending. */
	firstDir: "asc" | "desc";
	class?: string;
}

// The array order *is* the table's column order. The default view reads left to right as
// name → status → types → sources → version → description → reads: what the name is, how far
// along it is, how it is defined, and only then the prose and the popularity. The columns the
// View menu can add sit where they belong beside their neighbours, so turning one on inserts
// it rather than appending it to the far right.
export const conceptColumns: ConceptColumnSpec[] = [
	{ id: "name", label: "Name", hideable: false, visibleByDefault: true, sortable: true, firstDir: "asc" },
	{ id: "display_name", label: "Label", hideable: true, visibleByDefault: false, sortable: true, firstDir: "asc" },
	{ id: "status", label: "Status", hideable: true, visibleByDefault: true, sortable: true, firstDir: "asc" },
	{ id: "types", label: "Types", hideable: true, visibleByDefault: true, sortable: false, firstDir: "asc" },
	{ id: "sources", label: "Sources", hideable: true, visibleByDefault: true, sortable: false, firstDir: "asc" },
	{ id: "version", label: "Version", hideable: true, visibleByDefault: true, sortable: true, firstDir: "desc", class: "text-right" },
	// "Description" is the clinical documentation's opening line; the concept's own one-line
	// `description` field is the separate, off-by-default "Summary" column below it.
	{ id: "clinical", label: "Description", hideable: true, visibleByDefault: true, sortable: false, firstDir: "asc" },
	{ id: "description", label: "Summary", hideable: true, visibleByDefault: false, sortable: false, firstDir: "asc" },
	{ id: "documentation", label: "Docs", hideable: true, visibleByDefault: false, sortable: true, firstDir: "desc", class: "text-center" },
	{ id: "usage", label: "Reads", hideable: true, visibleByDefault: true, sortable: true, firstDir: "desc", class: "text-right" },
	{ id: "mine", label: "My reads", hideable: true, visibleByDefault: false, sortable: true, firstDir: "desc", class: "text-right" },
	{ id: "edited", label: "Last edited", hideable: true, visibleByDefault: false, sortable: true, firstDir: "desc" },
	{ id: "editor", label: "Last edited by", hideable: true, visibleByDefault: false, sortable: true, firstDir: "asc" },
	{ id: "names", label: "Names", hideable: true, visibleByDefault: false, sortable: true, firstDir: "desc", class: "text-right" },
];

export const DEFAULT_VISIBLE: ConceptColumnId[] = conceptColumns
	.filter((c) => c.visibleByDefault)
	.map((c) => c.id);

/** The visibility map a `cols=` query param describes; the defaults when it is absent. */
export function visibilityFromParam(param: string | null): Record<string, boolean> {
	const wanted = new Set<string>(
		param === null ? DEFAULT_VISIBLE : param.split(",").filter(Boolean),
	);
	return Object.fromEntries(
		conceptColumns.map((c) => [c.id, !c.hideable || wanted.has(c.id)]),
	);
}

/** The `cols=` value for a visibility map, or null when it is exactly the default set. */
export function visibilityToParam(visibility: Record<string, boolean>): string | null {
	const shown = conceptColumns.filter((c) => c.hideable && visibility[c.id]).map((c) => c.id);
	const isDefault =
		shown.length === DEFAULT_VISIBLE.filter((id) => id !== "name").length &&
		shown.every((id) => DEFAULT_VISIBLE.includes(id));
	return isDefault ? null : shown.join(",");
}

/** What a row shows in each cell that is a plain value. Keeps the markup free of accessors. */
export function cellValue(row: ConceptTableRow, id: ConceptColumnId): unknown {
	switch (id) {
		case "name":
			return row.name;
		case "display_name":
			return row.display_name;
		case "clinical":
			return row.doc_clinical_excerpt;
		case "description":
			return row.description;
		case "documentation":
			return row.doc_size;
		case "usage":
			return row.usage_reads;
		case "mine":
			return row.my_reads;
		case "sources":
			return row.sources;
		case "types":
			return row.types;
		case "status":
			return row.doc_status;
		case "edited":
			return row.last_edited_at;
		case "editor":
			return row.last_edited_by;
		case "names":
			return row.names_count;
		case "version":
			return row.version;
	}
}
