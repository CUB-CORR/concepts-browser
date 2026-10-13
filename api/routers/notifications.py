"""Broadcast notifications, gated by `can_admin`.

`POST /admin/notifications/release` mails a package release's notes to every subscribed user
(see `mailer.release_note_recipients`). It is meant to be called by the package's release
workflow with an admin's API key rather than by a person, so the caller sends the notes
themselves — the workflow has the release in hand, and a manual run can post any older tag's
notes the same way. Nothing here remembers what was announced: posting the same release twice
mails it twice, which is what a deliberate resend wants.

The sends run as a background task after the response; each one lands on the audit page as a
`release_note` email row.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from .. import mailer, security
from ..db import get_db
from ..deps import require_capability
from ..models import User
from ..schemas import ReleaseNoteQueued, ReleaseNoteRequest

router = APIRouter(prefix="/admin/notifications", tags=["admin"])

_admin = require_capability(security.CAN_ADMIN)


@router.post(
    "/release",
    response_model=ReleaseNoteQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
def notify_release(
    body: ReleaseNoteRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(_admin),
):
    """Mail the release notes to every subscribed user (currently: every approved, active one).

    `dry_run` sends nothing and returns the rendered message; `only_me` sends to the caller
    alone. Recipients without a directory mail address are counted in `without_address` and
    recorded as skipped when the task reaches them.
    """
    if body.only_me:
        # `admin` may be a detached, scope-narrowed copy (an API key); only its id is used.
        recipients = [db.get(User, admin.id)]
    else:
        recipients = mailer.release_note_recipients(db)

    message = {
        "package": body.package,
        "version": body.version,
        "notes": body.notes,
        "release_url": body.release_url,
        "repository": body.repository,
    }
    summary = {
        "package": body.package,
        "version": body.version,
        "recipients": len(recipients),
        "without_address": sum(1 for user in recipients if not mailer.recipient_for(user)),
    }

    if body.dry_run:
        # Rendered for a real recipient where there is one, so the greeting is realistic.
        _, html = mailer.render_release_note_email(recipients[0] if recipients else admin, **message)
        return ReleaseNoteQueued(
            status="dry_run",
            subject=mailer.release_note_subject(body.package, body.version),
            html=html,
            **summary,
        )

    if recipients:
        background.add_task(
            mailer.notify_release, user_ids=[user.id for user in recipients], **message
        )
    return ReleaseNoteQueued(status="queued", **summary)
