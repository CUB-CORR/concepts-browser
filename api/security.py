import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

# Capabilities. CAN_ADMIN implies all others (see deps.require_capability).
# "Approved" = has >=1 capability; a freshly provisioned LDAP user has none (pending review).
#
# Most capabilities are *incremental*: they form one chain (see CAPABILITY_CHAIN below), and
# holding one entails every lesser one. Only `create_api_key`, `add_project` and `can_admin`
# sit outside it, as independent flags.
CAN_READ = "can_read"
# May read what a concept *computes*, not just what it declares: the `py` snippets and the bytes
# of the data files those snippets read. `can_read` alone stops at the JSON definition — see
# `deps.has_capability` and the routes in `routers/files.py` / `routers/source_files.py`.
CAN_READ_DETAIL = "can_read_detail"
CAN_EDIT = "can_edit"
CAN_PUBLISH = "can_publish"
CREATE_API_KEY = "create_api_key"
# May create projects. Editing a project is governed by lead membership, not this capability.
ADD_PROJECT = "add_project"
CAN_ADMIN = "can_admin"
# Chain first, weakest to strongest, then the independent flags — the order the admin UI
# lists them in.
ALL_CAPABILITIES = [
    CAN_READ,
    CAN_READ_DETAIL,
    CAN_EDIT,
    CAN_PUBLISH,
    CREATE_API_KEY,
    ADD_PROJECT,
    CAN_ADMIN,
]


# The incremental chain, weakest first. Holding one entails every capability to its left:
# an editor can read what they edit, a publisher can review what they release. Storage is
# untouched by this — a row may hold `can_publish` alone; entailment is evaluation-time only,
# resolved by `expand_capabilities` and never written back.
#
# Everything *not* in the chain keeps independent semantics: `create_api_key` and `add_project`
# are orthogonal permissions (nobody gets to mint keys by being able to publish), and
# `can_admin` is the one blanket flag — it implies all of them.
CAPABILITY_CHAIN = [CAN_READ, CAN_READ_DETAIL, CAN_EDIT, CAN_PUBLISH]


def expand_capabilities(caps) -> set[str]:
    """Resolve implied capabilities: `can_admin` grants everything, and every chain capability
    grants the lesser ones (see `CAPABILITY_CHAIN`).

    The single place the hierarchy is interpreted. `deps.has_capability` asks it whether a
    subject holds something; `deps._authenticate_api_key` expands *both* sides before
    intersecting, so a key scoped `can_publish` reads code while a key scoped `can_read`
    still does not, whatever its owner holds.
    """
    caps = set(caps or [])
    if CAN_ADMIN in caps:
        return set(ALL_CAPABILITIES)
    highest = max((CAPABILITY_CHAIN.index(c) for c in caps if c in CAPABILITY_CHAIN), default=-1)
    return caps | set(CAPABILITY_CHAIN[: highest + 1])


# API keys are presented as bearer tokens; this prefix lets `deps` tell a key from a JWT.
API_KEY_PREFIX = "cak_"


def generate_api_key() -> tuple[str, str, str]:
    """Mint a new API key. Returns `(plaintext, key_hash, key_prefix)` — the plaintext is shown
    to the user exactly once; we persist only the hash and a display prefix."""
    plaintext = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_api_key(plaintext), plaintext[:12]


def hash_api_key(key: str) -> str:
    """sha256 hex of an API key. Fast (the key is a high-entropy secret, not a password) and
    deterministic, so a presented key can be looked up by hash."""
    return hashlib.sha256(key.encode()).hexdigest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(user) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=settings.token_expire_hours)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "caps": list(user.capabilities or []),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
