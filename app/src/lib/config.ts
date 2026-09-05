// Central place for app-level, non-secret UI configuration. Edit the values here to
// change site-wide chrome (e.g. the preview banner) without touching component code.

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
		enabled: true,
		message: "Research preview — please report any errors.",
		linkLabel: "Report issue",
		linkHref: "https://github.com/CUB-CORR/concepts-browser/issues/new",
	},
};
