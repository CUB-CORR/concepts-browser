"""Outbound email over Exchange Web Services.

The *only* mail transport: EWS, sending as a shared functional mailbox. Such mailboxes are
typically Exchange accounts (the login IT issues for Outlook/OWA) rather than SMTP submission
accounts, so we talk EWS — the same protocol Outlook uses — not SMTP. Kept isolated (like
`ldap_auth`) so a future transport swap replaces just this file.

Recipients are never stored by us — they are read from the `mail` attribute of the LDAP
snapshot we already keep on the user (`User.ldap_profile`), so a person who has no directory
mail address simply gets no email.

Sending must never break the action that triggered it: every entry point here swallows its
errors and returns a bool. Callers hand the send to a background task so the request doesn't
wait on the mail server.

Every attempt — sent, failed, or never tried — lands in the audit log as an `email` event, so
"was this person actually told?" is answerable after the fact.
"""
import logging
import threading
from urllib.parse import quote

from exchangelib import (
    BASIC,
    DELEGATE,
    DIGEST,
    NTLM,
    Account,
    Configuration,
    Credentials,
    HTMLBody,
    Mailbox,
    Message,
)
from exchangelib.protocol import BaseProtocol
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, usage
from .config import settings
from .db import SessionLocal
from .models import (
    EMAIL_FAILED,
    EMAIL_SENT,
    EMAIL_SKIPPED,
    EVENT_API_CALL,
    AuditLog,
    ConceptUsage,
    ProjectLead,
    User,
)

log = logging.getLogger("concepts.mail")

# `EXCHANGE_AUTH_TYPE` spellings → what exchangelib calls them. Anything else (including the
# empty string) means "probe the server for it".
_AUTH_TYPES = {"ntlm": NTLM, "basic": BASIC, "digest": DIGEST}

# `AuditLog.email_kind` for each message we can send. The stable name of the message, as
# opposed to its subject line, which is prose.
EMAIL_KIND_APPROVAL = "approval"
EMAIL_KIND_PUBLISH_ALERT = "publish_alert"


def _attr(profile: dict | None, name: str) -> str | None:
    """One LDAP attribute out of the stored snapshot. Values are lists (`{"mail": [...]}`),
    but tolerate a bare string in case the directory returns a single-valued attribute flat."""
    value = (profile or {}).get(name)
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def recipient_for(user: User) -> str | None:
    """The user's directory email address, or ``None`` if the directory has none for them."""
    return _attr(user.ldap_profile, "mail")


def greeting_name(user: User) -> str:
    """How we address the person: the directory `cn`, normalized to natural order.

    Directories commonly store `cn` as "Lastname, Firstname"; a salutation needs
    "Firstname Lastname", so a single comma is flipped. Falls back to the display name,
    then the uid.
    """
    name = _attr(user.ldap_profile, "cn") or user.display_name or user.username
    last, comma, first = name.partition(",")
    if comma and "," not in first:
        return f"{first.strip()} {last.strip()}".strip()
    return name


def connect(username: str | None = None, password: str | None = None) -> Account:
    """Open the functional mailbox over EWS. Raises if the server, the credentials or the
    delegate rights are wrong — callers decide what that means.

    The login account (`EXCHANGE_USERNAME`) and the mailbox (`EXCHANGE_MAILBOX`) are
    separate on purpose: functional mailboxes are opened via *delegate* access, which is also
    why autodiscover is off (the login name need not be an address, so there is nothing to
    discover from — the EWS endpoint is derived from `EXCHANGE_SERVER` instead).
    """
    # Class-level, i.e. the timeout for every EWS request exchangelib makes. Its default is two
    # minutes; a background task blocking that long on a wedged server is not worth waiting for.
    BaseProtocol.TIMEOUT = settings.exchange_timeout
    config = Configuration(
        server=settings.exchange_server,
        credentials=Credentials(
            username if username is not None else settings.exchange_username,
            password if password is not None else settings.exchange_password,
        ),
        auth_type=_AUTH_TYPES.get(settings.exchange_auth_type.strip().lower()),
    )
    return Account(
        primary_smtp_address=settings.exchange_mailbox,
        config=config,
        autodiscover=False,
        access_type=DELEGATE,
    )


