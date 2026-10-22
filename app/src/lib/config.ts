import { env } from "$env/dynamic/public";
import { pick } from "$lib/brand";

// Central place for app-level, non-secret UI configuration.

export interface BannerConfig {
	/** When false, the banner is not rendered. */
	enabled: boolean;
	/** Text shown inline in the banner. */
	message: string;
	/** Label for the trailing link. Omit (or omit linkHref) to hide the link. */
	linkLabel?: string;
	/** External URL the trailing link points to. Opens in a new tab. */
	linkHref?: string;
}

export interface AppConfig {
	banner: BannerConfig;
}

export const appConfig: AppConfig = {
	banner: {
		enabled: env.PUBLIC_BANNER_MESSAGE !== "none",
		message: pick(env.PUBLIC_BANNER_MESSAGE, "Research preview — please report any errors."),
		linkLabel: pick(env.PUBLIC_BANNER_LINK_LABEL, "Report issue"),
		linkHref: pick(
			env.PUBLIC_BANNER_LINK_URL,
			"https://github.com/CUB-CORR/concepts-browser/issues/new",
		),
	},
};
