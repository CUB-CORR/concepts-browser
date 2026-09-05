import type { PageServerLoad } from "./$types";
import { redirect } from "@sveltejs/kit";

// The deprecation queue moved onto /review, next to the open drafts — the two things a
// reviewer is waiting on are one screen now. Kept as a permanent redirect because this URL was
// the top-bar link and is in people's bookmarks; the `?status=` tab it was on comes along.
export const load: PageServerLoad = ({ url }) => {
	const status = url.searchParams.get("status");
	redirect(308, status ? `/review?status=${encodeURIComponent(status)}` : "/review");
};