# The mailbox session, shared by every send. Opening one costs a version probe and an auth
# handshake, so it is built once and reused; sends run in background threads, hence the lock.
_account: Account | None = None
_account_lock = threading.Lock()


def _account_for_send() -> Account:
    global _account
    with _account_lock:
        if _account is None:
            _account = connect()
            log.info(
                "opened %s on %s as %s",
                settings.exchange_mailbox,
                settings.exchange_server,
                settings.exchange_username,
            )
        return _account


def _drop_account() -> None:
    """Forget the cached session so the next send reconnects. A password change, a dropped
    session or a server restart shouldn't need a redeploy to recover from."""
    global _account
    with _account_lock:
        _account = None


def _send(to: str, subject: str, text_body: str, html_body: str | None = None) -> tuple[str, str | None]:
    """Deliver one message. Never raises — an approval must still succeed when the mail server
    is down.

    Returns the `email_status` the audit log records, plus a short reason when the message did
    not go out. A disabled mailer is a *skip* (the expected state locally and in tests); an
    enabled one that can't send is a *failure*, because it was supposed to.
    """
    if not settings.exchange_enabled:
        log.info("Exchange disabled; not sending %r to %s", subject, to)
        return EMAIL_SKIPPED, "mail_disabled"
    if not settings.exchange_password:
        log.error("Exchange is enabled but EXCHANGE_PASSWORD is unset; cannot send %r", subject)
        return EMAIL_FAILED, "no_exchange_password"

    try:
        account = _account_for_send()
        message = Message(
            account=account,
            subject=subject,
            # An EWS message carries one body, not a multipart alternative: HTML if we have it,
            # otherwise the plain-text rendering, which stays the body of last resort.
            body=HTMLBody(html_body) if html_body else text_body,
            to_recipients=[Mailbox(email_address=to)],
        )
        # Not plain send(): a copy lands in the functional mailbox's Sent Items, so what we told
        # someone is visible to whoever opens the shared mailbox, not only in our audit log.
        message.send_and_save()
    except Exception as exc:  # noqa: BLE001 — see the module docstring: a send may never propagate
        # The session may be the thing that broke (expired auth, restarted server); throw it
        # away so a retry is a fresh connection rather than the same dead one.
        _drop_account()
        log.exception("failed to send %r to %s", subject, to)
        return EMAIL_FAILED, type(exc).__name__

    log.info("sent %r to %s", subject, to)
    return EMAIL_SENT, None


APPROVAL_SUBJECT = f"{settings.app_display_name} — access approved"


def render_approval_email(user: User) -> tuple[str, str]:
    """The approval message's text and HTML bodies.

    Split out from the send so `api/mail_check.py` can put the *real* message through a live
    Exchange session without also writing an audit row for a user nobody approved.
    """
    url = settings.frontend_origin.rstrip("/")
    app = settings.app_display_name
    contact = settings.contact_email

    contact_text = (
        f"\nIf you did not request access, or anything looks wrong, please reach out at {contact}\n"
        if contact
        else ""
    )
    text_body = f"""\
Dear {greeting_name(user)}!

Your access to the {app} has been approved. You can sign in at

    {url}

using your institutional username and password.
{contact_text}
Best regards,
The {app} team
"""
    contact_html = (
        f'<p>If you did not request access, or anything looks wrong, please reach out at\n'
        f'<a href="mailto:{contact}">{contact}</a></p>\n'
        if contact
        else ""
    )
    html_body = f"""\
<html><body style="font-family: sans-serif; font-size: 14px; color: #1a1a1a;">
<p>Dear {greeting_name(user)}!</p>
<p>Your access to the {app} has been approved. You can
sign in at <a href="{url}">{url}</a> using your institutional username and password.</p>
{contact_html}<p>Best regards,<br>The {app} team</p>
</body></html>
"""
    return text_body, html_body


