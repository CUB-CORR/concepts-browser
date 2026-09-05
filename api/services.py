"""Query helpers for concepts, versions and warnings (DB-portable SQL).

Also the two write helpers everything that mints a published version goes through — the
importer, a publish, and the file cascade — so "what a published row looks like" is stated
once (`mint_published_version`), and the pins from a config's snippet to the file versions it
reads are computed in one place (`sync_config_file_refs`).
"""
import logging
import uuid as uuidlib
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import Row, and_, delete, func, or_, select
from sqlalchemy.orm import Session

from . import files as blobstore
from . import pyrefs
from .config import settings
from .models import (
    FILE_REF_GETFILE,
    RELATIONSHIP_ALIAS,
    Blob,
    Concept,
    ConceptTaxonomy,
    Config,
    ConfigFileRef,
    Source,
    SourceFile,
    SourceFileVersion,
    Taxonomy,
    User,
    _utcnow,
    source_file_uuid,
)

log = logging.getLogger(__name__)

# How much documentation a concept carries, as three buckets over the combined character count
# of its three prose fields. The concepts table sorts on the count and shows only the bucket —
# a character count is a measurement, not an answer to "is this documented well enough".
# Stated once, here, so the sort, the served letter and the guide can never drift apart.
DOC_SIZE_SMALL_UNDER = 400
DOC_SIZE_MEDIUM_UNDER = 1500


def doc_chars_expr():
    """SQL expression for a concept's total documentation length, in characters."""
    return (
        func.length(func.coalesce(Concept.doc_clinical, ""))
        + func.length(func.coalesce(Concept.doc_implementation, ""))
        + func.length(func.coalesce(Concept.doc_caveats, ""))
    )


def doc_size(chars: int | None) -> str | None:
    """The S/M/L letter for a documentation character count; None when nothing is written."""
    if not chars:
        return None
    if chars < DOC_SIZE_SMALL_UNDER:
        return "S"
    if chars < DOC_SIZE_MEDIUM_UNDER:
        return "M"
    return "L"


# --- name matching -----------------------------------------------------------------------
# Identifiers are written `lab_blood_sodium` and searched for as "blood sodium", so every
# comparison below happens on a *flattened* name: lowercased, with the separators turned into
# spaces. The same flattening is expressible in SQL (a chain of `replace`), which is what lets
# the exact/prefix/substring ranking run in the database and the fuzzy pass run here without
# the two disagreeing about what a name is.
NAME_SEPARATORS = ("_", "-", ".", "/", ":")


def flatten_name(text: str | None) -> str:
    """A name as it is compared: lowercase, separators replaced by spaces, nothing collapsed."""
    flat = (text or "").lower()
    for ch in NAME_SEPARATORS:
        flat = flat.replace(ch, " ")
    return flat


def name_tokens(text: str | None) -> list[str]:
    """The words of a name — what the fuzzy pass matches token by token."""
    return flatten_name(text).split()


def fuzzy_budget(token: str) -> int:
    """How many typos a token of this length may carry and still be considered the same word.

    Short tokens get no slack at all: at three characters an edit distance of one relates
    almost any pair of words, which would make the fuzzy bucket meaningless.
    """
    if len(token) < 4:
        return 0
    if len(token) < 8:
        return 1
    return 2


def within_edit_distance(a: str, b: str, budget: int) -> bool:
    """True when `a` and `b` are at most `budget` single-character edits apart.

    Plain Levenshtein, but it gives up the moment a whole row is over budget, and the length
    difference is checked first — two cheap guards that mean the quadratic body only ever runs
    for pairs of short, similar words. Words, not identifiers: the caller splits both sides
    into tokens first, so `len(a)` and `len(b)` are a handful of characters.
    """
    if budget <= 0:
        return a == b
    if abs(len(a) - len(b)) > budget:
        return False
    if a == b:
        return True
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        if min(current) > budget:
            return False
        previous = current
    return previous[len(b)] <= budget


def fuzzy_name_hit(term_tokens: list[str], name: str | None) -> bool:
    """True when every word of the search term matches a word of `name` up to its typo budget.

    Per token rather than over the whole string, which is what makes the match order- and
    separator-insensitive: "sodum blood" still finds `lab_blood_sodium`. A token that is a
    prefix of a name word counts — people stop typing early far more often than they mistype.
    """
    if not term_tokens:
        return False
    candidates = name_tokens(name)
    if not candidates:
        return False
    for token in term_tokens:
        budget = fuzzy_budget(token)
        if not any(
            word.startswith(token) or within_edit_distance(token, word, budget)
            for word in candidates
        ):
            return False
    return True


DOC_EXCERPT_CHARS = 120


def doc_excerpt(text: str | None, limit: int = DOC_EXCERPT_CHARS) -> str | None:
    """The opening of a documentation field, as one line of at most `limit` characters.

    The concepts table shows the clinical description in a single-line cell, so serving the
    whole prose would be thousands of characters per row for a few dozen on screen. Newlines
    collapse to spaces (the cell is one line either way) and the cut falls on a word boundary
    where one is near enough, with an ellipsis marking that there is more.
    """
    if not text:
        return None
    flat = " ".join(text.split())
    if not flat:
        return None
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rstrip()
    space = cut.rfind(" ")
    # Only honour the word boundary when it does not throw away most of the excerpt.
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "…"


def pointer_active_at(at_time: datetime):
    """Filter clause for the pointers whose membership window contains `at_time`."""
    return and_(
        ConceptTaxonomy.created_at <= at_time,
        or_(
            ConceptTaxonomy.deprecated_at.is_(None),
            ConceptTaxonomy.deprecated_at > at_time,
        ),
    )


