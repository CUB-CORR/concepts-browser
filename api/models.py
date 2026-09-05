import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    """Naive UTC — SQLite has no timezone type, so we keep everything naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------------------------
# The source-file identity derivation. **Shared with corr-vars**, which computes the same uuids
# offline to write `getfile("…")` into snippets before the file has ever been uploaded here, so
# it is a contract, not an implementation detail: changing either the namespace string or the
# seed format silently invalidates every reference somebody wrote against the other side.
#
#     SOURCE_FILE_NS = uuid.uuid5(uuid.NAMESPACE_URL, "concepts-browser/source-file")
#     file_uuid      = str(uuid.uuid5(SOURCE_FILE_NS, f"{source_key}/{initial_path}"))
#
# The seed is the source's key plus the path the file is **first created under** — the identity
# is minted once and then frozen. Two consequences worth stating out loud:
#
#   * A file **renamed through the API** (uploading a new version under a different name, see
#     `services.store_file_version`) keeps its uuid. The path moves, the identity does not, and
#     re-deriving from the new path would break every snippet naming it.
#   * A file **renamed in the staged refdata tree** arrives as a *new path* and is therefore a
#     *new file* with a new identity; the old library entry keeps existing, unreferenced, until
#     somebody retires it. Tree-managed files get their identity from their tree path, which is
#     exactly what makes it computable offline.
SOURCE_FILE_NS = uuid.uuid5(uuid.NAMESPACE_URL, "concepts-browser/source-file")


def source_file_uuid(source_key: str, initial_path: str) -> str:
    """The uuid a file gets when it is created at `initial_path` in source `source_key`.

    Deterministic on purpose: a fresh database, a second deployment and the offline corr-vars
    tooling all have to arrive at the same identifier, because snippets hardcode it.
    """
    return str(uuid.uuid5(SOURCE_FILE_NS, f"{source_key}/{initial_path}"))


# `AuditLog.event` kinds — the three subtabs of the audit page.
EVENT_LOGIN = "login"
EVENT_API_CALL = "api_call"
EVENT_EMAIL = "email"

# `AuditLog.client_type`: who made the request. `app` is our own web app (proved by the BFF's
# shared secret); `external` is a client that authenticated on its own and named a project.
# The distinction is what the usage rollup counts on — browsing a concept in the app is not
# API usage by the person doing the browsing (see api/usage.py).
CLIENT_APP = "app"
CLIENT_EXTERNAL = "external"

# What `concept_usage` was folded under. Bumping it makes the next boot throw the rollup away
# and refold the log under the current rule (see `_rebuild_usage_for_client_filter` in
# api/main.py) — necessary because the fold is incremental, so a changed rule would otherwise
# apply only to rows logged after it.
USAGE_FILTER_VERSION = 2

# `AuditLog.email_status`: what became of a message we tried to send.
#   sent    — the mail server accepted it
#   failed  — we tried and it did not go out (server down, rejected, misconfigured)
#   skipped — we never tried (mail disabled, or the directory has no address for the user)
EMAIL_SENT = "sent"
EMAIL_FAILED = "failed"
EMAIL_SKIPPED = "skipped"

# `ConceptTaxonomy.relationship`: the one value that means "this name is a secondary spelling
# of the concept in this taxonomy" — it resolves like any other, and the app badges it as an
# alias rather than as the name the concept is introduced by. Anything else (NULL) is primary.
RELATIONSHIP_ALIAS = "alias"

# `ConceptTaxonomy.origin`: who owns the pointer row. `user` pointers are created in the app
# and are never touched by the reference import; `import` pointers are the ones the importer
# maintains — it adds and deprecates them to follow upstream (see api/importer.py).
ORIGIN_USER = "user"
ORIGIN_IMPORT = "import"

# `DeprecationRequest.status`: an operator's request to retire a duplicate concept, and what
# a reviewer did with it.
DEPRECATION_PENDING = "pending"
DEPRECATION_APPROVED = "approved"
DEPRECATION_REJECTED = "rejected"

# `ConfigFileRef.origin`: what wrote the pin. `getfile` is the normal case — the reference was
# read out of the config's `py` snippet. `legacy` marks a row the migration carried over from
# the pre-uuid model, where a file was attached to a config directly and the snippet named it
# by a relative path; those pins are real, but no `getfile(...)` call in the snippet backs them.
FILE_REF_GETFILE = "getfile"
FILE_REF_LEGACY = "legacy"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Local bcrypt hash for the bootstrap/local admin. LDAP users have no local password
    # and store "" here (the local-login path treats an empty hash as "no local password").
    password_hash: Mapped[str] = mapped_column(Text)
    # Stable directory id (the configured LDAP guid attribute, base64) — the authoritative join key for
    # LDAP users. NULL for local users; `username`/`display_name` are refreshable labels.
    ldap_guid: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    # Full snapshot of the directory attributes from the login search (attr -> list of values),
    # refreshed on every login. NULL for local users. Shown read-only on the profile page.
    ldap_profile: Mapped[dict | None] = mapped_column(JSON)
    # e.g. ["can_edit", "can_publish", "can_admin"]
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    @property
    def is_ldap(self) -> bool:
        """An LDAP-provisioned user (has a directory guid) vs. a local/bootstrap user."""
        return self.ldap_guid is not None


class ApiKey(Base):
    """A long-lived bearer credential a user mints for automation/CI, as an alternative to a
    JWT. Presented as `Authorization: Bearer <key>`; only the sha256 hash is stored, so the
    plaintext is shown exactly once at creation. Effective capabilities at use time are
    `scopes ∩ owner.capabilities` (re-checked live), never more than the owner currently has.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Human label so the owner can tell their keys apart on the management page.
    name: Mapped[str] = mapped_column(String(128))
    # sha256 hex of the full key (high-entropy secret ⇒ a fast hash is fine, and lets us look
    # the key up by hash). Never the plaintext.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Leading chars of the key (e.g. "cak_ab12cd34") for display; the rest is unrecoverable.
    key_prefix: Mapped[str] = mapped_column(String(16))
    # Subset of the owner's capabilities this key may exercise (validated ⊆ owner at creation).
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Stamped on every authenticated request the key makes, so the owner can see usage.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)


