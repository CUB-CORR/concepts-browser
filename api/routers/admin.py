"""Admin user-management API. Gated by `can_admin`; backs the `routes/users` page.

Lists users (including pending, empty-capability ones), and lets an admin grant/revoke
capabilities and deactivate/reactivate accounts. Authorization is our DB's job — there is no
LDAP attribute governing what a user may do here. An admin also sees and manages any user's API
keys from that user's profile page: re-scope or revoke them.

Approving a user (their first capability, granted here or at provisioning time) notifies them
by email — see `api/mailer.py`. The send is a background task: it must not delay the admin's
request, and a mail failure must not fail the approval.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ldap_auth, mailer, security
from ..config import settings
from ..db import get_db
from ..deps import require_capability
from ..models import ApiKey, User
from ..schemas import (
    AdminApiKeyUpdate,
    AdminUserOut,
    AdminUserUpdate,
    ApiKeyOut,
    DirectoryEntry,
    ProvisionUserRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Every endpoint here requires can_admin.
_admin = require_capability(security.CAN_ADMIN)


@router.get("/users", response_model=list[AdminUserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(_admin)):
    # Pending (empty-cap) users first, then by username, so approvals surface at the top.
    users = db.scalars(select(User).order_by(User.username)).all()
    users.sort(key=lambda u: (bool(u.capabilities), u.username.lower()))
    return users


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    body: AdminUserUpdate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # "Approved" is the pending → capable transition, so a later capability edit doesn't
    # re-notify. Read before the assignment below overwrites it.
    was_pending = not user.capabilities

    # Guard against an admin locking themselves out: they can't drop their own admin
    # capability or deactivate their own account (another admin must do it).
    if user.id == admin.id:
        if body.capabilities is not None and security.CAN_ADMIN not in body.capabilities:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "You cannot remove your own admin capability"
            )
        if body.is_active is False:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account"
            )

    if body.capabilities is not None:
        user.capabilities = body.capabilities  # already validated + normalized by the schema
        _raise_unpinned_keys(db, user)
    if body.is_active is not None:
        user.is_active = body.is_active

    db.commit()
    db.refresh(user)  # reloads the columns the approval email reads off the detached instance

    if was_pending and user.capabilities:
        background.add_task(mailer.send_approval_email, user)
    return user


def _raise_unpinned_keys(db: Session, user: User) -> None:
    """Carry a promotion over to the user's own keys. A key the user minted holds the owner
    default (`security.default_key_scopes`), so promoting a `can_read` user to read code would
    otherwise leave every key they already have unable to — corr-vars would keep failing until
    they minted a new one. Pinned keys carry an admin's explicit choice and are left alone."""
    keys = db.scalars(
        select(ApiKey).where(
            ApiKey.user_id == user.id,
            ApiKey.revoked.is_(False),
            ApiKey.scopes_pinned.is_(False),
        )
    )
    for key in keys:
        raised = security.raised_key_scopes(key.scopes, user.capabilities)
        if raised is not None:
            key.scopes = raised


def _user_key(db: Session, user_id: int, key_id: int) -> ApiKey:
    key = db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id))
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    return key


@router.get("/users/{user_id}/api-keys", response_model=list[ApiKeyOut])
def list_user_keys(user_id: int, db: Session = Depends(get_db), _: User = Depends(_admin)):
    """Every key the user holds, revoked ones included, newest first."""
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return db.scalars(
        select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
    ).all()


@router.patch("/users/{user_id}/api-keys/{key_id}", response_model=ApiKeyOut)
def rescope_user_key(
    user_id: int,
    key_id: int,
    body: AdminApiKeyUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(_admin),
):
    """Re-scope a key in place, so its holder keeps the same secret. Scopes are bounded by the
    owner's capabilities exactly as at minting; null resets to the owner default and unpins."""
    owner = db.get(User, user_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    key = _user_key(db, user_id, key_id)
    if key.revoked:
        raise HTTPException(status.HTTP_409_CONFLICT, "API key is revoked")

    if body.scopes is None:
        key.scopes = security.default_key_scopes(owner.capabilities)
        key.scopes_pinned = False
    else:
        allowed = security.expand_capabilities(owner.capabilities) - {security.CREATE_API_KEY}
        requested = set(body.scopes) - {security.CREATE_API_KEY}
        excess = sorted(requested - allowed)
        if excess:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Scopes exceed the owner's capabilities: {excess}"
            )
        key.scopes = sorted(requested)
        key.scopes_pinned = True
    db.commit()
    db.refresh(key)
    return key


@router.delete("/users/{user_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_key(
    user_id: int, key_id: int, db: Session = Depends(get_db), _: User = Depends(_admin)
):
    """Revoke someone's key (idempotent). Takes effect on the next request."""
    _user_key(db, user_id, key_id).revoked = True
    db.commit()


@router.get("/directory", response_model=list[DirectoryEntry])
def search_directory(
    q: str = Query(..., min_length=1, description="substring of a uid or common name"),
    db: Session = Depends(get_db),
    _: User = Depends(_admin),
):
    """Search the LDAP directory by uid/common name so an admin can proactively add a user who
    has never logged in. Each hit is flagged with `user_id` when the person is already in our
    DB (matched on the stable LDAP guid)."""
    if not settings.ldap_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "LDAP is not enabled")

    identities = ldap_auth.search_directory(q)
    if not identities:
        return []
    # Which of these are already provisioned? One query keyed on the stable guid.
    guids = [i.guid for i in identities]
    existing = {
        u.ldap_guid: u.id
        for u in db.scalars(select(User).where(User.ldap_guid.in_(guids)))
    }
    return [
        DirectoryEntry(
            ldap_guid=i.guid,
            username=i.uid,
            display_name=i.display_name,
            user_id=existing.get(i.guid),
        )
        for i in identities
    ]


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def provision_user(
    body: ProvisionUserRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(_admin),
):
    """Proactively add an LDAP user and grant them capabilities before their first login. The
    uid is re-resolved against the directory (we never trust a client-supplied guid), so the
    row is keyed on the same stable guid a later login would upsert onto.

    Provisioning *with* capabilities is an approval — the user is told by email, exactly as if
    an admin had approved them after a first login. Provisioning with none is not, and stays
    silent until they're granted something."""
    if not settings.ldap_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "LDAP is not enabled")

    identity = ldap_auth.resolve(body.username)
    if identity is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No unique directory entry for uid {body.username!r}"
        )

    # Idempotency guard: a login (or an earlier provision) may already own this guid.
    if db.scalar(select(User).where(User.ldap_guid == identity.guid)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already provisioned")

    user = User(
        username=identity.uid,
        ldap_guid=identity.guid,
        display_name=identity.display_name,
        ldap_profile=identity.profile,
        password_hash="",  # no local password for LDAP users
        capabilities=body.capabilities,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if user.capabilities:
        background.add_task(mailer.send_approval_email, user)
    return user
