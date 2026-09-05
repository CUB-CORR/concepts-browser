from collections import Counter
from datetime import datetime
from typing import Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ConceptSelector(BaseModel):
    """Mutually-exclusive selectors for which state of a concept to return.

    Bound from the query string; each field accepts a long and a short spelling.
    """
    v: int | None = Field(
        None,
        validation_alias=AliasChoices("v", "version"),
        description="published version number (alias: version)",
    )
    date: datetime | None = Field(
        None,
        validation_alias=AliasChoices("date", "d"),
        description="state active at this timestamp (alias: d)",
    )
    draft: int | None = Field(
        None, description="return a specific draft using its id"
    )


class ConceptFileSelector(ConceptSelector):
    """The concept selectors plus the one thing a file download needs on top: which source's
    attachment is meant, for the rare concept whose sources attach the same relative path.
    A subclass rather than a second parameter because FastAPI binds exactly one Pydantic model
    per query string — an additional plain `Query` param alongside one is not bound at all.
    """
    source: str | None = Field(
        None, description="source key, when several sources attach this path"
    )


class ConceptListQuery(BaseModel):
    """Query params for the concept list: taxonomy scope + an optional as-of date."""
    taxonomy: str | None = Field(
        None, description="only concepts named in this taxonomy; names come from it"
    )
    date: datetime | None = Field(
        None,
        validation_alias=AliasChoices("date", "d"),
        description="compute version/sources/types as of this timestamp (alias: d)",
    )
    include_deprecated: bool = Field(
        False, description="also list retired names, flagged via `deprecated_at`"
    )


# The sortable columns of the concepts table, and the sentinel that selects the "no status"
# facet (doc_status IS NULL). Both are spelled out here so the app, the docs and the API agree.
ConceptTableSort = Literal[
    "relevance",
    "usage",
    "mine",
    "documentation",
    "name",
    "display_name",
    "status",
    "edited",
    "editor",
    "version",
    "names",
    "id",
]
STATUS_NONE = "(none)"


class ConceptTableQuery(BaseModel):
    """Query params for the paginated, server-sorted concepts table.

    Everything the table does happens here rather than in the browser: the taxonomy holds
    thousands of names, so sorting, filtering, searching and paging all have to be one SQL
    query over the whole set — a page of rows sorted client-side would sort the page, not the
    table.
    """
    taxonomy: str | None = Field(
        None, description="only concepts named in this taxonomy; names come from it"
    )
    date: datetime | None = Field(
        None,
        validation_alias=AliasChoices("date", "d"),
        description="compute version/sources/types/last-edited as of this timestamp (alias: d)",
    )
    include_deprecated: bool = Field(
        False, description="also list retired names, flagged via `deprecated_at`"
    )
    q: str | None = Field(
        None,
        description="matched against identifier, display name, description and the three "
                    "documentation fields. Names are matched separator-insensitively "
                    "(`blood sodium` finds `lab_blood_sodium`) and, from three characters up, "
                    "also within a small per-word typo budget",
    )
    status: list[str] = Field(
        default_factory=list,
        description=f"keep only these `doc_status` values; repeatable. `{STATUS_NONE}` selects "
                    "the concepts carrying no status at all",
    )
    source: list[str] = Field(
        default_factory=list,
        description="keep only concepts a listed source has a published config for; repeatable",
    )
    type: list[str] = Field(
        default_factory=list,
        description="keep only concepts whose current configs include one of these types",
    )
    configured: Literal["all", "configured", "unconfigured"] = Field(
        "all", description="whether the concept has any published config at all"
    )
    sort: ConceptTableSort | None = Field(
        None,
        description="sort key; 'mine' is the caller's own read count. Omitted means relevance "
                    "when `q` is set and most-used-first otherwise; naming a column overrides "
                    "that and relevance becomes the first tiebreaker under it. 'relevance' "
                    "ignores `dir` — best matches always come first",
    )
    dir: Literal["asc", "desc"] = Field("desc", description="sort direction")
    page: int = Field(1, ge=1, description="1-based page number")
    page_size: int = Field(50, ge=1, le=200, description="rows per page")
    include_ids: bool = Field(
        False,
        description="also return every matching concept id (not just this page's) — what the "
                    "export needs to reproduce the filtered set",
    )