def resolve_pointers(
    db: Session, taxonomy: str, name: str, at_time: datetime | None = None
) -> list[tuple[ConceptTaxonomy, Concept]]:
    """Every concept an identifier names in a taxonomy at a point in time.

    Usually one, but an identifier is allowed to name several concepts at once — a *group*,
    which is why this returns a list and the name route returns one element per member.

    When no pointer is active at `at_time`, the name still resolves — to the window that was
    closest to being open then. A name that ever resolved must keep resolving, or every link
    and every client pinned to it breaks the moment somebody renames a concept, and a client
    reading as-of a date before the concept was registered gets what the name means rather than
    a 404. Callers tell the cases apart by the pointer's own `created_at`/`deprecated_at`.
    Ordered by concept id, so a group's members come back in a stable order.
    """
    at_time = at_time or _utcnow()
    rows = list(
        db.execute(
            select(ConceptTaxonomy, Concept)
            .join(Concept, Concept.id == ConceptTaxonomy.concept_id)
            .join(Taxonomy, Taxonomy.id == ConceptTaxonomy.taxonomy_id)
            .where(Taxonomy.key == taxonomy, ConceptTaxonomy.identifier == name)
            .order_by(Concept.id, ConceptTaxonomy.id)
        )
    )
    active = [
        (ct, c)
        for ct, c in rows
        if ct.created_at <= at_time and (ct.deprecated_at is None or ct.deprecated_at > at_time)
    ]
    if active:
        return active

    def rank(ct: ConceptTaxonomy) -> tuple:
        # Windows that had already closed first (most recently closed wins), then windows that
        # had not opened yet (the one that opened soonest after).
        if ct.created_at <= at_time:
            return (0, -(ct.deprecated_at or ct.created_at).timestamp())
        return (1, ct.created_at.timestamp())

    # One row per concept — a concept that held the name over two separate windows is still one
    # member of the answer.
    best: dict[int, tuple[ConceptTaxonomy, Concept]] = {}
    for ct, c in rows:
        held = best.get(c.id)
        if held is None or rank(ct) < rank(held[0]):
            best[c.id] = (ct, c)
    return [best[cid] for cid in sorted(best)]


def ambiguous_name_error(
    taxonomy: str, name: str, matches: list[tuple[ConceptTaxonomy, Concept]]
) -> HTTPException:
    """The 400 every name-addressed route raises when an identifier names a group.

    One helper rather than a body per call site: the shape is part of the public contract — the
    app renders the member list as a picker, so it has to be identical everywhere.
    """
    return HTTPException(
        400,
        {
            "error": "ambiguous_name",
            "taxonomy": taxonomy,
            "name": name,
            "members": [
                {
                    "id": c.id,
                    "name": ct.identifier,
                    "display_name": ct.display_name,
                    "description": c.description,
                }
                for ct, c in matches
            ],
        },
    )


def resolve_single(
    db: Session, taxonomy: str, name: str, at_time: datetime | None = None
) -> tuple[ConceptTaxonomy, Concept]:
    """Resolve a name that must mean exactly one concept: 404 on none, 400 on a group.

    Everything addressed by name and not expressible for several concepts at once — a version
    selector, a draft, a write — goes through here, so an operation can never silently land on
    whichever group member happened to sort first.
    """
    matches = resolve_pointers(db, taxonomy, name, at_time)
    if not matches:
        raise HTTPException(404, f"Concept '{name}' not found in taxonomy '{taxonomy}'")
    if len(matches) > 1:
        raise ambiguous_name_error(taxonomy, name, matches)
    return matches[0]


def final_successor(db: Session, concept: Concept) -> int | None:
    """The end of a concept's successor chain, or None when it has no successor.

    Deprecating B in favour of C after A was already deprecated in favour of B leaves a chain;
    a client following `successor_id` wants where it ends, not the next hop. Cycle-safe, and
    tolerant of a successor id that no longer resolves (the forced reimport rebuilds the graph
    without them) — the last id that did resolve is returned.
    """
    seen = {concept.id}
    current = concept
    while current.successor_id is not None and current.successor_id not in seen:
        seen.add(current.successor_id)
        nxt = db.get(Concept, current.successor_id)
        if nxt is None:
            return current.successor_id
        current = nxt
    return None if current.id == concept.id else current.id


def concept_taxonomy_entries(db: Session, concept_id: int) -> list[dict]:
    """Every pointer of a concept, across taxonomies, as the detail page lists its names.

    Deprecated pointers are included and flagged: a renamed concept's old name is exactly what
    a reader arriving from an old link needs to see explained. Active first within a taxonomy,
    primary names before aliases, so a consumer taking the first entry per taxonomy gets the
    name the concept is introduced by.
    """
    rows = db.execute(
        select(ConceptTaxonomy, Taxonomy.key)
        .join(Taxonomy, Taxonomy.id == ConceptTaxonomy.taxonomy_id)
        .where(ConceptTaxonomy.concept_id == concept_id)
        .order_by(
            Taxonomy.key,
            ConceptTaxonomy.deprecated_at.is_not(None),
            func.coalesce(ConceptTaxonomy.relationship, "") == RELATIONSHIP_ALIAS,
            ConceptTaxonomy.identifier,
        )
    )
    return [{"taxonomy": key, **pointer_info(ct)} for ct, key in rows]


