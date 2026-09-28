"""Transactional email for billing lifecycle events.

Provider-agnostic email transport. Transports are selected by
``EMAIL_PROVIDER`` (legacy alias ``SONAR_EMAIL_TRANSPORT``):

- ``log`` (default): renders the message and writes it to the application
  log plus an inspectable outbox directory. No email is actually sent.
  Used in tests and until the operator configures a real provider. The
  app boots and sends "nowhere" safely when unconfigured — nothing is
  silently dropped, everything is logged and kept in the outbox.
- ``smtp``: stdlib ``smtplib`` against ``SMTP_HOST`` (+ ``SMTP_PORT``,
  ``SMTP_USER``, ``SMTP_PASS``, ``SMTP_TLS``). No new dependencies.
- ``resend``: Resend via its SMTP interface — resolves to
  ``smtp.resend.com:587`` with username ``resend`` and the
  ``RESEND_API_KEY`` as the SMTP password. Same stdlib SMTP path as any
  other provider, so swapping providers later is just env config.

Marketing and transactional streams are separate: transactional mail
(purchase receipts, cancellation confirmations, renewal reminders) goes to
the transactional from-address and is never gated on marketing consent;
marketing mail carries RFC 8058 one-click ``List-Unsubscribe`` headers and
is only sent when a ``marketing_consent`` record with ``opt_in: true``
exists for the recipient.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

logger = logging.getLogger(__name__)

TRANSACTIONAL = "transactional"
MARKETING = "marketing"

# Placeholder until the founder verifies a sending domain in Resend and
# sets EMAIL_FROM / EMAIL_MARKETING_FROM. Never commit a real address here.
_DEFAULT_FROM = "Code Sonar <noreply@code-sonar.example>"

MAX_ATTEMPTS = 3
RETRY_DELAYS = (1.0, 4.0)  # seconds of backoff between attempts

_sleep = time.sleep  # module-level so tests can monkeypatch


def email_from_name() -> str:
    return os.environ.get("EMAIL_FROM_NAME", "").strip()


def email_from() -> str:
    """Transactional from-address, honoring EMAIL_FROM / legacy names."""
    addr = (
        os.environ.get("EMAIL_FROM", "").strip()
        or os.environ.get("SONAR_EMAIL_FROM", "").strip()
        or _DEFAULT_FROM
    )
    name = email_from_name()
    if name and "<" not in addr and "@" in addr:
        return f"{name} <{addr}>"
    return addr


def from_address(*, kind: str = TRANSACTIONAL) -> str:
    if kind == MARKETING:
        return (
            os.environ.get("EMAIL_MARKETING_FROM", "").strip()
            or os.environ.get("SONAR_EMAIL_MARKETING_FROM", "").strip()
            or email_from()
        )
    return email_from()


def _public_url() -> str:
    return os.environ.get("SONAR_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")


def unsubscribe_token(user_id: str) -> str:
    """HMAC-signed one-click unsubscribe token (no DB row needed)."""
    secret = os.environ.get("SONAR_SESSION_SECRET", "dev-unsubscribe-secret")
    mac = hmac.new(secret.encode(), f"unsub:{user_id}".encode(), hashlib.sha256).digest()
    raw = f"{user_id}:{base64.urlsafe_b64encode(mac).decode()}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def verify_unsubscribe_token(token: str) -> str | None:
    """Return the user id when the token is valid, else None."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        user_id, provided = raw.split(":", 1)
    except Exception:
        return None
    return user_id if hmac.compare_digest(provided, _token_mac(user_id)) else None


