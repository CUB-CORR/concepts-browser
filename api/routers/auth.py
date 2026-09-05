from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, ldap_auth, security
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, has_capability
from ..models import DEPRECATION_PENDING, Config, DeprecationRequest, User
from ..schemas import (
    LoginRequest,
    PendingCountsOut,
    ProfileOut,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
_DISABLED = HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")


@router.post(
    "/login",
    response_model=TokenResponse,
    openapi_extra={"x-public": True},
    summary="Log in",
)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    # Every attempt is an audit event — including the ones that fail below, which is why this
    # is marked up front, before we know the outcome. The middleware records the row with the
    # response status, so a rejected login lands as a 401/403 row against the attempted name.
    audit.mark_login(request, username=body.username)

    # 1. Local bcrypt path — for the bootstrap/local admin (LDAP users have an empty hash,
    #    so this is skipped for them and falls through to LDAP).
    user = db.scalar(select(User).where(User.username == body.username))
    if user is not None and user.password_hash and security.verify_password(
        body.password, user.password_hash
    ):
        if not user.is_active:
            raise _DISABLED
        token, expires = security.create_access_token(user)
        audit.mark_login(request, username=body.username, user_id=user.id)
        return TokenResponse(access_token=token, expires_at=expires)

    # 2. LDAP path — bind against the directory; on success upsert by the stable LdapGUID.
    #    A brand-new user is provisioned with NO capabilities (pending admin approval) but
    #    still gets a token, so the frontend can show the "approval pending" state.
    if settings.ldap_enabled:
        identity = ldap_auth.authenticate(body.username, body.password)
        if identity is not None:
            user = _upsert_ldap_user(db, identity)
            if not user.is_active:
                raise _DISABLED
            token, expires = security.create_access_token(user)
            db.commit()  # assigns user.id for a first-time LDAP user
            audit.mark_login(request, username=body.username, user_id=user.id)
            return TokenResponse(access_token=token, expires_at=expires)

    raise _INVALID


def _upsert_ldap_user(db: Session, identity: ldap_auth.LdapIdentity) -> User:
    """Find the user by stable LdapGUID (never the username), creating one with empty caps on
    first login; refresh the username/display_name labels on every login."""
    user = db.scalar(select(User).where(User.ldap_guid == identity.guid))
    if user is None:
        user = User(
            username=identity.uid,
            ldap_guid=identity.guid,
            display_name=identity.display_name,
            ldap_profile=identity.profile,
            password_hash="",  # no local password for LDAP users
            capabilities=[],
            is_active=True,
        )
        db.add(user)
        db.flush()  # assign user.id for the token's `sub`
    else:
        user.username = identity.uid
        user.display_name = identity.display_name
        user.ldap_profile = identity.profile
    # TEMPORARY (ldap_auto_grant_read): the directory itself is the read gate, so a user with
    # nothing granted yet gets `can_read` here rather than waiting for approval. Existing
    # grants are never touched; note that while this is on, stripping every capability no
    # longer locks a user out — deactivate the account instead.
    #
    # `can_read` and nothing else, deliberately: an unreviewed directory user browses concepts
    # and their JSON definitions, and gets an explicit refusal on the `py` snippets and the
    # file bytes until somebody grants `can_read_detail`.
    if settings.ldap_auto_grant_read and not user.capabilities:
        user.capabilities = [security.CAN_READ]
    return user


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get(
    "/pending-counts",
    response_model=PendingCountsOut,
    summary="What is waiting for the signed-in user",
)
def pending_counts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The navigation badge counts, in one call the root layout makes on every page render.

    Each half is gated by the capability that opens the page it points at — `can_publish` for
    the review queues (`GET /drafts` + `GET /deprecation-requests`), `can_admin` for the
    approval queue (`GET /admin/users`) — so this never tells a caller the size of a queue
    they may not open. A queue they may not open comes back as null, not zero.
    """
    review = None
    if has_capability(user, security.CAN_PUBLISH):
        drafts = db.scalar(
            select(func.count()).select_from(Config).where(Config.status == "draft")
        )
        requests = db.scalar(
            select(func.count())
            .select_from(DeprecationRequest)
            .where(DeprecationRequest.status == DEPRECATION_PENDING)
        )
        review = (drafts or 0) + (requests or 0)

    pending_users = None
    if has_capability(user, security.CAN_ADMIN):
        # Pending = no capabilities, exactly as the user table labels it. Deactivated accounts
        # are left out: deactivating is how an admin turns a request down, and a badge that
        # counted those could never be cleared.
        pending_users = sum(
            1
            for caps in db.scalars(select(User.capabilities).where(User.is_active.is_(True)))
            if not caps
        )

    return PendingCountsOut(review=review, pending_users=pending_users)


@router.get("/users/{username}/profile", response_model=ProfileOut)
def user_profile(
    username: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Account state, capabilities and the full LDAP attribute snapshot for one user. A user
    may view their own profile; admins may view anyone's."""
    is_admin = has_capability(user, security.CAN_ADMIN)
    if user.username != username and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to view this profile")
    target = (
        user
        if user.username == username
        else db.scalar(select(User).where(User.username == username))
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return target
