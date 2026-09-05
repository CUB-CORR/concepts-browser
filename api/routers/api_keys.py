"""API-key management, gated by `create_api_key`.

A user mints keys tied to their own account for automation/CI. Keys are presented as bearer
tokens (see `deps.get_current_user`) and carry a subset of the owner's capabilities. Only the
hash is stored, so the plaintext is returned exactly once, at creation.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import security
from ..db import get_db
from ..deps import has_capability, require_capability
from ..models import ApiKey, User, _utcnow
from ..schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

# Minting/managing keys requires the create_api_key capability.
_can_create = require_capability(security.CREATE_API_KEY)


@router.get("", response_model=list[ApiKeyOut])
def list_keys(db: Session = Depends(get_db), user: User = Depends(_can_create)):
    """The current user's own keys, newest first."""
    return db.scalars(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    ).all()


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_key(
    body: ApiKeyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(_can_create),
):
    """Mint a key. Only admins choose scopes (bounded by their capabilities); everyone else
    gets a read-only key. `create_api_key` is never a scope — a key must not mint more keys.
    The plaintext key is in the response and cannot be retrieved again."""
    if has_capability(user, security.CAN_ADMIN):
        # Admins scope freely within what they hold, minus the key-minting capability itself.
        allowed = security.expand_capabilities(user.capabilities) - {security.CREATE_API_KEY}
        requested = set(body.scopes) - {security.CREATE_API_KEY}
        excess = sorted(requested - allowed)
        if excess:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Scopes exceed your capabilities: {excess}"
            )
        scopes = sorted(requested)
    else:
        # Non-admins can't scope keys: a key only ever reads. It reads as far as its owner
        # can, though — a key stuck at `can_read` while its owner may read code would 403 on
        # every snippet fetch, which is precisely what corr-vars mints keys for. One scope is
        # enough to say that: `can_read_detail` entails `can_read` (see the chain in
        # `api/security.py`), and it is entailed in turn by `can_edit` and up.
        detail = has_capability(user, security.CAN_READ_DETAIL)
        scopes = [security.CAN_READ_DETAIL if detail else security.CAN_READ]

    plaintext, key_hash, key_prefix = security.generate_api_key()
    expires_at = (
        _utcnow() + timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None
        else None
    )
    key = ApiKey(
        user_id=user.id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=scopes,
        expires_at=expires_at,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    # Serialize the stored row, then attach the one-time plaintext.
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=plaintext)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_key(
    key_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_can_create),
):
    """Revoke one of the current user's keys (idempotent). Takes effect on the next request."""
    key = db.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    key.revoked = True
    db.commit()