class ConceptSearchQuery(BaseModel):
    """Query params for the concept picker's search."""
    q: str = Field(min_length=1, description="substring matched against identifier/display name")
    limit: int = Field(20, gt=0, le=100, description="maximum number of concepts returned")


class ConceptExportRequest(BaseModel):
    """Body for the admin concepts export (CSV/XLSX download).

    `ids` carries the concept ids of the app's *filtered* list so the file matches exactly
    what the admin sees; omitted = every concept named in the taxonomy. `date` is the same
    as-of lens the list takes, so an export under the date filter reproduces that state.
    """
    taxonomy: str | None = Field(
        None, description="taxonomy scope; defaults to the server's default taxonomy"
    )
    format: Literal["csv", "xlsx"] = "csv"
    ids: list[int] | None = Field(
        None, description="restrict to these concept ids (the filtered list); None = all"
    )
    include_configs: bool = Field(
        False, description="add the latest published json/py per source as extra columns"
    )
    date: datetime | None = Field(
        None, description="compute version/sources/types/configs as of this timestamp"
    )


# --- Public read responses (client-facing docs) -----------------------------
# These mirror the dicts returned by the concept/reference read endpoints so the
# generated OpenAPI schema documents response bodies, not just query params.
# Keep every returned key represented here: fields absent from the model are
# dropped from the serialized response.


class ConceptListItem(BaseModel):
    """One **pointer** as returned by the concept list: an identifier, and the concept it names.

    A concept named twice in the taxonomy (an alias) yields two rows; an identifier naming two
    concepts (a group) also yields two, distinguished by `id` and counted by `group_size`. The
    app collapses `group_size > 1` rows into one display row per identifier.
    """
    id: int = Field(description="concept id")
    taxonomy: str
    name: str
    display_name: str | None = None
    description: str | None = None
    version: int | None = Field(None, description="latest published version, as-of the query date")
    sources: list[str] = Field(default_factory=list, description="source keys with a published config")
    types: list[str] = Field(default_factory=list, description="config types present across sources")
    read_only: bool = Field(
        False, description="true when the concept's only source is auto-generated (not editable)"
    )
    pointer_id: int = Field(description="id of the taxonomy entry this row is")
    relationship: str | None = Field(None, description="'alias' for a secondary name; else null")
    origin: str = Field("user", description="'user' or 'import' — who maintains this name")
    group_size: int = Field(
        1, description="how many concepts this identifier names in this taxonomy, as-of the date"
    )
    deprecated_at: datetime | None = Field(
        None, description="set when this *name* was retired (only listed on request)"
    )
    concept_deprecated_at: datetime | None = Field(
        None, description="set when the *concept* itself was retired"
    )
    successor_id: int | None = Field(
        None, description="the concept that replaces a retired one, resolved to the end of the chain"
    )


class ConceptTableRow(ConceptListItem):
    """One row of the concepts table: a list row plus the columns the table can show.

    Nothing here identifies a reader. `usage_reads` is how often the concept is read by
    anyone, `my_reads` the caller's own share (their own data, always theirs to see) and
    `usage_users` — how many distinct people — is admin-only and null for everybody else,
    the same rule `/usage/concepts` applies.
    """
    doc_size: Literal["S", "M", "L"] | None = Field(
        None, description="S/M/L bucket over the documentation's character count; null = none"
    )
    doc_status: str | None = Field(None, description="the concept's workflow status label")
    doc_clinical_excerpt: str | None = Field(
        None,
        description="the opening of the clinical description, flattened to one line and cut to "
                    "at most 120 characters; the full text is never served per row",
    )
    usage_reads: int = Field(
        0,
        description="how often this concept has been pulled from the API, by anyone; reads the "
                    "web app makes while somebody browses it do not count",
    )
    my_reads: int = Field(0, description="how often the calling user has read it from the API")
    usage_users: int | None = Field(
        None, description="distinct readers; admin-only, else null"
    )
    last_edited_at: datetime | None = Field(
        None, description="when the latest published version (as-of the query date) was created"
    )
    last_edited_by: str | None = Field(
        None, description="username of that version's author; null for imported rows"
    )
    names_count: int = Field(
        1, description="how many names the concept holds across all taxonomies, as-of the date"
    )