def display_pointer(
    db: Session, concept_id: int, at_time: datetime | None = None
) -> tuple[ConceptTaxonomy, str] | None:
    """The pointer an id-addressed response presents a concept under, with its taxonomy key.

    A concept may hold many names; a response addressed by id still has to pick one to put in
    `name`. Preference order: still active, in the server's default taxonomy, a primary name
    rather than an alias, then alphabetical — i.e. what an operator would call the concept.
    None only for a concept that has never been named.
    """
    at_time = at_time or _utcnow()
    row = db.execute(
        select(ConceptTaxonomy, Taxonomy.key)
        .join(Taxonomy, Taxonomy.id == ConceptTaxonomy.taxonomy_id)
        .where(ConceptTaxonomy.concept_id == concept_id)
        .order_by(
            and_(
                ConceptTaxonomy.deprecated_at.is_not(None),
                ConceptTaxonomy.deprecated_at <= at_time,
            ),
            Taxonomy.key != settings.default_taxonomy,
            func.coalesce(ConceptTaxonomy.relationship, "") == RELATIONSHIP_ALIAS,
            ConceptTaxonomy.identifier,
        )
        .limit(1)
    ).first()
    return (row[0], row[1]) if row is not None else None


def pointer_info(ct: ConceptTaxonomy) -> dict:
    """One pointer row as every response spells it out."""
    return {
        "id": ct.id,
        "identifier": ct.identifier,
        "display_name": ct.display_name,
        "relationship": ct.relationship,
        "origin": ct.origin,
        "created_at": ct.created_at,
        "deprecated_at": ct.deprecated_at,
    }


def group_size_index(
    db: Session, taxonomy_id: int, at_time: datetime
) -> dict[str, int]:
    """{identifier: how many concepts it names in this taxonomy at `at_time`}.

    Batched for the list endpoint, which needs the count on every row and would otherwise run
    a query per row. Only identifiers naming more than one concept are worth carrying, but the
    map is complete so a caller can look up any row's identifier directly.
    """
    rows = db.execute(
        select(
            ConceptTaxonomy.identifier,
            func.count(func.distinct(ConceptTaxonomy.concept_id)),
        )
        .where(ConceptTaxonomy.taxonomy_id == taxonomy_id, pointer_active_at(at_time))
        .group_by(ConceptTaxonomy.identifier)
    )
    return {ident: count for ident, count in rows}


def search_concepts(
    db: Session, q: str, *, limit: int = 20, at_time: datetime | None = None
) -> list[dict]:
    """Concepts whose pointers match `q` anywhere, grouped one entry per concept.

    Searches `identifier` and `display_name` across **every** taxonomy, because the pickers
    this feeds — "point this identifier at an existing concept", "which concept supersedes
    this one" — are asked in one taxonomy about a concept the operator knows by its name in
    another. Every matching pointer comes back under its concept, so the picker can show what
    the concept is already called; active pointers rank (and sort) ahead of deprecated ones.
    """
    at_time = at_time or _utcnow()
    term = f"%{q.strip().lower()}%"
    deprecated = ConceptTaxonomy.deprecated_at.is_not(None) & (
        ConceptTaxonomy.deprecated_at <= at_time
    )
    rows = db.execute(
        select(ConceptTaxonomy, Taxonomy.key, Concept)
        .join(Taxonomy, Taxonomy.id == ConceptTaxonomy.taxonomy_id)
        .join(Concept, Concept.id == ConceptTaxonomy.concept_id)
        .where(
            ConceptTaxonomy.created_at <= at_time,
            or_(
                func.lower(ConceptTaxonomy.identifier).like(term),
                func.lower(func.coalesce(ConceptTaxonomy.display_name, "")).like(term),
            ),
        )
        # Active first, then alphabetically — the order the concepts themselves come back in,
        # since a concept ranks where its best pointer does.
        .order_by(deprecated, ConceptTaxonomy.identifier, ConceptTaxonomy.id)
        # A broad term can match thousands of pointers; a picker needs the head of that list,
        # not all of it.
        .limit(max(limit, 1) * 10)
    )

    out: dict[int, dict] = {}
    for ct, tax_key, concept in rows:
        entry = out.get(concept.id)
        if entry is None:
            if len(out) >= limit:
                continue
            entry = out[concept.id] = {
                "concept_id": concept.id,
                "description": concept.description,
                "deprecated_at": concept.deprecated_at,
                "matches": [],
            }
        entry["matches"].append(
            {
                "taxonomy": tax_key,
                "identifier": ct.identifier,
                "display_name": ct.display_name,
                "deprecated_at": ct.deprecated_at,
            }
        )
    return list(out.values())


def get_source_by_key(db: Session, key: str) -> Source | None:
    return db.scalar(select(Source).where(Source.key == key))


def current_concept_version(db: Session, concept_id: int) -> int | None:
    return db.scalar(
        select(func.max(Config.version_no)).where(
            Config.concept_id == concept_id, Config.status == "published"
        )
    )


def latest_published_for_source(
    db: Session, concept_id: int, source_id: int
) -> Config | None:
    """The most recent published row for one (concept, source) — what a draft copies from."""
    return db.scalar(
        select(Config)
        .where(
            Config.concept_id == concept_id,
            Config.source_id == source_id,
            Config.status == "published",
            Config.version_no.isnot(None),
        )
        .order_by(Config.version_no.desc())
        .limit(1)
    )


