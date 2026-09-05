// Shapes returned by the Concepts API. Hand-written (the API has no OpenAPI client step
// yet); keep in sync with `api/routers/*` and `api/services.py`.

export type Capability =
	| "can_read"
	| "can_read_detail"
	| "can_edit"
	| "can_publish"
	| "create_api_key"
	| "add_project"
	| "can_admin";

// All assignable capabilities, in display order (mirrors api/security.ALL_CAPABILITIES):
// the incremental chain weakest-first, then the two independent flags, then can_admin.
// Holding a chain capability entails the lesser ones, and can_admin implies the rest — see
// `caps.ts`, which is where that is resolved.
export const ALL_CAPABILITIES: Capability[] = [
	"can_read",
	"can_read_detail",
	"can_edit",
	"can_publish",
	"create_api_key",
	"add_project",
	"can_admin",
];

export interface User {
	id: number;
	username: string;
	display_name: string | null;
	capabilities: Capability[];
	is_active: boolean;
}

/** A user row from `GET /admin/users` (admin-only), for the user-management page. */
export interface AdminUser extends User {
	is_ldap: boolean;
	created_at: string;
}

/** A directory-search hit from `GET /admin/directory` (admin-only), for proactively adding an
 *  LDAP user who has never logged in. `user_id` is set when the person is already in our DB. */
export interface DirectoryEntry {
	ldap_guid: string;
	username: string;
	display_name: string | null;
	user_id: number | null;
}

/** A user's profile (`GET /auth/users/{username}/profile`): account state, capabilities and,
 *  for LDAP users, the full directory attribute snapshot (attr → list of string values). */
export interface Profile extends User {
	is_ldap: boolean;
	created_at: string;
	ldap_profile: Record<string, string[]> | null;
}

/** One concept a user has read, from the usage rollup (`GET /usage/users/{id}`). `name` and
 *  `taxonomy` are what it was last read under — enough to link to it, and null for a read that
 *  never resolved to a name. */
export interface UsageConcept {
	concept_id: number;
	name: string | null;
	taxonomy: string | null;
	reads: number;
	first_used_at: string;
	last_used_at: string;
	/** The distinct versions read, sorted and joined ("1, 3, 4"); null if none was recorded. */
	versions: string | null;
}

/** One user's API usage: when they were last active, and what they have read. Visible to that
 *  user and to admins — the API enforces it, this type just describes the payload. */
export interface UserUsage {
	user_id: number;
	username: string;
	display_name: string | null;
	last_active_at: string | null;
	concepts_used: number;
	total_reads: number;
	concepts: UsageConcept[];
}

/** An API key as listed on the owner's key-management page (`GET /api-keys`). Never carries
 *  the secret — that is shown once, in the create response. */
export interface ApiKey {
	id: number;
	name: string;
	key_prefix: string;
	scopes: Capability[];
	created_at: string;
	expires_at: string | null;
	revoked: boolean;
	last_used_at: string | null;
}

/** Response to `POST /api-keys`: the created key plus its one-time plaintext `key`. */
export interface ApiKeyCreated extends ApiKey {
	key: string;
}

/** A user placed in a project's `lead` field. */
export interface ProjectLead {
	id: number;
	username: string;
	display_name: string | null;
}

export type ProjectStatus = "active" | "completed" | "deleted";

/** A row of `GET /projects` (and `GET /projects/{id}`). */
export interface Project {
	id: string;
	name: string;
	description: string | null;
	ea_id: string | null;
	created_on: string;
	completed_on: string | null;
	deleted_on: string | null;
	status: ProjectStatus;
	leads: ProjectLead[];
	/** Version the project last accepted; 0 = never accepted. */
	license_approval: number;
	/** Current active license version (null if none configured). */
	license_current_version: number | null;
	/** True when `license_approval` is up to date with the current version. */
	license_ok: boolean;
	license_approved_on: string | null;
	/** Whether the signed-in user (a lead, or an admin) may edit this project. */
	can_edit: boolean;
	/* The study context: the PICO frame the project studies and the study team behind it.
	 * Written only on the project page, by a lead or an admin. */
	pico_population: string | null;
	pico_intervention: string | null;
	pico_comparison: string | null;
	pico_outcome: string | null;
	study_team: string | null;
}