class ConceptTableFacet(BaseModel):
    """One selectable value of a filter control, with how many rows carry it."""
    value: str = Field(description=f"the value; `{STATUS_NONE}` is the status filter's unset bucket")
    count: int


class ConceptTablePage(BaseModel):
    """One page of the concepts table, plus what the controls around it need.

    `degraded` names the columns whose value is **not** what the as-of date asks for. Usage
    counts and the documentation fields are concept-level and carry no history, so under a
    `date` lens they are today's values on a row that is otherwise historical. The table says
    so rather than quietly implying the past was measured.
    """
    rows: list[ConceptTableRow]
    total: int = Field(description="matching rows across all pages")
    page: int
    page_size: int
    pages: int = Field(description="number of pages at this page size; 0 when nothing matches")
    statuses: list[ConceptTableFacet] = Field(
        default_factory=list,
        description="the status values available under the current search, with counts; "
                    "computed ignoring the status filter itself so it stays multi-selectable",
    )
    sources: list[ConceptTableFacet] = Field(
        default_factory=list, description="source keys present, with counts, like `statuses`"
    )
    types: list[ConceptTableFacet] = Field(
        default_factory=list, description="config types present, with counts, like `statuses`"
    )
    ids: list[int] | None = Field(
        None, description="every matching concept id, when `include_ids` was asked for"
    )
    degraded: list[str] = Field(
        default_factory=list, description="columns not computable under the requested date lens"
    )


class PointerInfo(BaseModel):
    """One taxonomy entry — an identifier pointing at a concept over a time window."""
    id: int
    identifier: str
    display_name: str | None = None
    relationship: str | None = Field(None, description="'alias' for a secondary name; else null")
    origin: str = Field("user", description="'user' or 'import' — who maintains this name")
    created_at: datetime | None = None
    deprecated_at: datetime | None = Field(None, description="set once the name was retired")


class TaxonomyName(PointerInfo):
    """A concept's name within one taxonomy, as the detail page lists it."""
    taxonomy: str


class CriticalWarning(BaseModel):
    type: str = "critical_superseded"
    corrected_in_version: int
    message: str | None = None


class SourceVersionInfo(BaseModel):
    source_version: int | None = None
    type: str | None = None
    read_only: bool = False
    change_type: str | None = None
    message: str | None = None
    author: str | None = None
    committed_at: datetime | None = None
    status: str | None = None
    warning: CriticalWarning | None = Field(
        None, description="present when a later critical version supersedes this one"
    )


class SourceFile(BaseModel):
    """One data file this version of a definition reads, at the version of it that was pinned.

    Files live in the **source's** library and are versioned there; a snippet names one by
    `uuid` (`getfile("<uuid>")`) and a config version pins it at `version_no`. Together these
    fields are the manifest a client pre-downloads from before running the snippet: the uuid it
    will be asked for, the version this definition means, the digest to verify, and the `path`
    to lay the bytes out at.
    """
    uuid: str = Field(description="the file's stable id — what `getfile(\"…\")` names")
    path: str = Field(description="relative path to lay the file out at, e.g. 'pc/mapping.csv'")
    version_no: int = Field(description="the file version this definition version pins")
    size: int = Field(description="size in bytes")
    sha256: str = Field(description="sha256 of these bytes")
    media_type: str = "application/octet-stream"
    url: str = Field(description="GET path serving these bytes at the version served here")


class SourceFileRecord(BaseModel):
    """One row of a source's file library, as it stands now."""
    uuid: str
    path: str
    description: str | None = None
    size: int
    sha256: str
    media_type: str = "application/octet-stream"
    version_no: int = Field(description="the file's current (latest) version")
    updated_at: datetime = Field(description="when the current version was uploaded")
    updated_by: str | None = Field(None, description="who uploaded the current version")
    referenced_by: int = Field(
        description="how many concepts' current published configs read this file"
    )


class SourceFileVersionOut(BaseModel):
    """One entry of a file's version history."""
    version_no: int
    path: str | None = Field(
        None,
        description=(
            "the path this version was uploaded under — a new version may rename the file, so "
            "this is not necessarily the file's current path; null for versions written "
            "before the name was recorded"
        ),
    )
    sha256: str
    size: int
    author: str | None = None
    message: str | None = None
    created_at: datetime