class Project(Base):
    """A research project. Mostly self-contained: it gates external API queries (clients must
    name an existing, non-deleted project) and carries the CORR-license acceptance state."""

    __tablename__ = "projects"

    # UUID (not a sequential int) so project ids in URLs aren't enumerable.
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Unique + stable: external clients reference a project by this name on every query.
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Ethics-approval reference (Ethikvotum), e.g. "EA1/234/56". Optional.
    ea_id: Mapped[str | None] = mapped_column(String(128))
    # The study context: the PICO frame the project studies, one free-text column per element,
    # and the study team behind it (Projektteilnehmer). This describes the *study*, which is
    # what a project is — not any concept it reads. Edited on the project page by a lead or an
    # admin (see `_can_edit` in routers/projects.py); nothing outside the app writes it.
    pico_population: Mapped[str | None] = mapped_column(Text)
    pico_intervention: Mapped[str | None] = mapped_column(Text)
    pico_comparison: Mapped[str | None] = mapped_column(Text)
    pico_outcome: Mapped[str | None] = mapped_column(Text)
    study_team: Mapped[str | None] = mapped_column(Text)
    created_on: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # Set = completed (still usable for queries); set = soft-deleted (queries rejected).
    completed_on: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_on: Mapped[datetime | None] = mapped_column(DateTime)
    # 0 = license never accepted; otherwise the license `version` a lead accepted. When the
    # active license version is higher, the project must re-approve before it stays valid.
    license_approval: Mapped[int] = mapped_column(Integer, default=0)
    license_approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    license_approved_on: Mapped[datetime | None] = mapped_column(DateTime)


class ProjectLead(Base):
    """A user who leads a project. A project may have several leads; any of them may edit it
    (admins may edit any project). Replaces the separate lead/collaborator split."""

    __tablename__ = "project_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_lead"),
    )


