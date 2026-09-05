"""LDAP authentication against the institutional directory.

The *only* per-app authn code: verify a username/password against the directory and return a
stable identity. Authorization stays in our DB. Kept isolated so a future IdP swap replaces
just this file.

Person DNs are not a fixed template (entries sit under varying OUs), so authentication is a
two-step search-then-bind:

1. Bind anonymously (a service account may be configured instead) and search
   ``(uid=<username>)`` to resolve the user's DN and read the immutable guid attribute
   (``ldap_guid_attribute``, e.g. ``entryUUID`` / ``objectGUID``).
2. Open a fresh connection and bind as that DN with the supplied password — success proves
   the credentials.

Institutional directories are typically reachable only from the deployment host, so this is
exercised end-to-end only on deploy; unit tests mock the ``ldap3`` connection.
"""
import base64
import json
import logging
import ssl
from dataclasses import dataclass, field

from ldap3 import ALL, ALL_ATTRIBUTES, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from .config import settings

log = logging.getLogger("concepts.ldap")


@dataclass(frozen=True)
class LdapIdentity:
    guid: str  # base64 of the directory's immutable guid attribute — our stable join key
    uid: str
    display_name: str | None
    # Full attribute snapshot from the search (attr -> list of values), for the profile page.
    # Binary values (e.g. the guid) come back base64-encoded; datetimes as ISO strings.
    profile: dict = field(default_factory=dict)


def _server() -> Server:
    if settings.ldap_tls_ca_certs_file:
        tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=settings.ldap_tls_ca_certs_file)
    else:
        # Development fallback only. Production MUST set ldap_tls_ca_certs_file.
        log.warning("LDAP TLS certificate validation is DISABLED (no ldap_tls_ca_certs_file)")
        tls = Tls(validate=ssl.CERT_NONE)
    # ldaps:// in the URI turns on SSL; get_info=ALL matches the working notebook probe.
    return Server(settings.ldap_server_uri, get_info=ALL, tls=tls)


def _identity_from_entry(entry, uid: str | None = None) -> LdapIdentity | None:
    """Build an :class:`LdapIdentity` from a directory search hit, or ``None`` if the entry
    lacks the stable guid we key users by.

    `uid` overrides the entry's ``uid`` attribute — the login path already knows the supplied
    username; the directory search reads the uid off the entry instead.
    """
    raw_guid = entry.entry_raw_attributes.get(settings.ldap_guid_attribute) or []
    if not raw_guid:
        return None
    # The guid may be binary; base64 the raw value for a deterministic string key.
    guid = base64.b64encode(raw_guid[0]).decode("ascii")

    if uid is None:
        uid_val = entry["uid"].value if "uid" in entry else None
        if isinstance(uid_val, list):
            uid_val = uid_val[0] if uid_val else None
        if not uid_val:
            return None
        uid = uid_val

    display = None
    if settings.ldap_display_name_attribute in entry:
        display = entry[settings.ldap_display_name_attribute].value
    # Full attribute snapshot for the profile page. entry_to_json handles the awkward types
    # (bytes → base64, datetimes → ISO strings) so it round-trips through our DB.
    profile = json.loads(entry.entry_to_json()).get("attributes", {})
    return LdapIdentity(guid=guid, uid=uid, display_name=display or uid, profile=profile)


def _search(search_filter: str, limit: int) -> list[LdapIdentity]:
    """Run a read-only directory search under the service/anonymous bind and map every hit to
    an :class:`LdapIdentity`. Never binds as the target — this is directory *read* (for
    proactive provisioning), not password verification. Returns ``[]`` on error.
    """
    server = _server()
    try:
        with Connection(
            server,
            user=settings.ldap_search_bind_dn or None,
            password=settings.ldap_search_bind_password or None,
            auto_bind=True,
        ) as conn:
            conn.search(
                search_base=settings.ldap_search_base,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=[ALL_ATTRIBUTES, settings.ldap_guid_attribute],
                size_limit=limit,
            )
            identities = []
            for entry in conn.entries:
                identity = _identity_from_entry(entry)
                if identity is not None:
                    identities.append(identity)
            return identities
    except LDAPException:
        log.exception("LDAP directory search failed for filter %r", search_filter)
        return []