class SourceFileDetail(SourceFileRecord):
    """A library row plus every version the file has had, newest first."""
    versions: list[SourceFileVersionOut] = Field(default_factory=list)


class FileReference(BaseModel):
    """A concept whose current published config reads a file — one a new upload would publish
    a new version of, and one a retire is refused for."""
    concept_id: int
    taxonomy: str | None = None
    name: str | None = None
    display_name: str | None = None


class BumpedConcept(BaseModel):
    """One concept version an upload published."""
    concept_id: int
    name: str | None = None
    version_no: int


class FileUploadResult(BaseModel):
    """What an upload did: the version it landed on and the concept versions it published."""
    uuid: str
    path: str
    version_no: int
    unchanged: bool = Field(
        description="true when the bytes matched the current version: nothing was written"
    )
    bumped: list[BumpedConcept] = Field(
        default_factory=list, description="concepts this upload published a new version of"
    )


class SourceConfig(BaseModel):
    """The published definition for one source of a concept."""
    json_: dict | None = Field(None, alias="json", description="the source's JSON definition")
    py: str | None = Field(None, description="optional Python snippet")
    py_locked: bool = Field(
        False,
        description=(
            "true when this definition has a Python snippet that was withheld because the "
            "caller lacks `can_read_detail`. Never conflate a null `py` with 'no code': check "
            "this flag and fail, rather than resolving the concept without its snippet. The "
            "response also carries the `X-Concepts-Locked: can_read_detail` header."
        ),
    )
    files: list[SourceFile] = Field(
        default_factory=list, description="data files this version's `py` needs"
    )
    version_info: SourceVersionInfo

    model_config = ConfigDict(populate_by_name=True)


class RequestedSelectors(BaseModel):
    """Echo of the selectors the caller asked for (see query params)."""
    v: int | None = None
    date: datetime | None = None
    draft: int | None = None


class ConceptDetail(BaseModel):
    """A single concept with its per-source definitions.

    `taxonomy`/`name` are the pointer the concept was reached through; null only for a
    concept that holds no taxonomy entry at all.
    """
    id: int
    taxonomy: str | None = None
    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    names: list[TaxonomyName] = Field(default_factory=list, description="this concept's names in every taxonomy")
    pointer: PointerInfo | None = Field(
        None, description="the taxonomy entry this response was resolved through"
    )
    deprecated_at: datetime | None = Field(
        None, description="set when the concept itself was retired"
    )
    successor_id: int | None = Field(
        None, description="the concept that replaces a retired one, at the end of the chain"
    )
    version: int | None = Field(None, description="current (latest published) concept version")
    requested: RequestedSelectors
    sources: dict[str, SourceConfig] = Field(
        default_factory=dict, description="published definition keyed by source key"
    )
    # Clinical documentation, editable in the app and refreshed from the upstream Notion
    # export on reimport (see the documentation PATCH in routers/writes.py).
    doc_clinical: str | None = Field(None, description="clinical description")
    doc_implementation: str | None = Field(None, description="implementation description")
    doc_caveats: str | None = Field(None, description="known caveats")
    doc_status: str | None = Field(None, description="workflow status label")
    notion_url: str | None = Field(None, description="upstream documentation page, when one exists")


class DocumentationUpdate(BaseModel):
    """Partial update of a concept's documentation. Omitted fields keep their value; an
    explicit null clears one. Every text field needs `can_edit`; `doc_status` alone needs
    `can_publish`."""
    doc_clinical: str | None = None
    doc_implementation: str | None = None
    doc_caveats: str | None = None
    doc_status: str | None = None


class ConceptHistoryEntry(BaseModel):
    """One published version in a concept's history."""
    version: int | None = None
    source: str | None = None
    change_type: str | None = None
    message: str | None = None
    committed_at: datetime | None = None


class TaxonomyOut(BaseModel):
    key: str
    name: str | None = None
    version: str | None = None


class SourceOut(BaseModel):
    key: str
    nicename: str | None = None
    supported_types: list[str] = Field(default_factory=list)
    schema_governed: bool = False


class SourceTypesOut(BaseModel):
    source: str
    supported_types: list[str] = Field(default_factory=list)
    schema_governed: bool = False


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str | None = None
    capabilities: list[str] = []
    is_active: bool = True