/** An active user, for the lead multi-select (`GET /projects/user-options`). */
export interface UserOption {
	id: number;
	username: string;
	display_name: string | null;
}

/** The current CORR license (`GET /projects/license`). */
export interface License {
	version: number;
	body: string;
	created_on: string;
}

export interface ActivityBucket {
	ts: string;
	count: number;
}

export interface ActivityWindow {
	total: number;
	buckets: ActivityBucket[];
}

/** Per-project request activity (`GET /projects/{id}/activity`). */
export interface ProjectActivity {
	last_24h: ActivityWindow;
	last_week: ActivityWindow;
	last_month: ActivityWindow;
}

/** The kinds of event in the audit log — the three tabs of the audit page. */
export type AuditEventKind = "login" | "api_call" | "email";

/** What became of a message: the server accepted it, we tried and it didn't go out, or we
 *  never tried (mail disabled, or the directory has no address for the user). */
export type EmailStatus = "sent" | "failed" | "skipped";

/** The user an audit row is attributed to. Null on a failed login (nobody authenticated) —
 *  the name that was tried is then in `detail.username`. */
export interface AuditActor {
	id: number;
	username: string;
	display_name: string | null;
}

/** One row of `GET /audit/events` (admin-only). */
export interface AuditEvent {
	id: number;
	created_at: string;
	event: AuditEventKind;
	/** The caller — except on an `email` row, where it's the recipient. */
	user: AuditActor | null;
	auth_method: "jwt" | "api_key" | null;

	/** The request. All null on an `email` row: mail is sent from a background task, not served.
	 *  "app" = our own web app; "external" = an API client that named a project. */
	client_type: "app" | "external" | null;
	method: string | null;
	path: string | null;
	query_string: string | null;
	status_code: number | null;

	project_id: string | null;
	project_name: string | null;

	concept_id: number | null;
	concept_name: string | null;
	taxonomy: string | null;
	/** The version actually served (not necessarily the one asked for — see `detail.selector`). */
	concept_version: number | null;

	ip_address: string | null;
	user_agent: string | null;

	/** The email. Set only on an `email` row. `email_to` is null when the directory had no
	 *  address for the recipient — which is exactly when `email_status` is "skipped". */
	email_kind: string | null;
	email_to: string | null;
	email_subject: string | null;
	email_status: EmailStatus | null;

	/** Full context: for a request, its path/query params, the concept selector and (for a
	 *  login) the attempted username; for an email, what it granted and why it didn't go out. */
	detail: {
		query_params?: Record<string, string>;
		path_params?: Record<string, string>;
		selector?: { v: number | null; date: string | null; draft: number | null };
		username?: string;
		capabilities?: string[];
		reason?: string;
	} | null;
}

/** A page of `GET /audit/events`, with the total behind the current filters. */
export interface AuditPage {
	items: AuditEvent[];
	total: number;
	limit: number;
	offset: number;
}

/** The values that actually occur in the log (`GET /audit/filter-options`) — so a filter never
 *  offers something with no rows behind it. */
export interface AuditFilterOptions {
	users: AuditActor[];
	projects: { id: string; name: string }[];
	concepts: { id: number; name: string; taxonomy: string }[];
}

export interface Taxonomy {
	key: string;
	name: string | null;
	version: string | null;
}

export interface Source {
	key: string;
	nicename: string | null;
	supported_types: string[];
	schema_governed: boolean;
}

/** A row of `GET /concepts`: one **pointer** — an identifier and the concept it names.
 *  A concept named twice yields two rows; an identifier naming two concepts yields two as
 *  well, distinguished by `id` and counted by `group_size` (the list collapses those). */