class License(Base):
    """Versioned CORR license text. The active row (highest version) is the current license a
    project must accept; publishing a higher version re-prompts every project to re-approve."""

    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    created_on: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Base):
    """One row per auditable event: a login, an API call by an authenticated caller, or an
    email we sent (or tried to).

    Requests are written by the audit middleware (`api/audit.py`), which is why it can cover
    *every* route rather than only the concept reads. Routes enrich their own row by stashing
    context on `request.state` — the project gate sets `project_id`/`client_type`, `get_concept`
    sets the concept it resolved, `login` sets the event kind — and the middleware persists
    whatever is there once the response status is known.

    An `email` row is the exception: mail leaves in a background task, after the response, so
    `api/mailer.py` appends its own row (via `audit.record_email`) rather than going through the
    middleware. It is not an HTTP request, which is why the request columns below are nullable —
    an email has no method, path or client. `user_id` on such a row is the *recipient*, not a
    caller, so "was this person ever told?" is one filter away.

    `project_id` is set for external, project-scoped queries and NULL for internal web-app
    browsing. The concept columns are set only by the concept-read endpoints, which is what
    makes "who read which concept, at which version" filterable without parsing `path`.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    # "login" | "api_call" | "email".
    event: Mapped[str] = mapped_column(String(16), default=EVENT_API_CALL, index=True)
    # The caller on a request row; the *recipient* on an email row.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"), index=True)

    # --- the request. NULL on an email row, which isn't one.
    # "app" (trusted BFF request) | "external" (client that named a project).
    client_type: Mapped[str | None] = mapped_column(String(16))
    method: Mapped[str | None] = mapped_column(String(8))
    path: Mapped[str | None] = mapped_column(String(512))
    status_code: Mapped[int | None] = mapped_column(Integer)

    # --- the email: set only on an `email` row. `email_kind` is the stable key for the message
    # we sent ("approval"), so a later message type stays distinguishable without matching on a
    # subject line, which is prose and will be reworded.
    email_kind: Mapped[str | None] = mapped_column(String(32))
    # The address we wrote to, straight from the LDAP snapshot. NULL when the directory had
    # none for the user — the case `email_status="skipped"` exists to make visible.
    email_to: Mapped[str | None] = mapped_column(String(256))
    email_subject: Mapped[str | None] = mapped_column(String(256))
    # "sent" | "failed" | "skipped".
    email_status: Mapped[str | None] = mapped_column(String(16))

    # --- concept attribution: set when the call resolved a concept (the event we most care
    # about). `concept_version` is the version actually served, not the one asked for — the
    # selector the client sent (v / date / draft) is preserved in `detail`.
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concept.id"), index=True)
    concept_name: Mapped[str | None] = mapped_column(String(128), index=True)
    taxonomy: Mapped[str | None] = mapped_column(String(64))
    concept_version: Mapped[int | None] = mapped_column(Integer)

    # --- the request itself, for the detail view.
    # "jwt" | "api_key" | None (unauthenticated, e.g. a failed login).
    auth_method: Mapped[str | None] = mapped_column(String(16))
    query_string: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    # Full request context: path params, query params, selectors, and (for logins) the
    # attempted username. Never credentials — the login body's password is dropped.
    detail: Mapped[dict | None] = mapped_column(JSON)


class ConceptUsage(Base):
    """How often one user has read one concept — the audit log folded into a rollup.

    Everything here is *derived*: `api/usage.py` folds `audit_log` rows into it incrementally,
    so the table is a cache that can be dropped and rebuilt from the log at any time. It exists
    because the questions asked of it ("which concepts has this user used", "which concepts are
    used most") are aggregates over the whole log, and answering them by scanning it per request
    stops working the moment the log is a real one — the log grows with every API call, while
    this table grows only with distinct (user, concept) pairs.

    One row per pair, so both directions come out of the same rollup: group by `user_id` for the
    per-user view, by `concept_id` for "most used".

    `concept_name`/`taxonomy` are the *last* name the concept was read under, copied from the
    audit row exactly as the log itself denormalizes them. They are a label for linking, not an
    identity — a renamed concept keeps its id and the next read updates the label.
    """

    __tablename__ = "concept_usage"
    __table_args__ = (
        # The per-concept direction ("most used"): the PK's leading column is `user_id`, so it
        # cannot serve a scan keyed on the concept.
        Index("ix_concept_usage_concept_id", "concept_id"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concept.id"), primary_key=True)
    reads: Mapped[int] = mapped_column(Integer, default=0)
    first_used_at: Mapped[datetime] = mapped_column(DateTime)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    concept_name: Mapped[str | None] = mapped_column(String(128))
    taxonomy: Mapped[str | None] = mapped_column(String(64))
    # Which versions of the concept this user has read, as a sorted ", "-joined list ("1, 3, 4"),
    # folded from `audit_log.concept_version`. Null while no read named a version.
    versions: Mapped[str | None] = mapped_column(Text)


class UsageRollupState(Base):
    """The single-row watermark for the `concept_usage` fold: the highest `audit_log.id` that
    has already been counted.

    A watermark rather than a full recount is what makes the fold cheap enough to run on the
    read path: each refresh touches only the rows appended since the last one. It is also what
    makes it idempotent — re-running folds nothing — which is the property the whole design
    leans on, since the fold runs at boot *and* whenever a usage endpoint is read.
    """

    __tablename__ = "usage_rollup_state"

    id: Mapped[int] = mapped_column(primary_key=True)  # always 1
    last_audit_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # The rule the counted rows were folded under. A rollup started now is current by
    # definition; one stamped lower is refolded at boot. See USAGE_FILTER_VERSION.
    filter_version: Mapped[int] = mapped_column(Integer, default=USAGE_FILTER_VERSION)


class Concept(Base):
    """Identity plus clinical documentation. A concept's name(s) live in `concept_taxonomy`,
    keyed by taxonomy.

    The doc_* fields hold the concept-level documentation shown on the concept page — outside
    versioning, because it describes the concept and not one published definition. They are
    editable in the app (see the documentation PATCH in routers/writes.py) and are also
    (re)loaded by the importer from the optional reference notion_docs.json, which the sync
    sidecar exports from a Notion database — an in-app edit therefore lasts until the next
    reimport overwrites it for concepts present in that export.
    """

    __tablename__ = "concept"
    __table_args__ = (
        # The concepts table filters and sorts on the workflow status across the whole
        # vocabulary; without this the facet counts are a full scan of `concept`.
        Index("ix_concept_doc_status", "doc_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Clinical / implementation prose and known caveats, as plain text.
    doc_clinical: Mapped[str | None] = mapped_column(Text)
    doc_implementation: Mapped[str | None] = mapped_column(Text)
    doc_caveats: Mapped[str | None] = mapped_column(Text)
    # Free-form workflow label (e.g. "In Production"). Changing it needs can_publish and is
    # deliberately not audited.
    doc_status: Mapped[str | None] = mapped_column(String(64))
    # Upstream documentation page, when one exists — drives the "Open in Notion" button.
    notion_url: Mapped[str | None] = mapped_column(String(512))
    # Set when an approved deprecation request retired this concept. The row stays — its
    # pointers keep resolving and `audit_log.concept_id` still points somewhere — but the app
    # marks it retired and refuses new drafts on it.
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime)
    deprecated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # The concept that replaces this one, when the deprecation named a successor. A plain
    # integer, deliberately not a ForeignKey: the forced reference reimport clears the concept
    # graph with one bulk `DELETE FROM concept`, which a self-referential constraint would make
    # order-dependent. Chains are walked to their end by `services.final_successor`.
    successor_id: Mapped[int | None] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Source(Base):
    __tablename__ = "source"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nicename: Mapped[str | None] = mapped_column(String(128))
    supported_types: Mapped[list] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Taxonomy(Base):
    __tablename__ = "taxonomy"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[str | None] = mapped_column(String(64))


class ConceptTaxonomy(Base):
    """A **pointer**: "this identifier, in this taxonomy, names this concept", valid over a
    time window.

    The table is append-only. Rows are never deleted by users — retiring a name stamps
    `deprecated_at`, and re-adding it later mints a new row — so `?date=` can reconstruct what
    any identifier meant at any point in time, and a name that once resolved never 404s.

    There is deliberately **no unique constraint** on `(taxonomy_id, identifier)`. One
    identifier may name several concepts at once (a *group* — mostly ATC codes, where one code
    covers several substances), and one concept may hold several identifiers in one taxonomy
    (*aliases*). The only rule the application enforces is that the same
    `(taxonomy, identifier, concept)` is not active twice — see the pointer writes in
    ``api/routers/pointers.py``.
    """

    __tablename__ = "concept_taxonomy"

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concept.id"), index=True)
    taxonomy_id: Mapped[int] = mapped_column(ForeignKey("taxonomy.id"), index=True)
    # The concept's name within this taxonomy.
    identifier: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str | None] = mapped_column(String(256))
    # NULL = a primary name in this taxonomy; `RELATIONSHIP_ALIAS` = a secondary spelling.
    relationship: Mapped[str | None] = mapped_column(String(32))
    # The membership window: the pointer is active at T when
    # `created_at <= T AND (deprecated_at IS NULL OR deprecated_at > T)`.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime)
    deprecated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # `user` or `import` — see the ORIGIN_* constants above.
    origin: Mapped[str] = mapped_column(String(16), default=ORIGIN_USER)

    __table_args__ = (
        Index("ix_concept_taxonomy_tax_ident", "taxonomy_id", "identifier"),
    )


class Config(Base):
    """One immutable row per (concept, source, change). The table is the audit trail.

    `version_no` is a per-concept monotonic sequence, assigned only when a draft is
    published; it is NULL while a row is a draft. Current state is *derived*
    (MAX(version_no) per source), never stored as a flag.
    """

    __tablename__ = "config"

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concept.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"), index=True)

    type: Mapped[str] = mapped_column(String(32))
    # column is literally named "json" / "py" to match the API shape
    json_def: Mapped[dict] = mapped_column("json", JSON, nullable=False)
    python_code: Mapped[str | None] = mapped_column("py", Text)

    version_no: Mapped[int | None] = mapped_column(Integer)
    change_type: Mapped[str] = mapped_column(String(16), default="improvement")
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)

    # On a critical row: prior versions >= this number are affected (NULL = all prior).
    corrects_since_version_no: Mapped[int | None] = mapped_column(Integer)

    # Filled by the evaluation-package gate (Phase 2).
    validation_status: Mapped[str | None] = mapped_column(String(16))
    validation_report: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        Index(
            "uq_config_published_version",
            "concept_id",
            "version_no",
            unique=True,
            sqlite_where=text("status = 'published' AND version_no IS NOT NULL"),
        ),
        Index("ix_config_lookup", "concept_id", "status", "version_no"),
    )


class DeprecationRequest(Base):
    """Somebody with `can_edit` asking for a concept to be retired, and what a reviewer did.

    Retiring a concept is not an edit: it takes a definition out of circulation for every
    client pinned to it. So the two halves are split — anyone who may edit may *ask*, only
    `can_publish` may decide — and the ask survives the decision, which is what makes "who
    wanted this gone, and why" answerable later.

    A request is filed against a *name*, not only against a concept. A concept that carries
    several names loses just the one the request targeted — approving closes that pointer's
    window and leaves the concept live under its other names. Only when the targeted name is
    the concept's last live one does approving stamp the concept's
    `deprecated_at`/`deprecated_by`/`successor_id`. Rejecting only flips `status`.
    """

    __tablename__ = "deprecation_request"

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concept.id"), index=True)
    # The pointer this request was filed against — the name the requester was looking at. NULL
    # means the request is about the concept as a whole, which is what every request written
    # before names were addressable was.
    pointer_id: Mapped[int | None] = mapped_column(ForeignKey("concept_taxonomy.id"))
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    # The concept the requester believes supersedes this one, when they named one. Copied onto
    # `Concept.successor_id` on approval (the reviewer may override it).
    suggested_successor_id: Mapped[int | None] = mapped_column(ForeignKey("concept.id"))
    # "pending" | "approved" | "rejected" — see the DEPRECATION_* constants above.
    status: Mapped[str] = mapped_column(String(16), default=DEPRECATION_PENDING, index=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class Blob(Base):
    """One stored file, addressed by the sha256 of its contents.

    The bytes are NOT here: they live on disk under ``settings.file_dir``, sharded by the
    first two hex characters of the digest (see ``api/files.py``). Content addressing is what
    makes attachments cheap across the version history — a mapping file that never changes is
    attached to every version of a concept but stored exactly once, and re-uploading identical
    bytes is a no-op rather than a copy.
    """

    __tablename__ = "blob"

    id: Mapped[int] = mapped_column(primary_key=True)
    # sha256 hex of the contents; the storage key and the dedupe key in one.
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size: Mapped[int] = mapped_column(Integer)
    # What the download is served as. Sniffed from the upload, or guessed from the suffix.
    media_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SourceFile(Base):
    """A data file in a **source's** library: a mapping table, a pickled model, anything a
    definition's ``py`` snippet reads.

    Files belong to the source, not to one concept's version. Three sources' worth of
    experience with the older shape (a file attached to a single config row) said so: the same
    postcode table was read by four variables and therefore stored as four rows that had to be
    replaced in four places, and there was no answer at all to "which definitions read this
    file?" — the question every replacement starts with.

    `uuid` is the stable public identifier and the only thing a snippet ever names
    (``getfile("<uuid>")``, see ``api/pyrefs.py``). It is deliberately not the id: a file's
    identity has to survive a rename of its `path`, and it has to be safe to hand out in a
    URL without leaking how many files exist.

    It is **derived, once, from the source key and the path the file is first created under**
    (`source_file_uuid` at the top of this module) and then frozen — never re-derived, so a
    later rename does not move the identity. Deriving it rather than minting it randomly is
    what lets corr-vars write `getfile("…")` offline and a re-import into a fresh database
    resolve those references.

    Deletion is **soft, always**. Published configs pin file *versions* forever, so the bytes
    behind a retired file still have to be served to whoever reads that old concept version —
    a hard delete would silently break exactly the reproducibility this design is for. The
    delete route refuses while any current published config still reads the file, so
    `deleted_at` only ever marks something nothing new can reach.
    """

    __tablename__ = "source_file"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The public identifier, derived by `source_file_uuid(source.key, first path)`. The random
    # default is a backstop for the one case the derivation cannot serve — a seed already taken
    # by a row that has since been renamed away from it (see `services.store_file_version`).
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=lambda: str(uuid.uuid4())
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"), index=True)
    # The relative path the file is laid out at by a consumer (e.g.
    # ``"postcode/postcode_mapping.csv"``). Validated against traversal on the way in (see
    # ``api/files.py``) — it lands in filesystem paths downstream. A label, not an address:
    # nothing resolves a file by it any more.
    path: Mapped[str] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        UniqueConstraint("source_id", "path", name="uq_source_file_path"),
    )


class SourceFileVersion(Base):
    """One version of a `SourceFile` — the bytes it had at one point, and who put them there.

    `version_no` is a per-file 1-based sequence. The **current** version is derived as
    ``MAX(version_no)``, never stored as a flag, for the same reason `Config.version_no` is:
    a flag is a second source of truth that can disagree with the rows.

    A config references a *version*, not a file. That is the whole pinning story: uploading a
    new version leaves every published config reading the bytes it was published against, and
    is instead what mints those configs a new version of their own (see the cascade in
    ``api/services.py``).

    `path` is the name *this* version was uploaded under. A new version may rename the file, so
    the file's current `path` is not necessarily the one an older version carried.
    """

    __tablename__ = "source_file_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("source_file.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    blob_id: Mapped[int] = mapped_column(ForeignKey("blob.id"), index=True)
    # The path this version was uploaded under. A new version may rename the file (the identity
    # is the uuid), and the history is where that becomes visible: without it a rename would
    # retroactively relabel every earlier version. NULL on rows written before the column
    # existed — read it as "the same name the file has now".
    path: Mapped[str | None] = mapped_column(String(512))
    # Why this version was uploaded, in the uploader's words. Shown in the file's history.
    message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("file_id", "version_no", name="uq_source_file_version_no"),
    )


class ConfigFileRef(Base):
    """"This config version reads this file version" — the pin, computed from the snippet.

    Rows are derived, never authored: `services.sync_config_file_refs` re-reads the config's
    ``py`` with ``api/pyrefs.py`` and rewrites them. On a draft that happens on every edit, so
    the pins follow whatever the snippet currently says; on a published row it happened once,
    at publication, and the row is then immutable history like the config it belongs to.

    `path` is a **denormalized snapshot** of the file's path at pin time. It is what a consumer
    lays the bytes out at, and it has to be the path the definition was written against — a
    file renamed afterwards must not silently relocate the files of a version published before
    the rename. This is the split that decides what "the file's name" means where: the
    **manifest** in a concept read describes what one config version pinned, so it shows this
    snapshot, and so does the download served for it; the **library** pages describe the file
    as it stands, so they show `SourceFile.path`, the most recent name. `origin` records what
    put the row there.
    """

    __tablename__ = "config_file_ref"

    id: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[int] = mapped_column(ForeignKey("config.id"), index=True)
    file_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_file_version.id"), index=True
    )
    path: Mapped[str] = mapped_column(String(512))
    # `getfile` (read out of the snippet) or `legacy` (carried over from the pre-uuid
    # per-config attachments by the migration in api/main.py).
    origin: Mapped[str] = mapped_column(String(16), default=FILE_REF_GETFILE)

    __table_args__ = (
        UniqueConstraint("config_id", "path", name="uq_config_file_ref_path"),
    )
