import { ALL_CAPABILITIES, type Capability, type User } from "$lib/types";

// The incremental capability chain, weakest first — mirrors `security.CAPABILITY_CHAIN`
// (api/security.py). Holding one entails every capability to its left: an editor can read
// what they edit, a publisher can review what they release. Everything outside the chain
// (`create_api_key`, `add_project`) is an independent flag, and `can_admin` implies the lot.
export const CAPABILITY_CHAIN = [
	"can_read",
	"can_read_detail",
	"can_edit",
	"can_publish",
] as const satisfies readonly Capability[];

/** Does `caps` cover `capability`, directly or by entailment? The one place the UI resolves
 *  the hierarchy — mirrors `deps.has_capability`, which enforces it authoritatively. */
export function hasCapability(
	caps: readonly Capability[] | readonly string[] | null | undefined,
	capability: Capability,
): boolean {
	const held = caps ?? [];
	if (held.includes("can_admin")) return true;
	if (held.includes(capability)) return true;
	const rank = (CAPABILITY_CHAIN as readonly string[]).indexOf(capability);
	if (rank < 0) return false; // outside the chain: nothing implies it but can_admin
	return held.some((c) => (CAPABILITY_CHAIN as readonly string[]).indexOf(c) > rank);
}

/** Position of the strongest chain capability in `caps`, or -1 when it holds none. Mirrors the
 *  `highest` computation in `security.expand_capabilities`. */
export function highestChainRank(caps: readonly Capability[] | readonly string[]): number {
	return Math.max(
		-1,
		...caps.map((c) => (CAPABILITY_CHAIN as readonly string[]).indexOf(c as string)),
	);
}

/** `caps` with everything it entails filled in, in `ALL_CAPABILITIES` order: `can_admin` grants
 *  the lot, and a chain capability grants the lesser ones. Mirrors
 *  `security.expand_capabilities`.
 *
 *  Used where an explicit set has to match what is displayed — the user-management table shows
 *  implied capabilities ticked, and stores them ticked. Grants stay equivalent either way,
 *  since `deps.has_capability` resolves the hierarchy at evaluation time regardless. */
export function expandCapabilities(caps: readonly Capability[]): Capability[] {
	if (caps.includes("can_admin")) return [...ALL_CAPABILITIES];
	const held = new Set<string>(caps);
	const highest = highestChainRank(caps);
	for (const c of CAPABILITY_CHAIN.slice(0, highest + 1)) held.add(c);
	return ALL_CAPABILITIES.filter((c) => held.has(c));
}

/** `hasCapability` for a signed-in user (null when signed out). */
export function can(user: User | null | undefined, capability: Capability): boolean {
	if (!user) return false;
	return hasCapability(user.capabilities, capability);
}