def _token_mac(user_id: str) -> str:
    secret = os.environ.get("SONAR_SESSION_SECRET", "dev-unsubscribe-secret")
    mac = hmac.new(secret.encode(), f"unsub:{user_id}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode()


def unsubscribe_url(user_id: str) -> str:
    return f"{_public_url()}/api/compliance/unsubscribe/{unsubscribe_token(user_id)}"


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text_body: str
    html_body: str = ""
    kind: str = TRANSACTIONAL
    template: str = ""
    headers: dict[str, str] | None = None
    # Bare (no angle brackets) RFC 8058 one-click unsubscribe URL for
    # marketing mail. Wired into the message by the transport.
    list_unsubscribe_url: str = ""


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _amount(value: str) -> str:
    """Normalize a plan amount so templates always render ``$7``, never
    ``$$7`` — callers pass either ``"7"`` or ``"$7"``."""
    return (value or "?").lstrip("$")


def _html_wrap(title: str, paragraphs: list[str]) -> str:
    body = "".join(f"<p>{_esc(p)}</p>" for p in paragraphs)
    return (
        "<!doctype html><html><body style=\"font-family:system-ui,sans-serif;"
        "max-width:560px;margin:0 auto;color:#1f2937\">"
        f"<h2>{_esc(title)}</h2>{body}"
        "<p style=\"color:#6b7280;font-size:12px\">Code Sonar · "
        "we never train on your code.</p></body></html>"
    )


# -- templates -------------------------------------------------------------


def purchase_receipt_email(
    *,
    to: str,
    plan_name: str,
    amount: str,
    renews_at: str | None,
    cancel_url: str,
) -> OutgoingEmail:
    """Post-purchase acknowledgment: renewal terms, cancellation policy,
    and how to cancel — the CA AB 2863 retainable acknowledgment."""
    amt = _amount(amount)
    subject = f"Your Code Sonar {plan_name} subscription is active"
    next_renewal = (
        f"Your next renewal is {renews_at}." if renews_at
        else "Your subscription renews each month."
    )
    lines = [
        f"Thanks — your {plan_name} plan (${amt}/month) is now active.",
        "This is a recurring subscription. It renews automatically each month "
        f"at ${amt}/month until you cancel. {next_renewal}",
        "How to cancel: open the app, go to Pricing → Subscription, and click "
        "\"Cancel subscription\". You can also cancel any time here: " + cancel_url,
        "When you cancel, you keep your plan until the end of the current "
        "billing period. You will not be charged again.",
        "Questions? Reply to this email.",
    ]
    return OutgoingEmail(
        to=to,
        subject=subject,
        text_body="\n\n".join(lines),
        html_body=_html_wrap(subject, lines),
        kind=TRANSACTIONAL,
        template="purchase_receipt",
    )


def cancellation_confirmation_email(
    *,
    to: str,
    plan_name: str,
    effective_at: str | None,
) -> OutgoingEmail:
    subject = f"Your Code Sonar {plan_name} subscription is cancelled"
    active_until = (
        f"Your {plan_name} plan stays active until {effective_at}. "
        if effective_at
        else f"Your {plan_name} plan is now on the Free plan. "
    )
    lines = [
        "This confirms your cancellation request.",
        active_until + "You will not be charged again.",
    ]
    if effective_at:
        lines.append(
            "Changed your mind? Reopen the app before that date and click "
            "\"Keep my plan\" to resume your subscription."
        )
    else:
        lines.append(
            "Changed your mind? You can subscribe again any time from "
            "the app's Pricing page."
        )
    return OutgoingEmail(
        to=to,
        subject=subject,
        text_body="\n\n".join(lines),
        html_body=_html_wrap(subject, lines),
        kind=TRANSACTIONAL,
        template="cancellation_confirmation",
    )


def annual_renewal_reminder_email(
    *,
    to: str,
    plan_name: str,
    amount: str,
    cancel_url: str,
) -> OutgoingEmail:
    """CA AB 2863 annual reminder: product, amount/frequency, how to cancel."""
    amt = _amount(amount)
    subject = f"Reminder: your Code Sonar {plan_name} subscription renews monthly"
    lines = [
        f"This is your yearly reminder that your Code Sonar {plan_name} "
        f"subscription (${amt}/month) renews automatically each month "
        "until you cancel.",
        "To cancel: open the app, go to Pricing → Subscription, and click "
        "\"Cancel subscription\", or use this link: " + cancel_url,
    ]
    return OutgoingEmail(
        to=to,
        subject=subject,
        text_body="\n\n".join(lines),
        html_body=_html_wrap(subject, lines),
        kind=TRANSACTIONAL,
        template="annual_renewal_reminder",
    )


def fee_change_notice_email(
    *,
    to: str,
    plan_name: str,
    old_amount: str,
    new_amount: str,
    effective_at: str,
    cancel_url: str,
) -> OutgoingEmail:
    """Advance notice of a price increase (7–30 days ahead in CA)."""
    subject = f"Upcoming change to your Code Sonar {plan_name} price"
    lines = [
        f"Heads up: the price of your Code Sonar {plan_name} plan is changing "
        f"from ${_amount(old_amount)}/month to ${_amount(new_amount)}/month, "
        f"effective {effective_at}.",
        "If you do nothing, your subscription continues at the new price. "
        "To cancel before the change takes effect: " + cancel_url,
    ]
    return OutgoingEmail(
        to=to,
        subject=subject,
        text_body="\n\n".join(lines),
        html_body=_html_wrap(subject, lines),
        kind=TRANSACTIONAL,
        template="fee_change_notice",
    )


def marketing_announcement_email(
    *,
    to: str,
    user_id: str,
    subject: str,
    paragraphs: list[str],
) -> OutgoingEmail:
    """Marketing mail. Always carries RFC 8058 one-click unsubscribe and is
    only sent when a marketing-consent opt-in record exists for the
    recipient — the consent gate lives in the caller (see compliance.api)."""
    return OutgoingEmail(
        to=to,
        subject=subject,
        text_body="\n\n".join(paragraphs),
        html_body=_html_wrap(subject, paragraphs),
        kind=MARKETING,
        template="marketing_announcement",
        list_unsubscribe_url=unsubscribe_url(user_id),
    )


# -- transport --------------------------------------------------------------


class EmailTransport:
    """Provider-agnostic send interface."""

    name = "base"

    def send(self, email: OutgoingEmail, message: EmailMessage) -> dict[str, str]:
        raise NotImplementedError


def _outbox_dir() -> Path:
    override = os.environ.get("SONAR_EMAIL_OUTBOX_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".code-sonar" / "email-outbox"


class LogTransport(EmailTransport):
    """Safe default: no email leaves the machine. Rendered messages are
    logged and kept in the outbox so nothing is silently dropped."""

    name = "log"

    def send(self, email: OutgoingEmail, message: EmailMessage) -> dict[str, str]:
        _outbox_dir().mkdir(parents=True, exist_ok=True)
        entry = {
            "to": email.to,
            "from": message["From"],
            "subject": email.subject,
            "kind": email.kind,
            "template": email.template,
            "message_id": message["Message-ID"],
            "headers": email.headers or {},
            "text_body": email.text_body,
        }
        path = _outbox_dir() / (
            f"{hashlib.sha256(email.subject.encode()).hexdigest()[:8]}"
            f"-{len(email.text_body)}.json"
        )
        path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
        return {"transport": "log", "outbox_file": str(path)}


class SmtpTransport(EmailTransport):
    """Stdlib SMTP. The Resend profile is this same class pointed at
    smtp.resend.com:587 with username ``resend`` — provider-agnostic."""

    name = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        name: str = "smtp",
        timeout: int = 20,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.timeout = timeout
        self.name = name

    def send(self, email: OutgoingEmail, message: EmailMessage) -> dict[str, str]:
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as client:
            if self.use_tls:
                client.starttls()
            if self.username:
                client.login(self.username, self.password)
            client.send_message(message)
        return {"transport": self.name}


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def build_transport() -> EmailTransport:
    """Resolve the configured transport from the environment.

    ``EMAIL_PROVIDER`` (legacy ``SONAR_EMAIL_TRANSPORT``), one of
    ``log`` | ``smtp`` | ``resend``. ``resend`` is the SMTP profile:
    smtp.resend.com:587, user ``resend``, password from ``RESEND_API_KEY``
    (or an explicit ``SMTP_PASS`` override). Anything unknown — including
    a ``smtp``/``resend`` provider missing its credentials — fails closed
    to the ``log`` transport rather than raising at import or startup.
    """
    provider = _env("EMAIL_PROVIDER", "SONAR_EMAIL_TRANSPORT", default="log").lower()
    if provider == "smtp":
        host = _env("SMTP_HOST", "SONAR_SMTP_HOST")
        if not host:
            logger.warning("EMAIL_PROVIDER=smtp but no SMTP_HOST; using log transport")
            return LogTransport()
        port = int(_env("SMTP_PORT", "SONAR_SMTP_PORT", default="587") or "587")
        use_tls = _env("SMTP_TLS", "SONAR_SMTP_TLS", default="true").lower() not in (
            "0",
            "false",
            "no",
        )
        return SmtpTransport(
            host=host,
            port=port,
            username=_env("SMTP_USER", "SONAR_SMTP_USER"),
            password=os.environ.get("SMTP_PASS", "")
            or os.environ.get("SONAR_SMTP_PASSWORD", ""),
            use_tls=use_tls,
        )
    if provider == "resend":
        api_key = _env("RESEND_API_KEY") or _env("SMTP_PASS")
        if not api_key:
            logger.warning(
                "EMAIL_PROVIDER=resend but no RESEND_API_KEY; using log transport"
            )
            return LogTransport()
        return SmtpTransport(
            host="smtp.resend.com",
            port=587,
            username="resend",
            password=api_key,
            use_tls=True,
            name="resend",
        )
    if provider != "log":
        logger.warning("Unknown EMAIL_PROVIDER=%r; falling back to log", provider)
    return LogTransport()


def _as_message(email: OutgoingEmail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_address(kind=email.kind)
    msg["To"] = email.to
    msg["Subject"] = email.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="code-sonar")
    if email.kind == MARKETING:
        if email.list_unsubscribe_url:
            msg["List-Unsubscribe"] = f"<{email.list_unsubscribe_url}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    for key, value in (email.headers or {}).items():
        if key not in msg:
            msg[key] = value
    msg.set_content(email.text_body)
    if email.html_body:
        msg.add_alternative(email.html_body, subtype="html")
    return msg


def _transient(error: Exception) -> bool:
    """True for SMTP failures worth retrying (4xx, connection drops)."""
    if isinstance(error, smtplib.SMTPResponseException):
        return 400 <= error.smtp_code < 500
    return isinstance(
        error,
        (
            smtplib.SMTPConnectError,
            smtplib.SMTPServerDisconnected,
            ConnectionError,
            TimeoutError,
            OSError,
        ),
    )


def send_email(email: OutgoingEmail) -> dict[str, str]:
    """Render and send an email through the configured transport.

    Defaults to the ``log`` transport (no email leaves the machine) until
    the operator sets EMAIL_PROVIDER=smtp|resend with credentials.

    Bounded retries with backoff on transient SMTP failures; permanent
    failures raise. Structured logging records only routing metadata
    (to, template, transport, message id, attempt) — never bodies.
    """
    transport = build_transport()
    message = _as_message(email)
    message_id = str(message["Message-ID"])
    receipt: dict[str, str] = {"transport": transport.name}
    attempts = MAX_ATTEMPTS if transport.name != "log" else 1
    for attempt in range(1, attempts + 1):
        try:
            result = transport.send(email, message)
            receipt.update(result)
            receipt["message_id"] = message_id
            receipt["attempt"] = str(attempt)
            logger.info(
                "email.send kind=%s to=%s template=%s transport=%s message_id=%s attempt=%d",
                email.kind,
                email.to,
                email.template or email.subject,
                receipt.get("transport"),
                message_id,
                attempt,
            )
            return receipt
        except Exception as exc:  # noqa: BLE001 - retry policy decides
            logger.warning(
                "email.send kind=%s to=%s template=%s transport=%s attempt=%d failed: %s",
                email.kind,
                email.to,
                email.template or email.subject,
                transport.name,
                attempt,
                type(exc).__name__,
            )
            if attempt >= attempts or not _transient(exc):
                raise
            _sleep(RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])
    raise RuntimeError("unreachable: retry loop exhausted")  # pragma: no cover


def marketing_headers(user_id: str) -> dict[str, str]:
    """RFC 8058 one-click unsubscribe headers for marketing mail."""
    url = unsubscribe_url(user_id)
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