export interface ConceptListItem {
	id: number;
	taxonomy: string;
	name: string;
	display_name: string | null;
	description: string | null;
	version: number | null;
	sources: string[];
	types: string[];
	/** True when the concept's single source is an auto-generated (read-only) config. */
	read_only: boolean;
	/** Id of the taxonomy entry this row is. */
	pointer_id: number;
	/** "alias" for a secondary name; null for the concept's primary name here. */
	relationship: string | null;
	/** "user" or "import" — who maintains this name. */
	origin: string;
	/** How many concepts this identifier names in this taxonomy, as of the query date. */
	group_size: number;
	/** Set when this *name* was retired (only listed with `include_deprecated`). */
	deprecated_at: string | null;
	/** Set when the *concept* itself was retired. */
	concept_deprecated_at: string | null;
	/** The concept replacing a retired one, resolved to the end of the chain. */
	successor_id: number | null;
}

/** One row of `/concepts/table`: a list row plus the columns the table can show. */
export interface ConceptTableRow extends ConceptListItem {
	/** S/M/L over the documentation's character count; null when nothing is written. The
	 *  count itself is deliberately not served. */
	doc_size: "S" | "M" | "L" | null;
	doc_status: string | null;
	/** The opening of the clinical description, one line, cut to at most 120 characters. The
	 *  full documentation text is never served per row. */
	doc_clinical_excerpt: string | null;
	/** How often the concept has been read, by anyone. */
	usage_reads: number;
	/** How often the calling user has read it — their own data. */
	my_reads: number;
	/** Distinct readers; admin-only, null for everybody else. */
	usage_users: number | null;
	last_edited_at: string | null;
	last_edited_by: string | null;
	names_count: number;
}

/** A selectable value of a filter control, with how many rows carry it. */
export interface ConceptTableFacet {
	value: string;
	count: number;
}

/** One page of `/concepts/table`, plus what the controls around it need. */
export interface ConceptTablePage {
	rows: ConceptTableRow[];
	total: number;
	page: number;
	page_size: number;
	pages: number;
	statuses: ConceptTableFacet[];
	sources: ConceptTableFacet[];
	types: ConceptTableFacet[];
	/** Every matching concept id, when `include_ids` was asked for; else null. */
	ids: number[] | null;
	/** Columns the requested as-of date lens cannot move (usage, documentation, status). */
	degraded: string[];
}

/** One taxonomy entry: an identifier pointing at a concept over a time window. Retiring a name
 *  stamps `deprecated_at` — the row itself is never edited or deleted, which is what keeps an
 *  identifier that once resolved resolving. */
export interface PointerInfo {
	id: number;
	identifier: string;
	display_name: string | null;
	/** "alias" for a secondary name; null for the concept's primary name in that taxonomy. */
	relationship: string | null;
	/** "user" or "import" — who maintains this name. */
	origin: string;
	created_at: string | null;
	deprecated_at: string | null;
}

/** A concept's name within one taxonomy, as the detail payload lists it. Includes retired
 *  names, flagged by `deprecated_at` — a renamed concept's old name is exactly what a reader
 *  arriving from an old link needs explained. */
export interface TaxonomyName extends PointerInfo {
	taxonomy: string;
}

/** A pointer as the write endpoints return it. */
export interface Pointer extends PointerInfo {
	taxonomy: string;
	concept_id: number;
}

export interface CriticalWarning {
	type: string;
	corrected_in_version: number | null;
	message: string | null;
}

export interface VersionInfo {
	source_version: number | null;
	type: string;
	/** Auto-generated (medication/laboratory) config: not editable or versioned here. */
	read_only: boolean;
	change_type: string;
	message: string | null;
	author: string | null;
	committed_at: string;
	status: string;
	warning: CriticalWarning | null;
}

/** A data file a source definition reads — a mapping table, a pickled model. Files live in the
 *  **source's** library and are versioned there; a config references one by uuid, spelled
 *  `getfile("<uuid>")` in the snippet. What a config version carries is therefore a pin: this
 *  uuid at this `version_no`, which is what keeps an old version reproducible. */