class PendingCountsOut(BaseModel):
    """What is waiting for the signed-in user, as the navigation badges it.

    A field is `None` — not `0` — when the caller may not see that queue at all: nothing to
    show is a different statement from no permission to look, and only the first is a badge.
    """
    review: int | None = Field(
        None, description="Open drafts + pending deprecation requests; null without can_publish"
    )
    pending_users: int | None = Field(
        None, description="Active users awaiting their first capability; null without can_admin"
    )


class ProfileOut(BaseModel):
    """A user's own (or, for admins, any user's) profile: account state, capabilities, and the
    full directory attribute snapshot for LDAP users. `ldap_profile` maps attribute name to a
    list of string values; None for local/bootstrap users."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str | None = None
    capabilities: list[str] = []
    is_active: bool = True
    is_ldap: bool
    created_at: datetime
    ldap_profile: dict | None = None


class AdminUserOut(BaseModel):
    """A user as shown in the admin user-management page."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str | None = None
    capabilities: list[str] = []
    is_active: bool = True
    is_ldap: bool  # True for LDAP-provisioned users (read from User.is_ldap)
    created_at: datetime


def _validate_capabilities(v):
    if v is None:
        return v
    from .security import ALL_CAPABILITIES

    unknown = sorted(set(v) - set(ALL_CAPABILITIES))
    if unknown:
        raise ValueError(f"unknown capabilities: {unknown}")
    return sorted(set(v))  # dedupe, stable order


class AdminUserUpdate(BaseModel):
    """Partial update for a user from the admin page. Omitted fields are left unchanged."""
    capabilities: list[str] | None = None
    is_active: bool | None = None

    _known_caps = field_validator("capabilities")(_validate_capabilities)


class DirectoryEntry(BaseModel):
    """One person from an admin directory search (`GET /admin/directory`), for proactive
    provisioning. `user_id` is set when this person is already in our DB (keyed on the stable
    LDAP guid), so the UI can show "already added" instead of offering to add them again."""
    ldap_guid: str
    username: str  # the directory uid
    display_name: str | None = None
    user_id: int | None = None


class ProvisionUserRequest(BaseModel):
    """Pre-provision an LDAP user the admin found in the directory, granting capabilities up
    front. Only the `username` (uid) is trusted from the client — the server re-resolves it
    against the directory to read the authoritative guid/display name/profile."""
    username: str
    capabilities: list[str] = []

    _known_caps = field_validator("capabilities")(_validate_capabilities)


