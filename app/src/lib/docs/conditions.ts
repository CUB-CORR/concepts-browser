/* `:::if{...}` / `:::unless{...}` in a guide page: a passage — or whole `##` sections — shown
 * only when every condition named holds. Evaluated in the browser against the reader and this
 * deployment, so the server hands every branch over; the search index includes them all. */

import { brand } from "$lib/brand";
import { can } from "$lib/caps";
import type { Capability, User } from "$lib/types";
import type { DocLink } from "./types";

export type DirectiveAttrs = Record<string, string | null | undefined> | null | undefined;

/** A condition as it sits on a section that a top-level `:::if` / `:::unless` wrapped. */
export interface DocCondition {
	negate: boolean;
	attributes: Record<string, string>;
}

const features: Record<string, () => boolean> = {
	/** The concept page's "Report issue" button exists (PUBLIC_GITHUB_ISSUE_URL is set). */
	"issue-tracker": () => !!brand.issueUrlTemplate,
};

/** True when every condition `attrs` names holds: `feature=<name>` (see `features`),
 *  `link=<id>` (a link group defines that id) and `cap=<capability>` (the reader holds it). */
export function holds(attrs: DirectiveAttrs, user: User | null | undefined, links: DocLink[]): boolean {
	const a = attrs ?? {};
	if (a.feature != null && !features[a.feature]?.()) return false;
	if (a.link != null && !links.some((l) => l.id === a.link)) return false;
	if (a.cap != null && !can(user, a.cap as Capability)) return false;
	return true;
}

export function shown(
	condition: DocCondition | undefined,
	user: User | null | undefined,
	links: DocLink[],
): boolean {
	if (!condition) return true;
	return holds(condition.attributes, user, links) !== condition.negate;
}
