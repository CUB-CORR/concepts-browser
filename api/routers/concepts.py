from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from .. import audit, export, services, usage
from ..config import settings
from ..db import get_db
from ..deps import has_capability, require_capability
from ..models import (
    CLIENT_APP,
    CLIENT_EXTERNAL,
    Concept,
    ConceptTaxonomy,
    ConceptUsage,
    Config,
    Source,
    Taxonomy,
    User,
    _utcnow,
)
from ..schemas import (
    STATUS_NONE,
    ConceptDetail,
    ConceptExportRequest,
    ConceptHistoryEntry,
    ConceptListItem,
    ConceptListQuery,
    ConceptSearchQuery,
    ConceptSearchResult,
    ConceptSelector,
    ConceptTablePage,
    ConceptTableQuery,
)
from ..security import CAN_ADMIN, CAN_READ, CAN_READ_DETAIL

# Set on a concept read that withheld something for want of `can_read_detail`. The payload says
# so too (`sources[*].py_locked`), but a machine consumer that only reaches for `py` would see
# a plain null; this header is the same fact where a client cannot help but pass it.
LOCKED_HEADER = "X-Concepts-Locked"

router = APIRouter(tags=["concepts"])

# Reading concept content requires an authenticated user with can_read.
_reader = require_capability(CAN_READ)
# Bulk export is admin-only.
_admin = require_capability(CAN_ADMIN)