class ApiKeyOut(BaseModel):
    """An API key as shown on the owner's key-management page — never includes the secret."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    key_prefix: str
    scopes: list[str] = []
    created_at: datetime
    expires_at: datetime | None = None
    revoked: bool = False
    last_used_at: datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    """Response to key creation: the full plaintext key, shown exactly once."""
    key: str


class ApiKeyCreate(BaseModel):
    """Mint an API key. `scopes` must be a subset of the owner's current capabilities (enforced
    server-side). `expires_in_days` None ⇒ the key never expires."""
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = []
    expires_in_days: int | None = Field(default=None, gt=0, le=3650)

    _known_caps = field_validator("scopes")(_validate_capabilities)


class ConceptCreate(BaseModel):
    # `name` is registered as the concept's identifier under `taxonomy` (default corr_v1);
    # `display_name` is stored on that taxonomy entry, not on the concept itself.
    name: str
    taxonomy: str | None = None
    display_name: str | None = None
    description: str | None = None
    # A name already active in the taxonomy is a 409 unless this says the caller means to
    # create a second concept under it (a group) — see PointerCreate.
    confirm_group: bool = False


class DraftCreate(BaseModel):
    # accept "json" / "py" in the request body, expose as definition / code internally
    model_config = ConfigDict(populate_by_name=True)
    source: str
    # Default (empty=False): copy type/json/py from the latest published version of this
    # (concept, source); type is inherited and cannot change. `json`/`py` are optional and
    # override the copied values when given.
    # empty=True: start blank — nothing is copied, and `type` + `json` are required. This
    # is the only way to change a variable's type (the schema differs per type).
    empty: bool = False
    type: str | None = None
    definition: dict | None = Field(default=None, alias="json")
    code: str | None = Field(default=None, alias="py")
    message: str | None = None
    change_type: str = "improvement"


class DraftUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: str | None = None
    definition: dict | None = Field(default=None, alias="json")
    code: str | None = Field(default=None, alias="py")
    message: str | None = None
    change_type: str | None = None


class PublishRequest(BaseModel):
    change_type: str | None = None
    message: str | None = None
    corrects_since_version_no: int | None = None
    # Email everyone who has used this concept, plus the leads of the projects it was used
    # from. Off unless the publisher asks for it.
    notify: bool = False


class OpenDraftOut(BaseModel):
    """One unpublished draft in the cross-concept review queue (`GET /drafts`).

    Carries the concept named the way a reviewer recognises it, plus everything the queue row
    itself renders — so listing the queue costs one call rather than one concept read per row.
    `taxonomy` + `name` + `concept_id` are what a link back to the draft is built from: the
    page is addressed by name, and the id pins which member of a group is meant.
    """
    id: int
    concept_id: int
    taxonomy: str | None = Field(
        None, description="taxonomy of `name`; null for a concept holding no name at all"
    )
    name: str | None = None
    display_name: str | None = None
    concept_deprecated_at: datetime | None = Field(
        None, description="set when the concept itself was retired"
    )
    source: str | None = None
    type: str
    change_type: str
    message: str | None = None
    validation_status: str | None = None
    author: str | None = Field(None, description="username of whoever started the draft")
    created_at: datetime


# --- taxonomy pointers ----------------------------------------------------------------------


class PointerCreate(BaseModel):
    """Point an identifier at a concept.

    Refused with 409 when the identifier is already active in the taxonomy for a *different*
    concept, unless `confirm_group` says the caller means to form a group (one name, several
    concepts) — and always when this concept already holds it.
    """
    taxonomy: str | None = Field(
        None, description="taxonomy the identifier belongs to; defaults to the server's default"
    )
    identifier: str = Field(min_length=1, max_length=128)
    display_name: str | None = None
    relationship: str | None = Field(
        None, description="'alias' to badge this as a secondary name; else null"
    )
    confirm_group: bool = Field(
        False, description="accept that this identifier will name more than one concept"
    )


class PointerOut(PointerInfo):
    """A pointer as the write endpoints return it."""
    taxonomy: str
    concept_id: int


# --- retiring a concept ---------------------------------------------------------------------


class DeprecationRequestIn(BaseModel):
    """Ask for a name — or the concept behind it — to be retired, optionally naming what
    replaces it."""
    reason: str | None = None
    successor_id: int | None = Field(
        None, description="concept id that supersedes this one, when there is one"
    )
    pointer_id: int | None = Field(
        None,
        description=(
            "the concept's pointer (name) this is filed against. Approving retires only that "
            "name while the concept still has other live ones; omit it to ask for the whole "
            "concept"
        ),
    )


class DeprecationDecision(BaseModel):
    """A reviewer's answer. On approval `successor_id` overrides what the request suggested."""
    successor_id: int | None = None


class DeprecationConcept(BaseModel):
    """The concept a request is about, named the way a reviewer recognises it."""
    id: int
    taxonomy: str | None = None
    name: str | None = None
    display_name: str | None = None


class DeprecationPointer(BaseModel):
    """The name a request was filed against."""
    id: int
    taxonomy: str | None = None
    name: str | None = None
    display_name: str | None = None
    deprecated_at: datetime | None = Field(
        None, description="set once this name was retired"
    )


class DeprecationRequestOut(BaseModel):
    """One deprecation request in the review queue."""
    id: int
    concept: DeprecationConcept
    pointer: DeprecationPointer | None = Field(
        None, description="the name this was filed against; null = the concept as a whole"
    )
    retires: str = Field(
        description=(
            "'name' when approving closes only `pointer`'s window and leaves the concept live "
            "under its other names, 'concept' when it retires the concept itself. Answered as "
            "of the decision for a resolved request, and as of now for an open one"
        )
    )
    reason: str | None = None
    successor: DeprecationConcept | None = None
    status: str = Field(description="'pending', 'approved' or 'rejected'")
    requested_by: str | None = Field(None, description="username of the requester")
    resolved_by: str | None = Field(None, description="username of the reviewer")
    resolved_at: datetime | None = None
    created_at: datetime


# --- concept search (pickers) ---------------------------------------------------------------


