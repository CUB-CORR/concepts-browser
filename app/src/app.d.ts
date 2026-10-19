// See https://svelte.dev/docs/kit/types#app.d.ts
import type { User } from "$lib/types";
import type { DocsMenu } from "$lib/docs/types";

declare global {
	namespace App {
		// interface Error {}
		interface Locals {
			/** Resolved from the session cookie in hooks.server.ts; null when logged out. */
			user: User | null;
			/** The JWT from the session cookie, for authenticated API calls. */
			token: string | null;
		}
		interface PageData {
			/** From the root layout: the Docs menu's links and the chapters a link may point at. */
			docs?: DocsMenu;
		}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
