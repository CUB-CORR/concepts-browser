"""Check that this host can actually reach the Exchange server, and optionally send.

Lives in `api/` (not `scripts/`) because that is what the image copies — so it can be run
inside the container, which is the only place the answer counts:

    docker compose exec api python -m api.mail_check                    # probe EWS + login
    docker compose exec api python -m api.mail_check you@example.org    # ...and send a test mail

Locally (on a network that can reach the server) the same is `uv run python -m api.mail_check`.

Tells the failure modes apart: the EWS endpoint is unreachable (blocked, or a proxy is
swallowing it), the credentials are wrong, or the account cannot open the functional mailbox.
Reads the same EXCHANGE_* settings as the API, except that it probes regardless of
EXCHANGE_ENABLED — the point is to test the connection *before* switching mail on.

Because IT often documents a login name but not the form Exchange wants it in, the login is
retried in each spelling Exchange might accept, under each auth scheme, and the combination
that works is printed as the settings to deploy.

The test send renders the real approval template but does NOT write an audit row: nobody was
approved, and the log should not claim otherwise.
"""
import socket
import sys

from exchangelib import Account

from . import mailer
from .config import settings
from .models import EMAIL_SENT, User

HOST = settings.exchange_server
ENDPOINT = f"https://{HOST}/EWS/Exchange.asmx"

# The login as configured, then the domain-qualified spellings on-prem Exchange tends to
# want (NTLM often insists on a domain). The mail domain comes from the mailbox address;
# the NetBIOS-style guess is its first label, upper-cased.
BARE = settings.exchange_username.split("\\")[-1].split("@")[0]
_MAIL_DOMAIN = settings.exchange_mailbox.partition("@")[2]
_NETBIOS = _MAIL_DOMAIN.partition(".")[0].upper()
USERNAMES = [settings.exchange_username, f"{_NETBIOS}\\{BARE}", f"{BARE}@{_MAIL_DOMAIN}"]
# Configured scheme first, then the others, then "" = let exchangelib probe the server.
AUTH_TYPES = [settings.exchange_auth_type, "NTLM", "basic", ""]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def reachable() -> bool:
    """Is there an EWS endpoint to talk to at all? Purely TCP — a proxy or a closed 443 fails
    here, and that is a different conversation with IT than a rejected password."""
    try:
        with socket.create_connection((HOST, 443), timeout=settings.exchange_timeout):
            pass
    except OSError as exc:
        print(f"  ✗ {ENDPOINT}: unreachable — {exc}")
        return False
    print(f"  ✓ {HOST}:443 open")
    return True


def try_login(username: str, auth_type: str) -> Account | None:
    """One login attempt, all the way into the mailbox. Opening the account only builds the
    session; reading a folder is what actually authenticates and proves the delegate rights,
    so it is the folder read that decides whether this combination works."""
    label = f"{username} via {auth_type or 'auto-detected auth'}"
    settings.exchange_auth_type = auth_type
    try:
        account = mailer.connect(username=username)
        account.inbox.total_count  # noqa: B018 — the request that proves we're really in
    except Exception as exc:  # noqa: BLE001 — a probe reports failures, it doesn't raise them
        print(f"  ✗ {label}: {type(exc).__name__} — {exc}")
        return None
    print(f"  ✓ {label}: opened {settings.exchange_mailbox}")
    return account


def main(argv: list[str]) -> int:
    print(f"probing {ENDPOINT}\nmailbox {settings.exchange_mailbox}\n")
    if not reachable():
        print(
            "\nNothing listening. Ask IT to open 443 to the Exchange server from this host — "
            "and if you are behind an outbound proxy, check no_proxy covers it, or the "
            "request goes to the proxy instead."
        )
        return 1

    if not settings.exchange_password:
        print("\nEXCHANGE_PASSWORD unset — cannot verify the login. Set it and re-run.")
        return 1

    working = None
    for auth_type in _unique(AUTH_TYPES):
        for username in _unique(USERNAMES):
            if try_login(username, auth_type):
                working = (username, auth_type)
                break
        if working:
            break

    if not working:
        print(
            "\nReached the server, but no login worked. Either the password is wrong, or "
            f"{BARE} has no access to {settings.exchange_mailbox} — the mailbox is opened as a "
            "delegate, which is a right IT grants separately from the account itself."
        )
        return 1

    username, auth_type = working
    print(f"\nUsable: set EXCHANGE_USERNAME={username}", end="")
    print(f" EXCHANGE_AUTH_TYPE={auth_type}" if auth_type else " (leave EXCHANGE_AUTH_TYPE empty)")

    if len(argv) < 2:
        return 0

    to = argv[1]
    # Exercise the real message and the real transport, but not `send_approval_email`: this
    # user is a fixture nobody approved, and a probe has no business writing an audit row.
    # Overriding the settings in-process (rather than .env) keeps this a one-shot: mail stays
    # off for the API itself until you enable it for real.
    settings.exchange_enabled = True
    settings.exchange_username, settings.exchange_auth_type = username, auth_type
    fake = User(
        username="testuser",
        display_name="Test User",
        capabilities=["can_read", "can_edit"],
        ldap_profile={"cn": ["User, Test"], "mail": [to]},
    )
    text_body, html_body = mailer.render_approval_email(fake)
    print(f"\nsending a test approval email to {to} ...")
    status, reason = mailer._send(to, mailer.APPROVAL_SUBJECT, text_body, html_body)
    print("sent" if status == EMAIL_SENT else f"FAILED ({reason}) — see the log above")
    return 0 if status == EMAIL_SENT else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
