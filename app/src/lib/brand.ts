import { env } from "$env/dynamic/public";

/* Deployment-level branding, overridable per environment via PUBLIC_* env vars (read at
 * runtime under adapter-node — no rebuild needed). Asset paths point into /brand/ (see
 * static/brand/), which deployments may also replace wholesale with a bind-mount.
 *
 * Unset or empty vars fall back to the shipped defaults (docker-compose passes empty
 * strings for unset vars). The literal value "none" disables an optional element
 * (footer, API docs link, directory logo). */

const NONE = "none";

/** Env override, or `fallback` when unset/empty; "" when explicitly disabled via "none". */
function pick(value: string | undefined, fallback: string): string {
	if (value === NONE) return "";
	return value ? value : fallback;
}

export const brand = {
	/** Product name shown in the top bar next to the logo. */
	appName: pick(env.PUBLIC_APP_NAME, "Charité Outcomes Research Repository"),
	/** App logo (light background / dark background variants). */
	logoLight: pick(env.PUBLIC_BRAND_LOGO, "/logos/corr-white.png"),
	logoDark: pick(env.PUBLIC_BRAND_LOGO_DARK, "/logos/corr-darkmode.png"),
	/** Full-bleed background of the sign-in page. */
	loginBackground: pick(env.PUBLIC_BRAND_BACKGROUND, "/brand/background.jpg"),
	/** Hint under the sign-in heading — name your institution's credentials here. */
	loginHint: pick(env.PUBLIC_LOGIN_HINT, "Please log in using your directory credentials."),
	/** External API docs link in the top-bar Docs menu; "none" hides the entry. */
	apiDocsUrl: pick(env.PUBLIC_API_DOCS_URL, "/api/docs"),
	/** Attribution footer; "none" hides it. */
	footerText: pick(
		env.PUBLIC_FOOTER_TEXT,
		"Created by researchers at Charité – Universitätsmedizin Berlin",
	),
	footerLogoLight: pick(env.PUBLIC_FOOTER_LOGO, "/brand/charite.png"),
	footerLogoDark: pick(env.PUBLIC_FOOTER_LOGO_DARK, "/brand/charite-negativ.png"),
	footerUrl: pick(env.PUBLIC_FOOTER_URL, "https://www.charite.de"),
	/** Logo shown next to "Directory profile" for LDAP-backed users; "none" hides it. */
	directoryLogoLight: pick(env.PUBLIC_DIRECTORY_LOGO, "/brand/charite.png"),
	directoryLogoDark: pick(env.PUBLIC_DIRECTORY_LOGO_DARK, "/brand/charite-negativ.png"),
	/* Issue tracker the "Report issue" button on a concept page files against: a URL template
	 * with `{tax_name}` / `{concept_name}` placeholders (see conceptIssueUrl). No default —
	 * unset means the button is not rendered, because there is nowhere to send the report. */
	issueUrlTemplate: pick(env.PUBLIC_GITHUB_ISSUE_URL, ""),
	/* Git commit the running image was built from, baked in by CI (docker build-arg →
	 * runtime ENV). No default — unset means nothing is shown in the footer. */
	buildCommit: pick(env.PUBLIC_BUILD_COMMIT, ""),
};

/** The tracker URL for one concept, or "" when this deployment configured no template.
 *
 * The template is prefilled-issue syntax, e.g.
 *   https://github.com/ORG/REPO/issues/new?template=concept.yml&title=[{tax_name}/{concept_name}]
 * The values land inside query parameters, so they are percent-encoded. */
export function conceptIssueUrl(taxonomy: string, name: string): string {
	if (!brand.issueUrlTemplate) return "";
	return brand.issueUrlTemplate
		.replaceAll("{tax_name}", encodeURIComponent(taxonomy))
		.replaceAll("{concept_name}", encodeURIComponent(name));
}