def latest_published_per_source(
    db: Session,
    concept_id: int,
    *,
    at_version: int | None = None,
    at_time: datetime | None = None,
) -> list[Config]:
    """Latest published row per source, optionally bounded by version or timestamp.

    SELECT the max(version_no) per source under the bound, then fetch those rows.
    Portable across SQLite and Postgres.
    """
    filters = [
        Config.concept_id == concept_id,
        Config.status == "published",
        Config.version_no.isnot(None),
    ]
    if at_version is not None:
        filters.append(Config.version_no <= at_version)
    if at_time is not None:
        filters.append(Config.created_at <= at_time)

    mv = (
        select(Config.source_id, func.max(Config.version_no).label("mv"))
        .where(*filters)
        .group_by(Config.source_id)
        .subquery()
    )
    q = (
        select(Config)
        .join(mv, and_(Config.source_id == mv.c.source_id, Config.version_no == mv.c.mv))
        .where(Config.concept_id == concept_id, Config.status == "published")
    )
    return list(db.scalars(q))


def latest_published_index(
    db: Session, *, at_time: datetime | None = None, concept_ids: list[int] | None = None
) -> dict[int, list[Row]]:
    """Latest published row per (concept, source) for *all* concepts, grouped by concept_id.

    The batched counterpart to ``latest_published_per_source`` — one grouped query plus one
    fetch, instead of a subquery per concept. Used by the concepts list, which otherwise
    scales as N queries in the number of concepts.

    Selects only the columns the list renders (``source_id``, ``version_no``, ``type``) rather
    than whole ``Config`` rows, so the large ``json``/``py`` payloads are never read or
    deserialized. Each returned row exposes those three attributes.

    ``concept_ids`` narrows the batch to one page of a paginated list; an empty list means
    "no concepts asked for" and short-circuits.
    """
    if concept_ids is not None and not concept_ids:
        return {}
    filters = [Config.status == "published", Config.version_no.isnot(None)]
    if at_time is not None:
        filters.append(Config.created_at <= at_time)
    if concept_ids is not None:
        filters.append(Config.concept_id.in_(concept_ids))

    mv = (
        select(
            Config.concept_id,
            Config.source_id,
            func.max(Config.version_no).label("mv"),
        )
        .where(*filters)
        .group_by(Config.concept_id, Config.source_id)
        .subquery()
    )
    q = (
        select(
            Config.concept_id,
            Config.source_id,
            Config.version_no,
            Config.type,
        )
        .join(
            mv,
            and_(
                Config.concept_id == mv.c.concept_id,
                Config.source_id == mv.c.source_id,
                Config.version_no == mv.c.mv,
            ),
        )
        .where(Config.status == "published")
    )
    out: dict[int, list[Row]] = {}
    for row in db.execute(q):
        out.setdefault(row.concept_id, []).append(row)
    return out


def critical_warning(db: Session, concept_id: int, source_id: int, version_no: int | None):
    """If a later critical update supersedes this (source, version), return a warning."""
    if version_no is None:
        return None
    row = db.execute(
        select(Config.version_no, Config.message)
        .where(
            Config.concept_id == concept_id,
            Config.source_id == source_id,
            Config.status == "published",
            Config.change_type == "critical",
            Config.version_no > version_no,
            func.coalesce(Config.corrects_since_version_no, 1) <= version_no,
        )
        .order_by(Config.version_no)
        .limit(1)
    ).first()
    if row is None:
        return None
    return {
        "type": "critical_superseded",
        "corrected_in_version": row[0],
        "message": row[1],
    }


def config_files_index(db: Session, config_ids: list[int]) -> dict[int, list[Row]]:
    """The files several configs read, at the versions they pin: {config_id: [row, …]}.

    Each row carries `uuid`, `path`, `version_no`, `size`, `sha256` and `media_type` — enough
    for a client to pre-download everything a snippet might `getfile()` (it has the uuid the
    snippet names, the version to ask for, and the digest to verify) and to lay the bytes out
    at the path the definition was written against.

    Batched for the same reason `latest_published_index` is: a concept read resolves one config
    per source, and a per-config query would scale with the number of sources.
    """
    if not config_ids:
        return {}
    rows = db.execute(
        select(
            ConfigFileRef.config_id,
            SourceFile.uuid,
            ConfigFileRef.path,
            SourceFileVersion.version_no,
            Blob.size,
            Blob.sha256,
            Blob.media_type,
        )
        .select_from(ConfigFileRef)
        .join(SourceFileVersion, SourceFileVersion.id == ConfigFileRef.file_version_id)
        .join(SourceFile, SourceFile.id == SourceFileVersion.file_id)
        .join(Blob, Blob.id == SourceFileVersion.blob_id)
        .where(ConfigFileRef.config_id.in_(config_ids))
        .order_by(ConfigFileRef.path)
    )
    out: dict[int, list[Row]] = {}
    for row in rows:
        out.setdefault(row.config_id, []).append(row)
    return out


def file_download_url(concept_id: int, config: Config, file_uuid: str) -> str:
    """The GET path that serves one file of one config version.

    Addressed by concept id and file **uuid**: an identifier may name several concepts, and the
    uuid is what the snippet itself says, so a client holding a `getfile("…")` argument can
    build this URL without knowing anything else. The selector is pinned to what was actually
    served — the source's published `v`, or the `draft` id for a draft overlay — rather than
    echoing back a `date` the client may have asked with: a link that re-resolves as-of a moving
    lens would eventually hand out a *different* file than the response it came in.
    """
    selector = f"draft={config.id}" if config.status == "draft" else f"v={config.version_no}"
    return f"/concept/id/{concept_id}/files/{quote(file_uuid)}?{selector}"