def send_approval_email(user: User) -> bool:
    """Tell a user their account has been approved.

    Sent on the pending → approved transition (see `routers/admin.py`). No-op when the
    directory has no address for them — recorded as a skip, so an admin can see on the audit
    page that the person was never reachable rather than assuming they were told.
    """
    to = recipient_for(user)
    if not to:
        log.warning(
            "no LDAP mail address for user %r; skipping approval email", user.username
        )
        audit.record_email(
            user_id=user.id,
            kind=EMAIL_KIND_APPROVAL,
            subject=APPROVAL_SUBJECT,
            status=EMAIL_SKIPPED,
            detail={"reason": "no_ldap_mail_address", "username": user.username},
        )
        return False

    text_body, html_body = render_approval_email(user)
    status, reason = _send(to, APPROVAL_SUBJECT, text_body, html_body)
    audit.record_email(
        user_id=user.id,
        kind=EMAIL_KIND_APPROVAL,
        to=to,
        subject=APPROVAL_SUBJECT,
        status=status,
        # The message itself is boilerplate; what the approval granted is not, and it is what
        # makes it answerable later which of several capability edits was the one that mailed.
        detail={"capabilities": list(user.capabilities or []), **({"reason": reason} if reason else {})},
    )
    return status == EMAIL_SENT


def concept_url(concept_id: int, taxonomy: str | None, name: str | None) -> str:
    """Where the web app shows this concept. A concept that carries no name yet can only be
    linked to the browser itself."""
    base = settings.frontend_origin.rstrip("/")
    if not taxonomy or not name:
        return f"{base}/concepts"
    return f"{base}/concepts/tax/{quote(taxonomy)}/{quote(name)}?cid={concept_id}"


def qualified_concept_name(taxonomy: str | None, name: str) -> str:
    """How a concept is named to a reader: taxonomy-qualified where there is a taxonomy, since
    the bare name is only unique within one."""
    return f"{taxonomy}/{name}" if taxonomy else name


def publish_alert_subject(
    concept_name: str, change_type: str | None, taxonomy: str | None = None
) -> str:
    """A critical update says so in the subject line: it is the one a reader may need to act on
    before opening anything."""
    kind = "critical update" if change_type == "critical" else "update"
    label = qualified_concept_name(taxonomy, concept_name)
    return f"{settings.app_display_name} — {kind} to {label}"


_CHANGE_LEAD = {
    "critical": "A critical new version has been published",
    "initial": "A first version has been published",
}


def _lead_line(change_type: str | None, version_no: int | None) -> str:
    lead = _CHANGE_LEAD.get(change_type or "", "A new version has been published")
    return f"{lead} (version {version_no})" if version_no else lead


def render_publish_alert_email(
    user: User,
    *,
    concept_name: str,
    concept_url: str,
    taxonomy: str | None = None,
    change_type: str | None = None,
    version_no: int | None = None,
    message: str | None = None,
) -> tuple[str, str]:
    """The publish-alert message's text and HTML bodies. Split out from the send for the same
    reason `render_approval_email` is: the message can be rendered without mailing anyone."""
    app = settings.app_display_name
    contact = settings.contact_email
    lead = _lead_line(change_type, version_no)
    label = qualified_concept_name(taxonomy, concept_name)
    note = (message or "").strip()

    note_text = f"\nThe publisher's note:\n\n    {note}\n" if note else ""
    contact_text = (
        f"\nIf anything looks wrong, please reach out at {contact}\n" if contact else ""
    )
    text_body = f"""\
Dear {greeting_name(user)}!

{lead} of a concept you have used: {label}.
{note_text}
You can read it at

    {concept_url}
{contact_text}
Best regards,
The {app} team
"""
    note_html = (
        f'<p>The publisher\'s note:</p>\n<blockquote style="margin: 0 0 1em 1em; '
        f'padding-left: 12px; border-left: 3px solid #d0d0d0;">{note}</blockquote>\n'
        if note
        else ""
    )
    contact_html = (
        f'<p>If anything looks wrong, please reach out at\n'
        f'<a href="mailto:{contact}">{contact}</a></p>\n'
        if contact
        else ""
    )
    html_body = f"""\
<html><body style="font-family: sans-serif; font-size: 14px; color: #1a1a1a;">
<p>Dear {greeting_name(user)}!</p>
<p>{lead} of a concept you have used: <strong>{label}</strong>.</p>
{note_html}<p>You can read it at <a href="{concept_url}">{concept_url}</a></p>
{contact_html}<p>Best regards,<br>The {app} team</p>
</body></html>
"""
    return text_body, html_body