class ConceptSearchMatch(BaseModel):
    """One pointer that matched the search term."""
    taxonomy: str
    identifier: str
    display_name: str | None = None
    deprecated_at: datetime | None = None


class ConceptSearchResult(BaseModel):
    """One concept the search found, with every pointer of it that matched."""
    concept_id: int
    description: str | None = None
    deprecated_at: datetime | None = Field(
        None, description="set when the concept itself was retired"
    )
    matches: list[ConceptSearchMatch] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    ea_id: str | None = None
    # Users placed in the project's `lead` field. The creator is always included, so this
    # may be empty. Every lead may edit the project.
    lead_ids: list[int] = []
    # The creating lead accepts the current CORR license. Required to create a usable project.
    accept_license: bool = False


class ProjectUpdate(BaseModel):
    """Partial update from the project page; omitted fields are left unchanged."""
    name: str | None = None
    description: str | None = None
    ea_id: str | None = None
    lead_ids: list[int] | None = None
    # Toggle completion: True stamps `completed_on`, False clears it.
    completed: bool | None = None
    # Re-accept the current license (used when the active version outran the approval).
    accept_license: bool | None = None
    # The study context: the PICO frame and the study team behind the project. Each is free
    # text; an explicit null clears one, and omitting it leaves it alone.
    pico_population: str | None = None
    pico_intervention: str | None = None
    pico_comparison: str | None = None
    pico_outcome: str | None = None
    study_team: str | None = None


# --- audit log ------------------------------------------------------------------------------

class AuditActor(BaseModel):
    """The user an audit row is attributed to. Absent on a failed login (no user resolved) —
    the attempted username is then in `detail.username`."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None = None


class AuditEventOut(BaseModel):
    """One row of the audit log, as the audit page renders it."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    event: str = Field(description="'login', 'api_call' or 'email'")
    # The caller — except on an `email` row, where it is the recipient.
    user: AuditActor | None = None
    auth_method: str | None = Field(None, description="'jwt' or 'api_key'")

    # The request. All NULL on an `email` row: mail is sent from a background task, not served.
    client_type: str | None = Field(
        None, description="'app' (our web app) or 'external' (an API client)"
    )
    method: str | None = None
    path: str | None = None
    query_string: str | None = None
    status_code: int | None = None

    # The email. Set only on an `email` row.
    email_kind: str | None = Field(None, description="which message, e.g. 'approval'")
    email_to: str | None = Field(None, description="null when the directory had no address")
    email_subject: str | None = None
    email_status: str | None = Field(None, description="'sent', 'failed' or 'skipped'")

    project_id: str | None = None
    project_name: str | None = None

    concept_id: int | None = None
    concept_name: str | None = None
    taxonomy: str | None = None
    concept_version: int | None = Field(None, description="the version actually served")

    ip_address: str | None = None
    user_agent: str | None = None
    detail: dict | None = Field(None, description="full request: path/query params, username")


class AuditPage(BaseModel):
    """A page of audit rows plus the total matching the filters (for the pager)."""
    items: list[AuditEventOut]
    total: int
    limit: int
    offset: int


class AuditFilterOptions(BaseModel):
    """The distinct values present in the log, to populate the filter dropdowns — so an admin
    only ever filters by something that actually has rows."""
    users: list[AuditActor]
    projects: list[dict]
    concepts: list[dict]


class UsageConceptRow(BaseModel):
    """One concept a user has read, as the usage list renders it."""
    concept_id: int
    name: str | None = Field(
        None, description="the name it was last read under; null if never resolved to one"
    )
    taxonomy: str | None = None
    reads: int
    first_used_at: datetime
    last_used_at: datetime
    versions: str | None = Field(
        None, description="distinct concept versions read, sorted (\"1, 3, 4\"); null if none was recorded"
    )


class UserUsageOut(BaseModel):
    """What one user has done with the API: when they were last active, and which concepts they
    have read. Derived from the audit log (see `api/usage.py`).

    Only the calls they made *themselves* count. Reads the web app performs on their behalf while
    they browse are the app's, not theirs, and are excluded throughout — including
    `last_active_at`."""

    user_id: int
    username: str
    display_name: str | None = None
    last_active_at: datetime | None = Field(
        None,
        description="their most recent API call of any kind, excluding what the web app did for "
                    "them; null if they never made one",
    )
    concepts_used: int = Field(description="distinct concepts read")
    total_reads: int
    concepts: list[UsageConceptRow]