# --- source file libraries ---------------------------------------------------------------
# A data file belongs to a source and is versioned there; a config version pins one of those
# versions. Everything that reads or writes that relationship lives below.


def current_file_version(db: Session, file_id: int) -> SourceFileVersion | None:
    """A file's current version — derived as MAX(version_no), never stored as a flag."""
    return db.scalar(
        select(SourceFileVersion)
        .where(SourceFileVersion.file_id == file_id)
        .order_by(SourceFileVersion.version_no.desc())
        .limit(1)
    )


def source_file_by_uuid(
    db: Session, source_id: int, file_uuid: str, *, include_deleted: bool = False
) -> SourceFile | None:
    """One file of one source, by its public uuid. Retired files are hidden unless asked for —
    a download of an old concept version still has to reach one, a new reference must not."""
    filters = [SourceFile.source_id == source_id, SourceFile.uuid == file_uuid]
    if not include_deleted:
        filters.append(SourceFile.deleted_at.is_(None))
    return db.scalar(select(SourceFile).where(*filters))


@dataclass
class FileRefs:
    """What a config's snippet asked for that could not be pinned.

    `unknown` is a `getfile("…")` naming no live file of the config's source — a mistyped or
    retired uuid. It is a warning on a draft and a refusal at publish: a published version whose
    snippet reaches for a file that does not exist is a definition that cannot run.
    `unresolvable` is a `getfile(...)` whose argument isn't a literal, which stays a warning
    forever — nothing here can prove such a call wrong (see ``api/pyrefs.py``).
    """

    unknown: list[str] = field(default_factory=list)
    unresolvable: list[str] = field(default_factory=list)


def sync_config_file_refs(db: Session, config: Config) -> FileRefs:
    """Recompute which file versions a config pins, from its ``py``. Returns what didn't resolve.

    The pins are **derived state**: the snippet is the only place a reference is written down,
    so this reads it (``api/pyrefs.py``) and rewrites the rows rather than merging into them —
    a uuid removed from the snippet has to lose its pin, and a diff-and-patch would have to
    reproduce that anyway.

    Each reference pins the file's *current* version at the moment of the call. On a draft that
    is every edit, so a draft always reads the newest bytes; on a publish it is once, and the
    row is then immutable history. This is never called on an already-published config: those
    are re-pinned only by minting a whole new version of them (see `cascade_file_version`).

    The config must already have an id — flush before calling.
    """
    uuids, unresolvable = pyrefs.referenced_uuids(config.python_code)
    known: dict[str, SourceFile] = {}
    if uuids:
        known = {
            f.uuid: f
            for f in db.scalars(
                select(SourceFile).where(
                    SourceFile.source_id == config.source_id,
                    SourceFile.uuid.in_(sorted(uuids)),
                    SourceFile.deleted_at.is_(None),
                )
            )
        }
    unknown = sorted(uuids - set(known))

    pinned: dict[str, int] = {}
    for file_uuid in sorted(known):
        file = known[file_uuid]
        version = current_file_version(db, file.id)
        if version is None:
            # A library row with no version at all: not usable, and indistinguishable to the
            # author from a uuid that names nothing.
            unknown.append(file_uuid)
            continue
        pinned[file.path] = version.id

    db.execute(delete(ConfigFileRef).where(ConfigFileRef.config_id == config.id))
    db.flush()
    for path, version_id in pinned.items():
        db.add(
            ConfigFileRef(
                config_id=config.id,
                file_version_id=version_id,
                path=path,
                origin=FILE_REF_GETFILE,
            )
        )
    db.flush()
    return FileRefs(unknown=sorted(set(unknown)), unresolvable=unresolvable)


def config_pinned_versions(db: Session, config_id: int) -> set[int]:
    """The `source_file_version` ids one config pins. The comparison the importer versions on."""
    return set(
        db.scalars(
            select(ConfigFileRef.file_version_id).where(ConfigFileRef.config_id == config_id)
        )
    )


def snippet_current_versions(db: Session, source_id: int, py: str | None) -> set[int]:
    """The file version ids a snippet's `getfile` calls resolve to *right now*.

    Paired with `config_pinned_versions` this answers "does the stored version already read
    what this snippet would read today" — which is what makes a replaced mapping table a
    changed definition even when not one character of the definition moved.
    """
    uuids, _ = pyrefs.referenced_uuids(py)
    if not uuids:
        return set()
    out: set[int] = set()
    for file in db.scalars(
        select(SourceFile).where(
            SourceFile.source_id == source_id,
            SourceFile.uuid.in_(sorted(uuids)),
            SourceFile.deleted_at.is_(None),
        )
    ):
        version = current_file_version(db, file.id)
        if version is not None:
            out.add(version.id)
    return out


