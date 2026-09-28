"""Transactional email for billing lifecycle events.

Pluggable transports selected by ``SONAR_EMAIL_TRANSPORT``:

- ``log`` (default): renders the message and writes it to the application
  log plus an inspectable outbox directory. No email is actually sent.
  Used in tests and until the operator configures a real provider.
- ``smtp``: stdlib smtplib against ``SONAR_SMTP_HOST`` (+ PORT, USER,
  PASSWORD, TLS). No new dependencies.
- ``resend``: Resend HTTP API via urllib (``RESEND_API_KEY``).

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
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

TRANSACTIONAL = "transactional"
MARKETING = "marketing"

_DEFAULT_FROM = "Code Sonar <noreply@code-sonar.example>"


def from_address(*, kind: str = TRANSACTIONAL) -> str:
    if kind == MARKETING:
        return os.environ.get("SONAR_EMAIL_MARKETING_FROM", "").strip() or email_from()
    return email_from()


def email_from() -> str:
    return os.environ.get("SONAR_EMAIL_FROM", "").strip() or _DEFAULT_FROM


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
    headers: dict[str, str] | None = None


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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
    subject = f"Your Code Sonar {plan_name} subscription is active"
    next_renewal = (
        f"Your next renewal is {renews_at}." if renews_at
        else "Your subscription renews each month."
    )
    lines = [
        f"Thanks — your {plan_name} plan (${amount}/month) is now active.",
        "This is a recurring subscription. It renews automatically each month "
        f"at ${amount}/month until you cancel. {next_renewal}",
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
    )


def annual_renewal_reminder_email(
    *,
    to: str,
    plan_name: str,
    amount: str,
    cancel_url: str,
) -> OutgoingEmail:
    """CA AB 2863 annual reminder: product, amount/frequency, how to cancel."""
    subject = f"Reminder: your Code Sonar {plan_name} subscription renews monthly"
    lines = [
        f"This is your yearly reminder that your Code Sonar {plan_name} "
        f"subscription (${amount}/month) renews automatically each month "
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
        f"from ${old_amount}/month to ${new_amount}/month, effective {effective_at}.",
        "If you do nothing, your subscription continues at the new price. "
        "To cancel before the change takes effect: " + cancel_url,
    ]
    return OutgoingEmail(
        to=to,
        subject=subject,
        text_body="\n\n".join(lines),
        html_body=_html_wrap(subject, lines),
        kind=TRANSACTIONAL,
    )


# -- transport --------------------------------------------------------------


def _outbox_dir() -> Path:
    override = os.environ.get("SONAR_EMAIL_OUTBOX_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".code-sonar" / "email-outbox"


def _send_via_log(email: OutgoingEmail) -> dict[str, str]:
    _outbox_dir().mkdir(parents=True, exist_ok=True)
    entry = {
        "to": email.to,
        "from": from_address(kind=email.kind),
        "subject": email.subject,
        "kind": email.kind,
        "headers": email.headers or {},
        "text_body": email.text_body,
    }
    path = _outbox_dir() / (
        f"{hashlib.sha256(email.subject.encode()).hexdigest()[:8]}"
        f"-{len(email.text_body)}.json"
    )
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    logger.info(
        "email[%s] to=%s subject=%s (log transport; no email sent)",
        email.kind,
        email.to,
        email.subject,
    )
    return {"transport": "log", "outbox_file": str(path)}


def _as_message(email: OutgoingEmail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_address(kind=email.kind)
    msg["To"] = email.to
    msg["Subject"] = email.subject
    if email.kind == MARKETING:
        list_unsub = email.headers.get("List-Unsubscribe", "") if email.headers else ""
        msg["List-Unsubscribe"] = f"<{list_unsub}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    for key, value in (email.headers or {}).items():
        if key not in msg:
            msg[key] = value
    msg.set_content(email.text_body)
    if email.html_body:
        msg.add_alternative(email.html_body, subtype="html")
    return msg


def _send_via_smtp(email: OutgoingEmail) -> dict[str, str]:
    host = os.environ.get("SONAR_SMTP_HOST", "").strip()
    if not host:
        raise RuntimeError("SONAR_SMTP_HOST is not configured")
    port = int(os.environ.get("SONAR_SMTP_PORT", "587").strip() or "587")
    username = os.environ.get("SONAR_SMTP_USER", "").strip()
    password = os.environ.get("SONAR_SMTP_PASSWORD", "")
    use_tls = os.environ.get("SONAR_SMTP_TLS", "true").strip().lower() not in ("0", "false", "no")
    msg = _as_message(email)
    with smtplib.SMTP(host, port, timeout=20) as client:
        if use_tls:
            client.starttls()
        if username:
            client.login(username, password)
        client.send_message(msg)
    logger.info("email[%s] to=%s subject=%s via smtp", email.kind, email.to, email.subject)
    return {"transport": "smtp"}


def _send_via_resend(email: OutgoingEmail) -> dict[str, str]:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")
    payload: dict[str, object] = {
        "from": from_address(kind=email.kind),
        "to": [email.to],
        "subject": email.subject,
        "text": email.text_body,
    }
    if email.html_body:
        payload["html"] = email.html_body
    if email.headers:
        payload["headers"] = email.headers
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "code-sonar/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")
    logger.info("email[%s] to=%s subject=%s via resend", email.kind, email.to, email.subject)
    return {"transport": "resend", "response": body[:200]}


def send_email(email: OutgoingEmail) -> dict[str, str]:
    """Send an email through the configured transport.

    Defaults to the ``log`` transport (no email leaves the machine) until
    the operator sets SONAR_EMAIL_TRANSPORT=smtp|resend with credentials.
    """
    transport = os.environ.get("SONAR_EMAIL_TRANSPORT", "log").strip().lower()
    if transport == "smtp":
        return _send_via_smtp(email)
    if transport == "resend":
        return _send_via_resend(email)
    if transport != "log":
        logger.warning("Unknown SONAR_EMAIL_TRANSPORT=%r; falling back to log", transport)
    return _send_via_log(email)


def marketing_headers(user_id: str) -> dict[str, str]:
    """RFC 8058 one-click unsubscribe headers for marketing mail."""
    url = unsubscribe_url(user_id)
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