class ConceptUsageRow(BaseModel):
    """How much one concept is used, for the 'most used' / 'most used by me' sorts.

    `users` — how many distinct people read it — is admin-only and null for everybody else: the
    aggregate is public within the app, but who is behind it is not. `my_*` is the caller's own
    share, which they may always see.
    """

    concept_id: int
    name: str | None = None
    taxonomy: str | None = None
    reads: int
    last_used_at: datetime
    users: int | None = Field(None, description="distinct readers; admin-only, else null")
    my_reads: int = 0
    my_last_used_at: datetime | None = None


class VariableUpsertRow(BaseModel):
    """One variable as an upstream generator hands it over.

    The same three things a dataset's files carry per variable — the definition, the Python
    snippet that computes it, the extra taxonomy names it is known by — for one name. Data
    file attachments are deliberately absent: those come from a staged tree, not a JSON body.
    """
    name: str = Field(min_length=1, description="the variable's name in the key taxonomy")
    type: str | None = Field(
        None,
        description="the config type; may equally be stated inside `definition`, but the two "
                    "must agree",
    )
    definition: dict = Field(
        description="the definition as stored and validated against the (source, type) schema. "
                    "Those schemas are closed, so it must carry nothing else — no provenance",
    )
    python: str | None = Field(None, description="the snippet computing this variable")
    pointers: dict[str, list[str]] | None = Field(
        None, description="{taxonomy key: [identifier, …]} the import maintains for it"
    )

    @property
    def effective_type(self) -> str | None:
        return self.type or self.definition.get("type")

    @model_validator(mode="after")
    def _one_type(self) -> "VariableUpsertRow":
        inside = self.definition.get("type")
        if self.type and inside and self.type != inside:
            raise ValueError(
                f"row {self.name!r} states type {self.type!r} beside the definition and "
                f"{inside!r} inside it"
            )
        return self


class VariableUpsertRequest(BaseModel):
    """A batch of variables posted for upsert (see POST /internal/variables/upsert)."""
    source: str | None = Field(None, description="source key; defaults to the import source")
    key_taxonomy: str | None = Field(
        None, description="taxonomy the names are resolved in; defaults to the configured one"
    )
    mode: Literal["partial", "complete"] = Field(
        "partial",
        description="`partial` (the default) says nothing about what is missing and the "
                    "missing-upstream report is not computed. `complete` says these rows are "
                    "everything the sender has for `complete_for_types`, so stored names of "
                    "those types that are absent here are reported — reported only, never acted on",
    )
    complete_for_types: list[str] = Field(
        default_factory=list, description="required (and non-empty) with mode=complete"
    )
    on_invalid: Literal["skip", "reject"] | None = Field(
        None,
        description="what to do with a row the schema turns away: `skip` it (the default in "
                    "partial mode, matching the file import) or `reject` the whole batch (the "
                    "default in complete mode)",
    )
    dry_run: bool = Field(False, description="apply everything, report it, write nothing")
    rows: list[VariableUpsertRow] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "VariableUpsertRequest":
        counts = Counter(r.name for r in self.rows)
        if repeated := sorted(n for n, c in counts.items() if c > 1):
            # Two rows for one name are a bug in the sender: keyed by name downstream, they
            # would silently collapse to whichever came last.
            raise ValueError(f"duplicate row name(s): {', '.join(repeated)}")
        if self.mode == "complete":
            if not self.complete_for_types:
                raise ValueError("mode=complete requires a non-empty complete_for_types")
            stray = sorted(
                {
                    f"{r.name} ({r.effective_type})"
                    for r in self.rows
                    if r.effective_type not in self.complete_for_types
                }
            )
            if stray:
                # Claiming completeness for types while carrying rows of other types makes the
                # claim unreadable — say which rows do not belong.
                raise ValueError(
                    "rows outside complete_for_types: " + ", ".join(stray)
                )
        if self.on_invalid is None:
            # In complete mode a skipped row is indistinguishable from a retired one in the
            # report, so silence is the wrong default there.
            self.on_invalid = "reject" if self.mode == "complete" else "skip"
        return self