def search_directory(query: str, limit: int | None = None) -> list[LdapIdentity]:
    """Find people whose uid or common name contains `query`, for an admin pre-provisioning a
    user who has never logged in. Read-only; returns up to `limit` identities (defaults to
    ``ldap_search_size_limit``), empty on a blank query or error.
    """
    query = (query or "").strip()
    if not query:
        return []
    if limit is None or limit > settings.ldap_search_size_limit:
        limit = settings.ldap_search_size_limit
    search_filter = settings.ldap_search_filter.format(query=escape_filter_chars(query))
    return _search(search_filter, limit)


def resolve(username: str) -> LdapIdentity | None:
    """Resolve one exact `uid` to its directory identity (guid + display name + profile),
    without verifying a password. Used when provisioning: the admin picks a uid and we read
    the authoritative guid/profile straight from the directory. Rejects 0 or >1 matches.
    """
    username = (username or "").strip()
    if not username:
        return None
    search_filter = settings.ldap_uid_filter.format(username=escape_filter_chars(username))
    hits = _search(search_filter, limit=2)
    if len(hits) != 1:
        log.warning("LDAP resolve for uid %r returned %d matches (need exactly 1)", username, len(hits))
        return None
    return hits[0]


def authenticate(username: str, password: str) -> LdapIdentity | None:
    """Return the LDAP identity for valid credentials, else ``None``.

    Rejects empty credentials up front: a DN with an empty password is an *unauthenticated
    bind* that servers accept as success, so it must never count as authentication.
    """
    if not username or not password:
        return None

    server = _server()
    try:
        # 1. Service/anonymous bind → resolve the DN and read the stable guid.
        with Connection(
            server,
            user=settings.ldap_search_bind_dn or None,
            password=settings.ldap_search_bind_password or None,
            auto_bind=True,
        ) as search_conn:
            found = search_conn.search(
                search_base=settings.ldap_search_base,
                search_filter=settings.ldap_uid_filter.format(
                    username=escape_filter_chars(username)
                ),
                search_scope=SUBTREE,
                # Pull every attribute so the profile page can show the full directory entry;
                # the guid is requested explicitly in case it's not returned by the "*" wildcard.
                attributes=[ALL_ATTRIBUTES, settings.ldap_guid_attribute],
            )
            # Exactly one match, or we refuse to guess which account to authenticate.
            if not found or len(search_conn.entries) != 1:
                log.warning(
                    "LDAP uid search for %r returned %d entries (need exactly 1): %s",
                    username,
                    len(search_conn.entries),
                    [e.entry_dn for e in search_conn.entries],
                )
                return None
            entry = search_conn.entries[0]
            user_dn = entry.entry_dn
            log.info("LDAP resolved %r to DN %s", username, user_dn)
            # Key on the supplied username (the login uid), not the entry's uid attribute.
            identity = _identity_from_entry(entry, uid=username)
            if identity is None:
                log.warning(
                    "LDAP user %r has no %s attribute", username, settings.ldap_guid_attribute
                )
                return None
            log.info("LDAP display name for %r: %r", username, identity.display_name)

        # 2. Re-bind as the resolved DN with the supplied password to verify it.
        bind_conn = Connection(server, user=user_dn, password=password, auto_bind=False)
        try:
            if not bind_conn.bind():
                log.warning(
                    "LDAP password bind as %s failed: %s", user_dn, bind_conn.result
                )
                return None
        finally:
            bind_conn.unbind()

        return identity
    except LDAPException:
        log.exception("LDAP authentication error for %r", username)
        return None
