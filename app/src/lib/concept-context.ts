import { getContext, setContext } from "svelte";

// Which concept the detail page's forms write to.
//
// A name may point at several concepts, so the page is always about one *pinned member*
// (`?cid=`), and every write it offers has to name that member by id — resolving by name again
// on the server would be ambiguous exactly when it matters. Form actions replace the query
// string, so the id travels as a hidden `cid` field in each form; this context is how the
// components deep in the tree (the draft editor, the file list, the history) get it without
// threading a prop through every layer.
const KEY = Symbol("concept");

export interface ConceptContext {
	/** The pinned member's concept id. */
	readonly id: number;
	/** True when the name this page was reached by points at more than one concept. */
	readonly grouped: boolean;
}

export function setConceptContext(ctx: ConceptContext): void {
	setContext(KEY, ctx);
}

export function conceptContext(): ConceptContext {
	return getContext<ConceptContext>(KEY);
}