export interface SourceFile {
	uuid: string;
	path: string;
	size: number;
	sha256: string;
	media_type: string;
	/** The file version this config version is pinned to. */
	version_no: number;
}

/** One row of a source's file library (`GET /sources/{key}/files`): the file as it stands now,
 *  plus how many published configs read it — which is exactly how many concepts a new upload
 *  would publish a version of. */
export interface SourceFileRecord {
	uuid: string;
	path: string;
	size: number;
	sha256: string;
	media_type: string;
	/** The current (latest) version of the file. */
	version_no: number;
	updated_at: string;
	updated_by: string | null;
	/** How many concepts' current published configs reference this file. */
	referenced_by: number;
}

/** One entry of a file's version history. */
export interface SourceFileVersion {
	version_no: number;
	/** The path this version was uploaded under — a new version may rename the file, so it is
	 *  not necessarily the file's current path. Null for versions from before it was recorded. */
	path: string | null;
	sha256: string;
	size: number;
	author: string | null;
	message: string | null;
	created_at: string;
}

/** `GET /sources/{key}/files/{uuid}`: the library row plus every version of it. */
export interface SourceFileDetail extends SourceFileRecord {
	versions: SourceFileVersion[];
}

/** A concept whose **current published** config references a file
 *  (`GET /sources/{key}/files/{uuid}/references`) — i.e. one that a new upload would publish a
 *  new version of. */
export interface FileReference {
	concept_id: number;
	taxonomy: string | null;
	name: string | null;
	display_name: string | null;
}

/** What `POST /sources/{key}/files` reports back: the version it minted (or `unchanged`, when
 *  the bytes were identical and nothing happened) and the concepts the cascade published. */
export interface FileUploadResult {
	uuid: string;
	/** The file's path *after* the upload — a new version may have renamed it. */
	path: string;
	version_no: number;
	unchanged: boolean;
	bumped: { concept_id: number; name: string | null; version_no: number }[];
}

/** A file a draft pinned that has since moved on: the draft still reads `pinned_version` while
 *  the library is at `current_version`. Publishing the draft pins the current one. */
export interface DraftFileChange {
	uuid: string;
	path: string | null;
	pinned_version: number | null;
	current_version: number | null;
}

/** One source's current config block inside `GET /concept/{tax}/{name}`. */
export interface SourceConfig {
	json: Record<string, unknown>;
	py: string | null;
	/** The definition *has* a snippet, but it was withheld for want of `can_read_detail`.
	 *  Distinct from `py === null` with this false, which means there simply is no code. */
	py_locked?: boolean;
	/** Always present; empty when this version has no attachments. */
	files: SourceFile[];
	version_info: VersionInfo;
}

export interface ConceptDetail {
	id: number;
	/** The pointer the concept was reached through; null only for a concept that holds no
	 *  taxonomy entry at all. */
	taxonomy: string | null;
	name: string | null;
	display_name: string | null;
	description: string | null;
	names: TaxonomyName[];
	/** The taxonomy entry this response resolved through — carries the window the name was
	 *  (or is) valid in, so a retired name can be explained rather than just 404ing. */
	pointer: PointerInfo | null;
	/** Set when the concept itself was retired. */
	deprecated_at: string | null;
	/** The concept replacing a retired one, at the end of the successor chain. */
	successor_id: number | null;
	version: number | null;
	requested: { v: number | null; date: string | null; draft: number | null };
	sources: Record<string, SourceConfig>;
	/* Clinical documentation (editable in-app; refreshed from the sidecar's Notion export
	 * on reimport, when that sync is configured). */
	doc_clinical: string | null;
	doc_implementation: string | null;
	doc_caveats: string | null;
	doc_status: string | null;
	notion_url: string | null;
}

export interface HistoryRow {
	version: number | null;
	source: string | null;
	change_type: string;
	message: string | null;
	committed_at: string;
}