def draft_file_state(db: Session, config: Config) -> tuple[list[dict], list[str]]:
    """``(files_changed_since_draft, unresolved_files)`` for one draft.

    Drafts are deliberately **not** cascaded into: a file upload rewrites published versions,
    which are the ones clients read, and silently re-pinning somebody's open work would change
    what their draft means while they were writing it. The drift is surfaced instead — the
    draft still reads `pinned_version` while the library has moved on to `current_version`, and
    publishing re-pins to whatever is current then.
    """
    rows = db.execute(
        select(
            SourceFile.id,
            SourceFile.uuid,
            ConfigFileRef.path,
            SourceFileVersion.version_no,
        )
        .select_from(ConfigFileRef)
        .join(SourceFileVersion, SourceFileVersion.id == ConfigFileRef.file_version_id)
        .join(SourceFile, SourceFile.id == SourceFileVersion.file_id)
        .where(ConfigFileRef.config_id == config.id)
        .order_by(ConfigFileRef.path)
    ).all()

    current: dict[int, int] = {}
    if rows:
        current = {
            file_id: version_no
            for file_id, version_no in db.execute(
                select(SourceFileVersion.file_id, func.max(SourceFileVersion.version_no))
                .where(SourceFileVersion.file_id.in_({r[0] for r in rows}))
                .group_by(SourceFileVersion.file_id)
            )
        }

    changed = [
        {
            "uuid": file_uuid,
            "path": path,
            "pinned_version": pinned,
            "current_version": current.get(file_id),
        }
        for file_id, file_uuid, path, pinned in rows
        if current.get(file_id) != pinned
    ]

    uuids, _ = pyrefs.referenced_uuids(config.python_code)
    live = (
        set(
            db.scalars(
                select(SourceFile.uuid).where(
                    SourceFile.source_id == config.source_id,
                    SourceFile.uuid.in_(sorted(uuids)),
                    SourceFile.deleted_at.is_(None),
                )
            )
        )
        if uuids
        else set()
    )
    return changed, sorted(uuids - live)


def next_published_version(
    db: Session, concept_id: int, versions: dict[int, int] | None = None
) -> int:
    """The next per-concept version number, counting what this pass has already handed out.

    `version_no` is a per-concept sequence shared by all of the concept's sources (see
    api/models.py), so the second source to define a name continues that concept's numbering
    instead of minting a second v1. `versions` is an optional cache for a batch that adds many
    rows without flushing between them (the importer's pass, a file cascade).
    """
    last = versions.get(concept_id) if versions is not None else None
    if last is None:
        last = db.scalar(
            select(func.max(Config.version_no)).where(
                Config.concept_id == concept_id, Config.status == "published"
            )
        ) or 0
    if versions is not None:
        versions[concept_id] = last + 1
    return last + 1


def mint_published_version(
    db: Session,
    *,
    concept_id: int,
    source_id: int,
    type_: str,
    definition: dict,
    py: str | None,
    change_type: str,
    message: str | None,
    validation_status: str | None,
    validation_report: dict | None,
    author_id: int | None,
    now: datetime,
    versions: dict[int, int] | None = None,
) -> Config:
    """Add one published `Config` row and return it, flushed so it has an id.

    The one place a published row is built outside a publish: the reference import mints them
    for what moved upstream, and the file cascade mints them for definitions whose data file
    was replaced. Both are the same event — something the definition depends on changed without
    a human editing it — and they have to produce identical rows, which is why this is a shared
    function rather than two that look alike.
    """
    config = Config(
        concept_id=concept_id,
        source_id=source_id,
        type=type_,
        json_def=definition,
        python_code=py,
        version_no=next_published_version(db, concept_id, versions),
        change_type=change_type,
        message=message,
        status="published",
        created_by=author_id,
        created_at=now,
        approved_by=author_id,
        approved_at=now,
        validation_status=validation_status,
        validation_report=validation_report,
    )
    db.add(config)
    db.flush()  # assign config.id so file pins can point at it
    return config


def configs_referencing_file(db: Session, file_id: int) -> list[Config]:
    """The **current published** configs of live concepts that read any version of this file.

    Current published only, on purpose. An older version pins the bytes it was published
    against and must keep them; a draft is somebody's open work and is warned about rather than
    rewritten. Deprecated concepts and auto-generated configs are out too — the first is not in
    circulation and the second has no version history to add to.

    That leaves exactly the set a new upload publishes a new version of, and it is deliberately
    the same set that makes a delete a 409: the way to retire a file is to take its readers out
    of use, and "still referenced" has to mean the same thing in both directions or a file
    could be permanently un-retirable by a concept nothing reads.
    """
    latest = (
        select(
            Config.concept_id,
            Config.source_id,
            func.max(Config.version_no).label("mv"),
        )
        .where(Config.status == "published", Config.version_no.isnot(None))
        .group_by(Config.concept_id, Config.source_id)
        .subquery()
    )
    ids = list(
        db.scalars(
            select(Config.id)
            .join(
                latest,
                and_(
                    Config.concept_id == latest.c.concept_id,
                    Config.source_id == latest.c.source_id,
                    Config.version_no == latest.c.mv,
                ),
            )
            .join(ConfigFileRef, ConfigFileRef.config_id == Config.id)
            .join(SourceFileVersion, SourceFileVersion.id == ConfigFileRef.file_version_id)
            .join(Concept, Concept.id == Config.concept_id)
            .where(
                Config.status == "published",
                SourceFileVersion.file_id == file_id,
                Concept.deprecated_at.is_(None),
                Config.type.not_in(settings.auto_generated_types)
                if settings.auto_generated_types
                else True,
            )
            .distinct()
            .order_by(Config.id)
        )
    )
    return [c for c in (db.get(Config, i) for i in ids) if c is not None]


def file_references(db: Session, file_id: int) -> list[dict]:
    """The concepts whose current published config reads this file, named the way a reviewer
    recognises them. The list a delete refuses with, and the one an upload dialog shows."""
    out = []
    for config in configs_referencing_file(db, file_id):
        found = display_pointer(db, config.concept_id)
        pointer, taxonomy = found if found is not None else (None, None)
        out.append(
            {
                "concept_id": config.concept_id,
                "taxonomy": taxonomy,
                "name": pointer.identifier if pointer is not None else None,
                "display_name": pointer.display_name if pointer is not None else None,
            }
        )
    return out