def send_publish_alert_email(
    user: User,
    *,
    concept_id: int,
    concept_name: str,
    taxonomy: str | None = None,
    change_type: str | None = None,
    version_no: int | None = None,
    message: str | None = None,
) -> bool:
    """Tell one user that a concept they use has a new published version."""
    subject = publish_alert_subject(concept_name, change_type, taxonomy)
    detail = {
        "concept_id": concept_id,
        "concept_name": concept_name,
        "taxonomy": taxonomy,
        "version_no": version_no,
        "change_type": change_type,
    }

    to = recipient_for(user)
    if not to:
        log.warning(
            "no LDAP mail address for user %r; skipping publish alert", user.username
        )
        audit.record_email(
            user_id=user.id,
            kind=EMAIL_KIND_PUBLISH_ALERT,
            subject=subject,
            status=EMAIL_SKIPPED,
            detail={**detail, "reason": "no_ldap_mail_address", "username": user.username},
        )
        return False

    text_body, html_body = render_publish_alert_email(
        user,
        concept_name=concept_name,
        concept_url=concept_url(concept_id, taxonomy, name=concept_name),
        taxonomy=taxonomy,
        change_type=change_type,
        version_no=version_no,
        message=message,
    )
    status, reason = _send(to, subject, text_body, html_body)
    audit.record_email(
        user_id=user.id,
        kind=EMAIL_KIND_PUBLISH_ALERT,
        to=to,
        subject=subject,
        status=status,
        detail={**detail, **({"reason": reason} if reason else {})},
    )
    return status == EMAIL_SENT


def publish_alert_recipients(db: Session, concept_id: int, *, exclude_user_id: int | None = None) -> list[User]:
    """Who is told about a new version: everyone who has used the concept, plus the leads of
    every project it was used from. Deduplicated, active users only.

    The two sets answer different questions — "who pulled this definition" and "who is
    answerable for a study that pulled it" — and a lead who is also a user is one person, so
    the union is taken on the user id and not on the address.
    """
    usage.refresh(db)

    user_ids = set(
        db.scalars(select(ConceptUsage.user_id).where(ConceptUsage.concept_id == concept_id))
    )

    project_ids = set(
        db.scalars(
            select(AuditLog.project_id)
            .where(
                AuditLog.event == EVENT_API_CALL,
                AuditLog.method == "GET",
                AuditLog.concept_id == concept_id,
                AuditLog.status_code < 400,
                AuditLog.project_id.is_not(None),
            )
            .distinct()
        )
    )
    if project_ids:
        user_ids |= set(
            db.scalars(
                select(ProjectLead.user_id).where(ProjectLead.project_id.in_(project_ids))
            )
        )

    user_ids.discard(exclude_user_id)
    if not user_ids:
        return []
    return list(
        db.scalars(
            select(User)
            .where(User.id.in_(user_ids), User.is_active.is_(True))
            .order_by(User.id)
        )
    )


def notify_concept_published(
    *,
    concept_id: int,
    concept_name: str,
    taxonomy: str | None,
    change_type: str | None,
    version_no: int | None,
    message: str | None,
    published_by: int | None,
) -> int:
    """Fan the publish alert out to everyone it concerns. Returns how many messages went out.

    Runs as a background task after the publish has committed, so it opens its own session and
    never lets a failure — a wedged mail server, a broken query — reach the request that
    triggered it. The publisher is left out: they are the one who did it.
    """
    try:
        with SessionLocal() as db:
            recipients = publish_alert_recipients(db, concept_id, exclude_user_id=published_by)
    except Exception:  # noqa: BLE001 — see the module docstring
        log.exception("failed to collect publish-alert recipients for concept %s", concept_id)
        return 0

    return sum(
        send_publish_alert_email(
            user,
            concept_id=concept_id,
            concept_name=concept_name,
            taxonomy=taxonomy,
            change_type=change_type,
            version_no=version_no,
            message=message,
        )
        for user in recipients
    )