export interface Draft {
	id: number;
	concept_id: number;
	source_id: number;
	source: string | null;
	type: string;
	json: Record<string, unknown>;
	py: string | null;
	/** As on `SourceConfig`: the draft has a snippet that `can_read_detail` would show. */
	py_locked?: boolean;
	status: string;
	version_no: number | null;
	change_type: string;
	message: string | null;
	validation_status: string | null;
	created_by: number | null;
	created_at: string;
	/** Files this draft pinned whose library version has moved on since. Drafts are never
	 *  cascaded into (only published configs are), so this is how the drift becomes visible. */
	files_changed_since_draft?: DraftFileChange[];
	/** `getfile()` uuids in the snippet that name no file in this source — a publish blocker. */
	unresolved_files?: string[];
}

/** One unpublished draft in the cross-concept review queue (`GET /drafts`). Carries the
 *  concept named the way a reviewer recognises it, so /review renders and links without a
 *  concept read per row — `concept_id` is what pins the right member when `name` names a
 *  group. */
/** The navigation badge counts (`GET /auth/pending-counts`). A field is null when the signed-in
 *  user may not see that queue — which is not the same as the queue being empty. */
export interface PendingCounts {
	review: number | null;
	pending_users: number | null;
}

export interface OpenDraft {
	id: number;
	concept_id: number;
	taxonomy: string | null;
	name: string | null;
	display_name: string | null;
	/** Set when the *concept* was retired while this draft was still open. */
	concept_deprecated_at: string | null;
	source: string | null;
	type: string;
	change_type: string;
	message: string | null;
	validation_status: string | null;
	author: string | null;
	created_at: string;
}

/** One pointer that matched a concept search (`GET /concepts/search`). */
export interface ConceptSearchMatch {
	taxonomy: string;
	identifier: string;
	display_name: string | null;
	deprecated_at: string | null;
}

/** One concept the search found, with every pointer of it that matched — so a picker can show
 *  what else the concept is called before it is chosen. */
export interface ConceptSearchResult {
	concept_id: number;
	description: string | null;
	deprecated_at: string | null;
	matches: ConceptSearchMatch[];
}

/** The concept a deprecation request is about, named the way a reviewer recognises it. */
export interface DeprecationConcept {
	id: number;
	taxonomy: string | null;
	name: string | null;
	display_name: string | null;
}

/** One row of the deprecation review queue (`GET /deprecation-requests`). */
/** The name a deprecation request was filed against. */
export interface DeprecationPointer {
	id: number;
	taxonomy: string | null;
	name: string | null;
	display_name: string | null;
	deprecated_at: string | null;
}

export interface DeprecationRequest {
	id: number;
	concept: DeprecationConcept;
	/** The name this was filed against; null = the concept as a whole. */
	pointer: DeprecationPointer | null;
	/** What approving retires: just `pointer`, or the concept itself. */
	retires: "name" | "concept";
	reason: string | null;
	successor: DeprecationConcept | null;
	status: "pending" | "approved" | "rejected";
	requested_by: string | null;
	resolved_by: string | null;
	resolved_at: string | null;
	created_at: string;
}

/** The structured 409 body a name-taken write comes back with: the concept(s) already holding
 *  the identifier, which the caller confirms forming a group with. */
export interface NameExistsConflict {
	taxonomy: string;
	name: string;
	members: { id: number; name: string; display_name: string | null; description?: string | null }[];
}

/** A JSON-Schema node (draft 2020-12), loosely typed for the recursive form generator. */
export interface JsonSchema {
	$id?: string;
	$ref?: string;
	type?: string | string[];
	title?: string;
	description?: string;
	const?: unknown;
	enum?: unknown[];
	pattern?: string;
	format?: string;
	required?: string[];
	properties?: Record<string, JsonSchema>;
	additionalProperties?: boolean | JsonSchema;
	items?: JsonSchema;
	uniqueItems?: boolean;
	oneOf?: JsonSchema[];
	anyOf?: JsonSchema[];
	allOf?: JsonSchema[];
	[key: string]: unknown;
}

/** `GET /schemas` → { source: { type: schema } }. */
export type SchemaIndex = Record<string, Record<string, JsonSchema>>;