def concept_query(
    request: Request,
    project: str = Query(
        ...,
        description="Name of the project the query is attributed to."
    ),
    db: Session = Depends(get_db),
    user: User = Depends(_reader),
) -> User:
    """Auth + project gate for every concept read.

    `project` is a required query param (so the public schema advertises it), but its *value* is
    only validated for external clients. Requests carrying the BFF's `X-App-Secret` (our web app)
    are internal: the project value is ignored (the app sends the placeholder `internal`). Every
    other authenticated client must name an existing, non-deleted project.

    The gate's verdict is stashed for the audit middleware, which writes the one `audit_log` row
    for this request once the response status is known — attributing the query to the requesting
    user and, for external clients, to the project.

    When no `app_shared_secret` is configured (dev / tests) the app/external distinction can't
    be made, so project *validation* is disabled and every read counts as app — but the param
    must still be present. Production sets the secret (compose makes it mandatory), which turns
    the external gate on. Note that such a deployment also records no *direct* API usage: the
    usage rollup counts what is not `app`, and without the secret nothing can be told apart.
    """
    if not settings.app_shared_secret or audit.is_app_request(request, settings.app_shared_secret):
        client_type, project_id = CLIENT_APP, None
    else:
        client_type = CLIENT_EXTERNAL
        project_id = audit.resolve_active_project(db, project).id
    audit.mark_client(request, client_type=client_type, project_id=project_id)
    return user


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    """Selectors compare against naive-UTC `created_at`; normalize aware inputs."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _one_selector(sel: ConceptSelector) -> None:
    if sum(p is not None for p in (sel.v, sel.date, sel.draft)) > 1:
        raise HTTPException(400, "Pass at most one of: v, date, draft")


def _selector_echo(sel: ConceptSelector) -> dict:
    return {
        "v": sel.v,
        "date": sel.date.isoformat() if sel.date is not None else None,
        "draft": sel.draft,
    }


def build_detail(
    db: Session,
    concept: Concept,
    pointer: ConceptTaxonomy | None,
    taxonomy: str | None,
    sel: ConceptSelector,
    *,
    detail: bool = True,
) -> tuple[dict, int | None]:
    """One concept as `ConceptDetail`, plus the version actually served (for the audit row).

    The single place a concept read is assembled: the name route calls it once per group
    member, the id route once. `pointer` is the taxonomy entry the caller arrived through — it
    decides the `name`/`display_name` the response is phrased in.

    `detail=False` (the caller has `can_read` but not `can_read_detail`) keeps the read a 200 —
    browsing a concept and its JSON is what `can_read` is *for* — and withholds only the `py`
    snippet, flagged as `sources[*].py_locked`. See `services.build_sources_payload`.
    """
    at_time = _to_naive_utc(sel.date)
    configs = services.latest_published_per_source(
        db, concept.id, at_version=sel.v, at_time=at_time
    )
    if sel.draft is not None:
        d = db.get(Config, sel.draft)
        if d is None or d.concept_id != concept.id or d.status != "draft":
            raise HTTPException(404, "Draft not found for this concept")
        configs = [c for c in configs if c.source_id != d.source_id] + [d]

    served = max((c.version_no for c in configs if c.version_no is not None), default=None)
    payload = {
        "id": concept.id,
        "taxonomy": taxonomy,
        "name": pointer.identifier if pointer is not None else None,
        "display_name": pointer.display_name if pointer is not None else None,
        "description": concept.description,
        "names": services.concept_taxonomy_entries(db, concept.id),
        "pointer": services.pointer_info(pointer) if pointer is not None else None,
        "deprecated_at": concept.deprecated_at,
        "successor_id": services.final_successor(db, concept),
        "version": services.current_concept_version(db, concept.id),
        "requested": {"v": sel.v, "date": sel.date, "draft": sel.draft},
        "sources": services.build_sources_payload(db, concept, configs, detail=detail),
        "doc_clinical": concept.doc_clinical,
        "doc_implementation": concept.doc_implementation,
        "doc_caveats": concept.doc_caveats,
        "doc_status": concept.doc_status,
        "notion_url": concept.notion_url,
        # Concept-level, outside versioning: the same values whatever `v`/`date` selected.
    }
    return payload, served


def mark_locked(response: Response, payloads: list[dict]) -> None:
    """Stamp `X-Concepts-Locked` when any source block in the response withheld its snippet."""
    if any(
        block.get("py_locked")
        for payload in payloads
        for block in payload.get("sources", {}).values()
    ):
        response.headers[LOCKED_HEADER] = CAN_READ_DETAIL


def concept_or_404(db: Session, concept_id: int) -> Concept:
    concept = db.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, f"Concept #{concept_id} not found")
    return concept


def history_rows(db: Session, concept_id: int) -> list[dict]:
    sources = {s.id: s for s in db.scalars(select(Source))}
    rows = db.scalars(
        select(Config)
        .where(Config.concept_id == concept_id, Config.status == "published")
        .order_by(Config.version_no.desc())
    )
    return [
        {
            "version": r.version_no,
            "source": sources[r.source_id].key if r.source_id in sources else None,
            "change_type": r.change_type,
            "message": r.message,
            "committed_at": r.created_at,
        }
        for r in rows
    ]


@router.get(
    "/concepts",
    response_model=list[ConceptListItem],
    openapi_extra={"x-public": True},
    summary="List concepts",
)
def list_concepts(
    q: Annotated[ConceptListQuery, Query()],
    db: Session = Depends(get_db),
    _ctx: User = Depends(concept_query),
):
    """One row per name registered in a taxonomy, with the concept it points at, its latest
    published version, contributing sources and config types. A concept named twice appears
    twice (the second row badged `alias`); an identifier naming several concepts yields one row
    per member, each carrying `group_size`. Pass `date` (`d`) to see the state as of a past
    timestamp, `include_deprecated` to also list retired names."""
    taxonomy = q.taxonomy or settings.default_taxonomy
    tax = db.scalar(select(Taxonomy).where(Taxonomy.key == taxonomy))
    if tax is None:
        raise HTTPException(404, f"Taxonomy '{taxonomy}' not found")

    at_time = _to_naive_utc(q.date) or _utcnow()
    source_keys = {s.id: s.key for s in db.scalars(select(Source))}
    filters = [ConceptTaxonomy.taxonomy_id == tax.id, ConceptTaxonomy.created_at <= at_time]
    if not q.include_deprecated:
        filters.append(services.pointer_active_at(at_time))
    rows = db.execute(
        select(Concept, ConceptTaxonomy)
        .join(ConceptTaxonomy, ConceptTaxonomy.concept_id == Concept.id)
        .where(*filters)
        .order_by(ConceptTaxonomy.identifier, Concept.id)
    )

    # Latest published config per (concept, source) for every concept in one batched query
    # (avoids a per-concept subquery — the list can hold thousands of concepts once the
    # auto-generated medication/laboratory variables are imported).
    index = services.latest_published_index(db, at_time=_to_naive_utc(q.date))
    groups = services.group_size_index(db, tax.id, at_time)

    out = []
    for concept, ct in rows:
        # The concept version as-of-time is the max version_no among those rows (= the global
        # max, since each source's latest carries that source's highest version_no).
        configs = index.get(concept.id, [])
        out.append(
            {
                "id": concept.id,
                "taxonomy": taxonomy,
                "name": ct.identifier,
                "display_name": ct.display_name,
                "description": concept.description,
                "version": max((c.version_no for c in configs), default=None),
                "sources": sorted(
                    {source_keys[c.source_id] for c in configs if c.source_id in source_keys}
                ),
                "types": sorted({c.type for c in configs}),
                # A concept is read-only when its single configured source is auto-generated
                # (medication/laboratory) — the list italicizes these.
                "read_only": len(configs) == 1
                and configs[0].type in settings.auto_generated_types,
                "pointer_id": ct.id,
                "relationship": ct.relationship,
                "origin": ct.origin,
                "group_size": groups.get(ct.identifier, 1),
                "deprecated_at": ct.deprecated_at,
                "concept_deprecated_at": concept.deprecated_at,
                "successor_id": services.final_successor(db, concept),
            }
        )
    return out


# How many names the fuzzy pass will look at. It reads one short string per name in the
# taxonomy and compares it token-wise, which is microseconds each — but a vocabulary an order
# of magnitude larger than anything we host should degrade to plain substring search rather
# than pay for a scan the searcher cannot see.
FUZZY_MAX_NAMES = 20_000
# And how many of them may come back. The list becomes an `IN (…)`, so it is bounded on the
# way out too — a reader who has to page through two thousand near-misses did not want a
# fuzzy match, they wanted a different search.
FUZZY_MAX_HITS = 2_000
# Below this many characters a term is a prefix somebody is still typing, not a typo worth
# guessing at — and a two-character fuzzy bucket would match most of the vocabulary.
FUZZY_MIN_TERM = 3


def _flat_sql(col):
    """`services.flatten_name`, in SQL — lowercase with the separators turned into spaces.

    Portable (`lower`/`replace` are everywhere) and, more importantly, character-for-character
    the same transformation the fuzzy pass applies in Python, so "blood sodium" reaches
    `lab_blood_sodium` by substring here and by token there without the two disagreeing.
    """
    expr = func.lower(func.coalesce(col, ""))
    for ch in services.NAME_SEPARATORS:
        expr = func.replace(expr, ch, " ")
    return expr


def _like_escape(term: str) -> str:
    """Escape what LIKE treats as a wildcard. `_` needs no escaping — flattening ate it."""
    return term.replace("\\", "\\\\").replace("%", "\\%")


def _table_search_clause(term: str, fuzzy_pointer_ids: list[int]):
    """The `q` filter: names *and* documentation text, plus whatever the fuzzy pass found.

    A concept is as often looked for by a phrase from its clinical description as by its
    identifier, so the search covers both — which is also why it cannot run in the browser:
    the documentation text is not in the list payload. Names are matched on their flattened
    form, prose on the text as written.
    """
    plain = f"%{term.strip().lower()}%"
    flat = f"%{_like_escape(services.flatten_name(term.strip()))}%"
    clauses = [
        _flat_sql(ConceptTaxonomy.identifier).like(flat, escape="\\"),
        _flat_sql(ConceptTaxonomy.display_name).like(flat, escape="\\"),
        func.lower(func.coalesce(Concept.description, "")).like(plain),
        func.lower(func.coalesce(Concept.doc_clinical, "")).like(plain),
        func.lower(func.coalesce(Concept.doc_implementation, "")).like(plain),
        func.lower(func.coalesce(Concept.doc_caveats, "")).like(plain),
    ]
    if fuzzy_pointer_ids:
        clauses.append(ConceptTaxonomy.id.in_(fuzzy_pointer_ids))
    return or_(*clauses)


def _fuzzy_pointer_ids(db: Session, term: str, name_filters: list) -> list[int]:
    """The pointers whose *name* is a typo away from the term, as a list of pointer ids.

    Nothing exotic is available in SQLite, so this is the pragmatic split: the database hands
    over one row per name in the taxonomy — an identifier and a display name, a few thousand
    short strings — and the scoring happens here, token by token with a per-token typo budget.
    The result is fed back into the query both as an extra OR of the filter and as a ranking
    bucket, so a fuzzy hit is found *and* sorted below every literal name hit.

    Cost is one indexed scan plus O(names × tokens) cheap comparisons, nearly all of which die
    on the length prefilter; `FUZZY_MAX_NAMES` bounds the worst case.
    """
    tokens = services.name_tokens(term)
    if not tokens or len(term.strip()) < FUZZY_MIN_TERM:
        return []
    rows = db.execute(
        select(ConceptTaxonomy.id, ConceptTaxonomy.identifier, ConceptTaxonomy.display_name)
        .where(*name_filters)
        .limit(FUZZY_MAX_NAMES)
    ).all()
    flat_term = services.flatten_name(term.strip())
    hits = []
    for pointer_id, identifier, display_name in rows:
        # A name the term is literally inside is found and ranked by the SQL above; carrying it
        # here too would only lengthen the id list — and for a short term like "lab" that is
        # most of the vocabulary.
        if flat_term in services.flatten_name(identifier) or flat_term in services.flatten_name(
            display_name
        ):
            continue
        if services.fuzzy_name_hit(tokens, identifier) or services.fuzzy_name_hit(
            tokens, display_name
        ):
            hits.append(pointer_id)
            if len(hits) >= FUZZY_MAX_HITS:
                break
    return hits


def _relevance_expr(term: str, fuzzy_pointer_ids: list[int]):
    """How well a row answers the search, as a rank where 0 is best.

    A hit in the *name* always beats a hit that only appears in the prose: somebody typing
    `sodium` is looking for the concept called that, not for the forty concepts whose caveats
    mention it. Within the name, the ladder is exact → prefix → substring → display name →
    fuzzy, and everything that matched only description or documentation shares the bottom
    rung.
    """
    flat_term = services.flatten_name(term.strip())
    escaped = _like_escape(flat_term)
    ident = _flat_sql(ConceptTaxonomy.identifier)
    label = _flat_sql(ConceptTaxonomy.display_name)
    branches = [
        (ident == flat_term, 0),
        (ident.like(f"{escaped}%", escape="\\"), 1),
        (ident.like(f"%{escaped}%", escape="\\"), 2),
        (label.like(f"%{escaped}%", escape="\\"), 3),
    ]
    if fuzzy_pointer_ids:
        branches.append((ConceptTaxonomy.id.in_(fuzzy_pointer_ids), 4))
    return case(*branches, else_=5)


@router.get(
    "/concepts/table",
    response_model=ConceptTablePage,
    openapi_extra={"x-public": True},
    summary="List concepts as a sorted, filtered, paginated table",
)
def concepts_table(
    q: Annotated[ConceptTableQuery, Query()],
    db: Session = Depends(get_db),
    caller: User = Depends(concept_query),
):
    """The concept list as a table: the same one-row-per-name rows the list returns, plus the
    columns a table wants — how much the concept is read, how much documentation it carries
    (as an S/M/L bucket), its status, and who last published a version of it.

    Sorting, filtering, searching and paging all happen here rather than in the client: the
    taxonomy holds thousands of names, and a page sorted in the browser would only sort that
    page. With no `sort` and no `q` the order is *most used first*, ties broken by *most
    documentation* — the two things that make a concept the one a newcomer should look at.

    `q` searches identifiers, display names, the description and all three documentation
    fields, and with no explicit `sort` it also *orders* the result by relevance: a hit in the
    name always outranks one that appears only in the prose, and within the name exact beats
    prefix beats substring beats a typo. Names are compared separator-insensitively, so
    "blood sodium" finds `lab_blood_sodium`. `status`, `source` and `type` filter on the
    workflow label and on the concept's
    current configuration; each is repeatable, and each comes back as a facet with counts.
    `date`/`d` moves the same as-of lens the list honours; the columns it cannot move (usage,
    documentation, status — all concept-level and unversioned) are named in `degraded`.
    """
    taxonomy = q.taxonomy or settings.default_taxonomy
    tax = db.scalar(select(Taxonomy).where(Taxonomy.key == taxonomy))
    if tax is None:
        raise HTTPException(404, f"Taxonomy '{taxonomy}' not found")

    # "Most used" reads the rollup, which is folded from the audit log on demand — same as the
    # usage endpoints, so the table never shows counts staler than the request that asked.
    usage.refresh(db)

    at_time = _to_naive_utc(q.date) or _utcnow()
    is_admin = has_capability(caller, CAN_ADMIN)

    # --- the joined shape every part of this query is phrased over -----------------------
    doc_chars = services.doc_chars_expr()

    reads = (
        select(
            ConceptUsage.concept_id.label("concept_id"),
            func.sum(ConceptUsage.reads).label("reads"),
            func.count().label("users"),
        )
        .group_by(ConceptUsage.concept_id)
        .subquery()
    )
    mine = (
        select(
            ConceptUsage.concept_id.label("concept_id"),
            ConceptUsage.reads.label("my_reads"),
        )
        .where(ConceptUsage.user_id == caller.id)
        .subquery()
    )
    # The latest published version of the concept as of `at_time`, and the row that carries it.
    # `version_no` is a per-concept sequence with a unique index over published rows, so the
    # max identifies exactly one config — which is what makes "last edited (by)" a join and
    # not a per-row lookup.
    mv = (
        select(Config.concept_id.label("concept_id"), func.max(Config.version_no).label("mv"))
        .where(
            Config.status == "published",
            Config.version_no.is_not(None),
            Config.created_at <= at_time,
        )
        .group_by(Config.concept_id)
        .subquery()
    )
    latest = (
        select(
            mv.c.concept_id.label("concept_id"),
            mv.c.mv.label("version"),
            Config.created_at.label("edited_at"),
            Config.created_by.label("editor_id"),
        )
        .join(
            Config,
            and_(
                Config.concept_id == mv.c.concept_id,
                Config.version_no == mv.c.mv,
                Config.status == "published",
            ),
        )
        .subquery()
    )
    # The current configuration of each concept: latest published row per (concept, source),
    # as-of the lens. The same thing the `sources`/`types` columns are read off, so the
    # filters over it can never disagree with what the row shows. Built per call site — the
    # facet queries join it while the filters put it inside an EXISTS, and one subquery object
    # in both places would render as the same alias twice.
    def current_configs(name: str):
        mv_src = (
            select(
                Config.concept_id.label("concept_id"),
                Config.source_id.label("source_id"),
                func.max(Config.version_no).label("mv"),
            )
            .where(
                Config.status == "published",
                Config.version_no.is_not(None),
                Config.created_at <= at_time,
            )
            .group_by(Config.concept_id, Config.source_id)
            .subquery(f"{name}_mv")
        )
        cfg = aliased(Config)
        src = aliased(Source)
        return (
            select(
                mv_src.c.concept_id.label("concept_id"),
                src.key.label("source_key"),
                cfg.type.label("type"),
            )
            .join(
                cfg,
                and_(
                    cfg.concept_id == mv_src.c.concept_id,
                    cfg.source_id == mv_src.c.source_id,
                    cfg.version_no == mv_src.c.mv,
                    cfg.status == "published",
                ),
            )
            .join(src, src.id == mv_src.c.source_id)
            .subquery(name)
        )

    current_cfg = current_configs("current_cfg")

    def configured_exists(name: str, extra=None):
        """EXISTS over a concept's current configs — correlated only to `concept`, so the
        facet queries may join their own copy of the same shape alongside it."""
        cfg = current_configs(name)
        clauses = [cfg.c.concept_id == Concept.id]
        if extra is not None:
            clauses.append(extra(cfg))
        return select(1).select_from(cfg).where(*clauses).correlate(Concept).exists()

    ct_names = aliased(ConceptTaxonomy)
    names = (
        select(
            ct_names.concept_id.label("concept_id"),
            func.count(func.distinct(ct_names.identifier)).label("names_count"),
        )
        .where(
            ct_names.created_at <= at_time,
            or_(ct_names.deprecated_at.is_(None), ct_names.deprecated_at > at_time),
        )
        .group_by(ct_names.concept_id)
        .subquery()
    )

    def counted(stmt):
        """The rows the filters speak about: one per name, and the concept it names.

        Every filter is phrased over these two tables alone, so this is all a count or a facet
        needs — and all it should carry. The per-concept subqueries below are one row each, so
        adding them could not change a count, but it does change the plan: made to count 8k
        names, SQLite starts re-scanning the materialized subqueries once per row and the query
        goes from milliseconds to seconds.
        """
        return stmt.select_from(ConceptTaxonomy).join(
            Concept, Concept.id == ConceptTaxonomy.concept_id
        )

    def joined(stmt):
        """`counted`, plus everything a *row* displays. Only the one page-sized query needs it."""
        return (
            counted(stmt)
            .outerjoin(reads, reads.c.concept_id == Concept.id)
            .outerjoin(mine, mine.c.concept_id == Concept.id)
            .outerjoin(latest, latest.c.concept_id == Concept.id)
            .outerjoin(names, names.c.concept_id == Concept.id)
            .outerjoin(User, User.id == latest.c.editor_id)
        )

    filters = [ConceptTaxonomy.taxonomy_id == tax.id, ConceptTaxonomy.created_at <= at_time]
    if not q.include_deprecated:
        filters.append(services.pointer_active_at(at_time))

    # The search, and the relevance rank that goes with it. The fuzzy pass runs over the same
    # set of names the table is drawn from — the filters above, before any facet narrows it —
    # so a typo is forgiven for exactly the names the reader could have been looking at.
    term = (q.q or "").strip()
    relevance = None
    if term:
        fuzzy_ids = _fuzzy_pointer_ids(db, term, filters)
        relevance = _relevance_expr(term, fuzzy_ids)
        filters.append(_table_search_clause(term, fuzzy_ids))

    if q.configured == "configured":
        filters.append(configured_exists("cfg_any"))
    elif q.configured == "unconfigured":
        filters.append(~configured_exists("cfg_any"))
    if q.source:
        filters.append(
            configured_exists("cfg_source", lambda c: c.c.source_key.in_(q.source))
        )
    if q.type:
        filters.append(configured_exists("cfg_type", lambda c: c.c.type.in_(q.type)))

    # Each facet counts what is reachable *without* its own filter, so ticking one value never
    # makes the others disappear from the control that offers them.
    def facet(column, *, blank: str | None = None):
        rows = db.execute(
            counted(select(column, func.count())).where(*filters).group_by(column)
        ).all()
        out = [
            {"value": value if value is not None else blank, "count": count}
            for value, count in rows
            if value is not None or blank is not None
        ]
        return sorted(out, key=lambda f: (f["value"] == blank, f["value"].lower()))

    statuses = facet(Concept.doc_status, blank=STATUS_NONE)
    # Sources and types are many-per-concept, so their facets count *pointers reaching* a
    # value — a row is counted once per source it is configured from, which is what a chip
    # saying "how many rows would this leave me" means.
    cfg_join = current_cfg.c.concept_id == Concept.id
    source_rows = db.execute(
        counted(select(current_cfg.c.source_key, func.count()))
        .join(current_cfg, cfg_join)
        .where(*filters)
        .group_by(current_cfg.c.source_key)
    ).all()
    type_rows = db.execute(
        counted(select(current_cfg.c.type, func.count()))
        .join(current_cfg, cfg_join)
        .where(*filters)
        .group_by(current_cfg.c.type)
    ).all()
    sources_facet = sorted(
        ({"value": v, "count": c} for v, c in source_rows), key=lambda f: f["value"]
    )
    types_facet = sorted(
        ({"value": v, "count": c} for v, c in type_rows), key=lambda f: f["value"]
    )

    if q.status:
        wanted = [s for s in q.status if s != STATUS_NONE]
        clauses = [Concept.doc_status.in_(wanted)] if wanted else []
        if STATUS_NONE in q.status:
            clauses.append(Concept.doc_status.is_(None))
        filters.append(or_(*clauses) if len(clauses) > 1 else clauses[0])

    total = db.scalar(counted(select(func.count())).where(*filters)) or 0

    # --- ordering -------------------------------------------------------------------------
    my_reads = func.coalesce(mine.c.my_reads, 0)
    total_reads = func.coalesce(reads.c.reads, 0)
    keys = {
        "usage": total_reads,
        "mine": my_reads,
        "documentation": doc_chars,
        "name": ConceptTaxonomy.identifier,
        "display_name": func.coalesce(ConceptTaxonomy.display_name, ""),
        "status": func.coalesce(Concept.doc_status, ""),
        "edited": latest.c.edited_at,
        "editor": func.coalesce(User.username, ""),
        "version": func.coalesce(latest.c.version, 0),
        "names": func.coalesce(names.c.names_count, 0),
        "id": Concept.id,
    }
    # An omitted `sort` means "whatever this view is *for*": relevance while searching, most
    # used otherwise. Naming a column overrides that — a reader who clicked "Version" wants
    # versions, and relevance drops to being the first tiebreaker under their choice.
    sort_key = q.sort or ("relevance" if relevance is not None else "usage")
    if sort_key == "relevance" and relevance is None:
        sort_key = "usage"

    if sort_key == "relevance":
        # Relevance has no meaningful direction: best first, or it is not a ranking.
        order = [relevance.asc(), total_reads.desc(), doc_chars.desc()]
    else:
        primary = keys[sort_key]
        primary = primary.desc() if q.dir == "desc" else primary.asc()
        # Whatever the chosen key, the default order is the tiebreaker underneath it — so equal
        # usage falls back to the better-documented concept, and equal everything to a stable
        # (identifier, id) order that keeps paging from shuffling rows between pages.
        order = [primary]
        if relevance is not None:
            order.append(relevance.asc())
        if sort_key not in ("usage", "documentation"):
            order.append(total_reads.desc())
        if sort_key != "documentation":
            order.append(doc_chars.desc())
    # The last two keys are unique together, which is what makes the slices the infinite
    # scroll appends a partition of the sorted whole rather than a resampling of it.
    order += [ConceptTaxonomy.identifier, ConceptTaxonomy.id]

    rows = db.execute(
        joined(
            select(
                Concept,
                ConceptTaxonomy,
                doc_chars.label("doc_chars"),
                total_reads.label("reads"),
                my_reads.label("my_reads"),
                reads.c.users,
                latest.c.edited_at,
                latest.c.version,
                User.username,
                func.coalesce(names.c.names_count, 1).label("names_count"),
            )
        )
        .where(*filters)
        .order_by(*order)
        .limit(q.page_size)
        .offset((q.page - 1) * q.page_size)
    ).all()

    source_keys = {s.id: s.key for s in db.scalars(select(Source))}
    index = services.latest_published_index(
        db,
        at_time=_to_naive_utc(q.date),
        concept_ids=[r.Concept.id for r in rows],
    )
    groups = services.group_size_index(db, tax.id, at_time)

    out = []
    for r in rows:
        concept, ct = r.Concept, r.ConceptTaxonomy
        configs = index.get(concept.id, [])
        out.append(
            {
                "id": concept.id,
                "taxonomy": taxonomy,
                "name": ct.identifier,
                "display_name": ct.display_name,
                "description": concept.description,
                "version": r.version,
                "sources": sorted(
                    {source_keys[c.source_id] for c in configs if c.source_id in source_keys}
                ),
                "types": sorted({c.type for c in configs}),
                "read_only": len(configs) == 1
                and configs[0].type in settings.auto_generated_types,
                "pointer_id": ct.id,
                "relationship": ct.relationship,
                "origin": ct.origin,
                "group_size": groups.get(ct.identifier, 1),
                "deprecated_at": ct.deprecated_at,
                "concept_deprecated_at": concept.deprecated_at,
                "successor_id": services.final_successor(db, concept),
                "doc_size": services.doc_size(r.doc_chars),
                "doc_status": concept.doc_status,
                # One line of the clinical prose, not the prose: the table's Description column
                # is a single truncated line, and a page of full documentation text would be
                # the largest thing in the response by far.
                "doc_clinical_excerpt": services.doc_excerpt(concept.doc_clinical),
                "usage_reads": r.reads,
                "my_reads": r.my_reads,
                # Distinct readers is a fact about people, not about the concept.
                "usage_users": r.users if is_admin else None,
                "last_edited_at": r.edited_at,
                "last_edited_by": r.username,
                "names_count": r.names_count,
            }
        )

    ids = None
    if q.include_ids:
        ids = sorted(
            set(db.scalars(counted(select(Concept.id)).where(*filters).distinct()).all())
        )

    return {
        "rows": out,
        "total": total,
        "page": q.page,
        "page_size": q.page_size,
        "pages": -(-total // q.page_size),
        "statuses": statuses,
        "sources": sources_facet,
        "types": types_facet,
        "ids": ids,
        # Concept-level fields carry no history, so a date lens cannot move them. Say which.
        "degraded": ["usage", "documentation", "status"] if q.date is not None else [],
    }


@router.get(
    "/concepts/search",
    response_model=list[ConceptSearchResult],
    summary="Search concepts by any of their names",
)
def search_concepts(
    q: Annotated[ConceptSearchQuery, Query()],
    db: Session = Depends(get_db),
    _ctx: User = Depends(concept_query),
):
    """Find concepts by a substring of any identifier or display name, in any taxonomy.

    Grouped one entry per concept, carrying every pointer of it that matched, so a picker can
    show what else the concept is called. Active names sort ahead of retired ones."""
    return services.search_concepts(db, q.q, limit=q.limit)


@router.post(
    "/concepts/export",
    summary="Export concepts as CSV/XLSX (admin)",
)
def export_concepts(
    req: ConceptExportRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_admin),
):
    """Download the concepts list as a spreadsheet: one row per name registered in the
    taxonomy, a name column per taxonomy, the clinical documentation, and (optionally)
    the latest published config per source. A POST because the app sends the concept
    ids of its filtered list, which don't fit in a query string."""
    taxonomy = req.taxonomy or settings.default_taxonomy
    tax = db.scalar(select(Taxonomy).where(Taxonomy.key == taxonomy))
    if tax is None:
        raise HTTPException(404, f"Taxonomy '{taxonomy}' not found")

    headers, rows = export.build_export_table(
        db,
        tax,
        ids=req.ids,
        at_time=_to_naive_utc(req.date),
        include_configs=req.include_configs,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"concepts_{taxonomy}_{stamp}.{req.format}"
    if req.format == "xlsx":
        content, media_type = export.to_xlsx(headers, rows), export.XLSX_MEDIA_TYPE
    else:
        content, media_type = export.to_csv(headers, rows), export.CSV_MEDIA_TYPE
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# The id routes are declared before the name routes: `/concept/id/5` would otherwise bind
# `taxonomy="id"`, `name="5"` on the name route below.


@router.get(
    "/concept/id/{concept_id}",
    response_model=ConceptDetail,
    openapi_extra={"x-public": True},
    summary="Get a concept by id",
)
def get_concept_by_id(
    request: Request,
    response: Response,
    concept_id: int,
    sel: Annotated[ConceptSelector, Query()],
    db: Session = Depends(get_db),
    ctx: User = Depends(concept_query),
):
    """Return one concept, addressed by its id — the canonical, never-ambiguous form. Takes the
    same selectors as the name route: at most one of `v`, `date`/`d`, `draft`.

    Without `can_read_detail` the `py` snippets are withheld: each affected source block carries
    `py_locked: true` and the response the `X-Concepts-Locked` header."""
    _one_selector(sel)
    concept = concept_or_404(db, concept_id)
    found = services.display_pointer(db, concept.id, _to_naive_utc(sel.date))
    pointer, taxonomy = found if found is not None else (None, None)

    payload, served = build_detail(
        db, concept, pointer, taxonomy, sel, detail=has_capability(ctx, CAN_READ_DETAIL)
    )
    mark_locked(response, [payload])
    audit.mark_concept(
        request,
        concept_id=concept.id,
        name=payload["name"],
        taxonomy=taxonomy,
        version=served,
        selector=_selector_echo(sel),
    )
    return payload


@router.get(
    "/concept/id/{concept_id}/history",
    response_model=list[ConceptHistoryEntry],
    openapi_extra={"x-public": True},
    summary="Get a concept's version history by id",
)
def concept_history_by_id(
    request: Request,
    concept_id: int,
    db: Session = Depends(get_db),
    _ctx: User = Depends(concept_query),
):
    """The published version history of a concept, newest first."""
    concept = concept_or_404(db, concept_id)
    found = services.display_pointer(db, concept.id)
    audit.mark_concept(
        request,
        concept_id=concept.id,
        name=found[0].identifier if found else None,
        taxonomy=found[1] if found else None,
        version=None,
    )
    return history_rows(db, concept.id)


@router.get(
    "/concept/{taxonomy}/{name}",
    response_model=list[ConceptDetail],
    openapi_extra={"x-public": True},
    summary="Get the concept(s) a name resolves to",
)
def get_concept(
    request: Request,
    response: Response,
    taxonomy: str,
    name: str,
    sel: Annotated[ConceptSelector, Query()],
    db: Session = Depends(get_db),
    ctx: User = Depends(concept_query),
):
    """Return every concept this name points at, with their per-source published definitions.

    Always a list: an identifier is allowed to name several concepts at once (a group). Select
    which state to return with at most one of `v` (version), `date`/`d` (as-of timestamp), or
    `draft` (to view a specific draft) — `v` and `draft` address one concept's history, so a
    name that resolves to a group rejects them with an `ambiguous_name` 400. `date` moves the
    whole lens: it filters which names were registered then *and* which versions existed.

    A name whose pointers have all been retired still resolves, to what it last meant; those
    elements carry a `pointer.deprecated_at`.

    Without `can_read_detail` the `py` snippets are withheld: each affected source block carries
    `py_locked: true` and the response the `X-Concepts-Locked` header.
    """
    _one_selector(sel)
    matches = services.resolve_pointers(db, taxonomy, name, _to_naive_utc(sel.date))
    if not matches:
        raise HTTPException(404, f"Concept '{name}' not found in taxonomy '{taxonomy}'")
    if len(matches) > 1 and (sel.v is not None or sel.draft is not None):
        raise services.ambiguous_name_error(taxonomy, name, matches)

    detail = has_capability(ctx, CAN_READ_DETAIL)
    out = [
        build_detail(db, concept, ct, taxonomy, sel, detail=detail) for ct, concept in matches
    ]
    mark_locked(response, [payload for payload, _ in out])

    # Attribute this read to the concept, to the selector the client sent, and to the version
    # actually served. A draft has no version_no, so an overlaid draft doesn't move the served
    # version — it's recorded as the `draft` selector instead. A group is one read of several
    # concepts, so it gets one row naming none of them and listing all of them in `detail`.
    single = len(out) == 1
    audit.mark_concept(
        request,
        concept_id=matches[0][1].id if single else None,
        name=name,
        taxonomy=taxonomy,
        version=out[0][1] if single else None,
        selector=_selector_echo(sel),
    )
    if not single:
        audit.mark_detail(request, group_members=[c.id for _, c in matches])
    return [payload for payload, _ in out]


@router.get(
    "/concept/{taxonomy}/{name}/history",
    response_model=list[ConceptHistoryEntry],
    openapi_extra={"x-public": True},
    summary="Get a concept's version history",
)
def concept_history(
    request: Request,
    taxonomy: str,
    name: str,
    db: Session = Depends(get_db),
    _ctx: User = Depends(concept_query),
):
    """The published version history of a concept, newest first: version number, source,
    change type and commit message for each release. A version history belongs to one concept,
    so a name that resolves to a group is an `ambiguous_name` 400 — address a member by id."""
    _, concept = services.resolve_single(db, taxonomy, name)
    audit.mark_concept(request, concept_id=concept.id, name=name, taxonomy=taxonomy, version=None)
    return history_rows(db, concept.id)