def cascade_file_version(
    db: Session, file: SourceFile, *, author_id: int | None, now: datetime
) -> list[dict]:
    """Publish a new version of every concept whose current config reads this file.

    This is what makes a file upload a *publishing* action rather than an edit, and why the
    route needs `can_publish`. A definition is its JSON, its snippet **and** the bytes that
    snippet reads: replacing the mapping table changes what the definition computes just as
    surely as rewriting the code would, so it earns a version, with the same
    ``change_type="sync"`` the reference import stamps on an upstream change.

    Who is in scope is `configs_referencing_file` — current published configs of live concepts,
    auto-generated types excluded. Skipped on top of that is a config that already pins the
    file's newest version, which is what keeps this idempotent — and what lets the reference
    import run this after its own upsert (api/importer.py) without double-versioning the
    definitions that upsert already brought forward.

    Every door a file comes in through ends here: an upload through the API, and a file the
    sidecar restaged. A definition reading replaced bytes is a changed definition no matter who
    replaced them, and a hand-authored snippet has no other way of ever hearing about it.

    Runs inside the caller's transaction: the version row and everything it cascades into land
    together or not at all, so there is no state where the library has moved on but the
    definitions reading it have not.
    """
    bumped: list[dict] = []
    versions: dict[int, int] = {}
    current = current_file_version(db, file.id)
    for config in configs_referencing_file(db, file.id):
        if current is not None and current.id in config_pinned_versions(db, config.id):
            # Already reading the newest bytes — a config the caller minted itself moments ago
            # (the import does exactly that), or a second cascade over the same upload. There
            # is nothing to bring forward, and a version whose only content is "no change" is
            # noise in a history clients read.
            continue
        fresh = mint_published_version(
            db,
            concept_id=config.concept_id,
            source_id=config.source_id,
            type_=config.type,
            definition=config.json_def,
            py=config.python_code,
            change_type="sync",
            message=settings.file_sync_message,
            # Nothing about the definition changed, so its validation verdict carries over
            # unchanged rather than being re-derived against a schema that may have moved.
            validation_status=config.validation_status,
            validation_report=config.validation_report,
            author_id=author_id,
            now=now,
            versions=versions,
        )
        sync_config_file_refs(db, fresh)
        found = display_pointer(db, config.concept_id)
        bumped.append(
            {
                "concept_id": config.concept_id,
                "name": found[0].identifier if found is not None else None,
                "version_no": fresh.version_no,
            }
        )
    return bumped


@dataclass
class FileUpload:
    """What one upload did: the version it landed on, and the concepts it published."""

    file: SourceFile
    version: SourceFileVersion
    # True when the bytes were identical to the current version: nothing was minted and
    # nothing cascaded. The idempotency that makes a re-run of the importer free.
    unchanged: bool
    bumped: list[dict] = field(default_factory=list)


def _mint_file_uuid(db: Session, source: Source, initial_path: str) -> str:
    """The identity a new library row gets: `uuid5(SOURCE_FILE_NS, "<source key>/<path>")`.

    Deterministic so that a fresh database, a second deployment and the offline corr-vars
    tooling all name the same file the same way — snippets hardcode the string.

    The one case it cannot serve is a seed that is already taken: a row created at this path
    and since **renamed** away from it still holds the derived uuid, and identity is frozen, so
    it cannot be handed to the new file. That row falls back to a random uuid — the reference
    is not computable offline any more, which is the honest answer, and it is logged.
    """
    derived = source_file_uuid(source.key, initial_path)
    taken = db.scalar(select(SourceFile.id).where(SourceFile.uuid == derived))
    if taken is None:
        return derived
    log.warning(
        "%s: the derived uuid for %r (%s) belongs to source_file #%d, which was renamed away "
        "from that path; minting a random uuid instead",
        source.key, initial_path, derived, taken,
    )
    return str(uuidlib.uuid4())


def _rename_file(db: Session, file: SourceFile, rel: str) -> None:
    """Move a library row to a new current path, refusing a collision with another file.

    `(source_id, path)` is unique over *current* paths — the historical names a file has been
    known by live on `source_file_version.path` and constrain nothing. A rename onto a path
    another row already holds is answered 409 here rather than left to blow up as an
    IntegrityError at commit; a retired row counts, because the constraint does not know about
    `deleted_at` and re-uploading to that path is how such a file is revived.
    """
    clash = db.scalar(
        select(SourceFile).where(
            SourceFile.source_id == file.source_id,
            SourceFile.path == rel,
            SourceFile.id != file.id,
        )
    )
    if clash is not None:
        retired = " (retired, but it still holds the path)" if clash.deleted_at else ""
        raise HTTPException(
            409,
            {
                "error": "file_path_taken",
                "message": (
                    f"'{rel}' is already the path of another file in this source "
                    f"(uuid {clash.uuid}){retired}; rename that one first."
                ),
                "uuid": clash.uuid,
            },
        )
    file.path = rel
    db.flush()


