import hmac

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, security
from .config import settings
from .db import get_db
from .models import ApiKey, User, _utcnow

_bearer = HTTPBearer(auto_error=True)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer credential to a live `User`. The credential is either a JWT or an API
    key (distinguished by the `cak_` prefix); both paths return the owner with the capabilities
    that are authoritative *right now* (API keys are further narrowed to their scopes).

    Resolving the caller is also what makes the request auditable: `audit.mark_user` tags it so
    the audit middleware records a row for it (see `api/audit.py`)."""
    token = creds.credentials
    if token.startswith(security.API_KEY_PREFIX):
        user = _authenticate_api_key(token, db)
        audit.mark_user(request, user_id=user.id, auth_method="api_key")
        return user

    try:
        payload = security.decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    audit.mark_user(request, user_id=user.id, auth_method="jwt")
    return user


def _authenticate_api_key(token: str, db: Session) -> User:
    """Resolve an API key to its owner. Rejects revoked/expired keys and inactive owners; caps
    are recomputed live as `scopes ∩ owner.capabilities` so a key can never exceed what the
    owner currently holds. Stamps `last_used_at` for the usage view."""
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == security.hash_api_key(token)))
    if key is None or key.revoked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    if key.expires_at is not None and key.expires_at < _utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key expired")

    owner = db.get(User, key.user_id)
    if owner is None or not owner.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    # Narrow to the key's scopes, bounded by the owner's live capabilities. Both sides are
    # expanded first, so entailment applies to each: a key scoped `can_publish` covers a
    # `can_read_detail` check, while a key scoped `can_read` stays a reader however much its
    # owner holds. Scopes still narrow; they just narrow along the chain.
    effective = sorted(
        security.expand_capabilities(key.scopes) & security.expand_capabilities(owner.capabilities)
    )

    key.last_used_at = _utcnow()
    db.commit()  # persist usage; this also expires `owner`'s attributes

    # Return a detached owner carrying the *effective* caps: reload every column so the detached
    # instance is fully populated (downstream reads like `user.id` won't hit the DB), then
    # override capabilities in memory so the narrowed set is never flushed back to the row.
    db.refresh(owner)
    db.expunge(owner)
    owner.capabilities = effective
    return owner


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    """Guard the ops routes the vars-sync sidecar calls (see `api/routers/internal.py`).

    Not a user credential: there is no account behind it and nothing to audit as a person.
    The shared secret is the whole authorization, so it is compared in constant time, and a
    deployment that configured none gets a 404 rather than an endpoint advertising that it
    exists and is merely locked.
    """
    if not settings.internal_token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if not x_internal_token or not hmac.compare_digest(
        x_internal_token, settings.internal_token
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")


def has_capability(user: User, capability: str) -> bool:
    """Does `user` hold `capability` right now, directly or by entailment?

    Every capability check in this service goes through here (or through the dependency
    factories below, which are this predicate wearing a 403). `security.expand_capabilities`
    is what makes it a hierarchy: a chain capability covers the lesser ones, `can_admin`
    covers everything. Never test membership in `user.capabilities` at a call site — that is
    the one way to end up stricter than the rest of the API.

    Exposed on its own for the routes that must *shape* a response rather than refuse it —
    `can_read_detail` on the concept read, which stays 200 for a `can_read` browser and marks
    the withheld snippet instead.
    """
    return capability in security.expand_capabilities(user.capabilities)


def require_capability(capability: str):
    """Dependency factory: 403 unless the user has `capability` (directly, by entailment, or
    as admin)."""

    def _dep(user: User = Depends(get_current_user)) -> User:
        if not has_capability(user, capability):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Missing capability: {capability}"
            )
        return user

    return _dep