def store_file_version(
    db: Session,
    source: Source,
    path: str,
    data: bytes,
    *,
    message: str | None = None,
    media_type: str | None = None,
    author_id: int | None = None,
    now: datetime | None = None,
    cascade: bool = True,
    file_uuid: str | None = None,
) -> FileUpload:
    """Put bytes in a source's library at `path`, minting a version only if they differ.

    Creates the file when the path is new. Raises `files.FileError` for a path or a size the
    store refuses; callers turn that into a 400/413.

    `file_uuid` names an **existing** file to put the bytes on, whatever it is currently called.
    That is the replace flow, and it is what lets a new version *rename* the file: the identity
    is the uuid (see `models.source_file_uuid`), so `path` is free to move and the library, the
    file page and every manifest minted from now on show the most recent name. The rename is
    applied even when the bytes turn out to be identical — a rename is a rename. It is refused
    with a 409 when another live file of the source already holds the new path, which is the
    `(source_id, path)` unique constraint speaking about *current* paths.

    **Idempotent by digest.** Re-uploading the current bytes is not a version and does not
    cascade — which is what lets the importer re-walk the whole staged tree every poll and
    write nothing, and what keeps a user who uploads the same file twice from publishing every
    referencing concept twice.

    `cascade=False` is for the importer, and it defers the cascade rather than dropping it: the
    import ingests a source's files immediately before upserting that source's variables, and
    the upsert itself already mints a version for every *imported* definition whose files moved,
    so cascading here as well would give one changed file two versions in a single pass. The
    import runs `cascade_file_version` itself once the upsert is done, where the already-pinned
    guard skips what the upsert handled and only the configs it does not own are brought
    forward.

    Re-uploading to a retired file's path revives it. The alternative — refusing, because
    `(source_id, path)` is unique — would leave the path permanently unusable, and a retired
    file is not a tombstone anybody asked to keep.
    """
    rel = blobstore.normalize_path(path)
    blobstore.check_size(len(data))
    now = now or _utcnow()

    if file_uuid is not None:
        file = source_file_by_uuid(db, source.id, file_uuid, include_deleted=True)
        if file is None:
            raise HTTPException(404, f"No file '{file_uuid}' in the '{source.key}' library")
    else:
        file = db.scalar(
            select(SourceFile).where(SourceFile.source_id == source.id, SourceFile.path == rel)
        )
    blob = blobstore.store(db, data, blobstore.guess_media_type(rel, media_type))

    if file is None:
        file = SourceFile(
            source_id=source.id,
            # Derived from the path it is created under, and frozen there — see
            # `models.source_file_uuid` for why this is a contract with corr-vars.
            uuid=_mint_file_uuid(db, source, rel),
            path=rel,
            created_at=now,
            created_by=author_id,
        )
        db.add(file)
        db.flush()  # assign file.id before the version can point at it
        current = None
    else:
        current = current_file_version(db, file.id)
        if file.deleted_at is not None:
            file.deleted_at = None
            file.deleted_by = None
        if file.path != rel:
            _rename_file(db, file, rel)

    if current is not None and current.blob_id == blob.id:
        return FileUpload(file=file, version=current, unchanged=True)

    version = SourceFileVersion(
        file_id=file.id,
        version_no=(current.version_no if current is not None else 0) + 1,
        blob_id=blob.id,
        path=rel,
        message=message,
        created_by=author_id,
        created_at=now,
    )
    db.add(version)
    db.flush()

    bumped = cascade_file_version(db, file, author_id=author_id, now=now) if cascade else []
    return FileUpload(file=file, version=version, unchanged=False, bumped=bumped)


def build_sources_payload(
    db: Session, concept: Concept, configs: list[Config], *, detail: bool = True
) -> dict:
    """Assemble the {source_key: {json, py, files, version_info}} response block.

    `detail=False` is a caller holding `can_read` but not `can_read_detail`: the JSON definition
    and the file manifest still come through (that is the browsing the capability is meant to
    keep working), but the snippet is withheld. It is withheld *visibly* — `py` is null and
    `py_locked` is true — because a null `py` on its own is indistinguishable from a definition
    that has no Python at all, and silently resolving a concept to "no code" is exactly the
    fallback this project refuses. The bytes behind `files[].url` are refused outright, with a
    403 from the download route.
    """
    sources = {s.id: s for s in db.scalars(select(Source))}
    authors: dict[int | None, str | None] = {}
    pinned_files = config_files_index(db, [c.id for c in configs])
    out: dict = {}

    for c in configs:
        src = sources.get(c.source_id)
        if src is None:
            continue
        if c.created_by not in authors:
            u = db.get(User, c.created_by) if c.created_by else None
            authors[c.created_by] = u.username if u else None
        out[src.key] = {
            "json": c.json_def,
            "py": c.python_code if detail else None,
            "py_locked": (not detail) and bool(c.python_code),
            # The data files this version's `py` reads, at the versions it pins. This is the
            # manifest a client pre-downloads from before it runs the snippet: `uuid` is what
            # `getfile("…")` says, `version_no` is which bytes this definition means, `sha256`
            # verifies them, and `path` is where to lay them out.
            "files": [
                {
                    "uuid": f.uuid,
                    "path": f.path,
                    "version_no": f.version_no,
                    "size": f.size,
                    "sha256": f.sha256,
                    "media_type": f.media_type,
                    "url": file_download_url(concept.id, c, f.uuid),
                }
                for f in pinned_files.get(c.id, [])
            ],
            "version_info": {
                "source_version": c.version_no,
                "type": c.type,
                # Auto-generated (medication/laboratory) configs are read-only: not editable
                # or versioned through the browser. The frontend hides the draft/edit UI.
                "read_only": c.type in settings.auto_generated_types,
                "change_type": c.change_type,
                "message": c.message,
                "author": authors[c.created_by],
                "committed_at": c.created_at,
                "status": c.status,
                "warning": critical_warning(db, concept.id, c.source_id, c.version_no),
            },
        }
    return out
