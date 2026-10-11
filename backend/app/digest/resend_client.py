"""Resend email client for the weekly digest (Phase 3).

Copyright © 2026 Michael Smith. All rights reserved.

Sends through the Resend API. Requires RESEND_API_KEY and
DIGEST_FROM_ADDRESS (a verified sending domain) in the environment.
When the key is missing, ``send`` raises EmailNotConfigured instead of
failing silently — the digest job must never think it sent.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


class EmailNotConfiguredError(RuntimeError):
    """Resend is not configured; sending is impossible."""


RESEND_API_URL = "https://api.resend.com/emails"


def _config() -> tuple[str, str]:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_address = os.environ.get("DIGEST_FROM_ADDRESS", "").strip()
    if not api_key or not from_address:
        raise EmailNotConfiguredError(
            "RESEND_API_KEY and DIGEST_FROM_ADDRESS must both be set"
        )
    return api_key, from_address


def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Send one email through Resend. Returns the API response."""
    api_key, from_address = _config()
    payload: dict[str, Any] = {
        "from": from_address,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    if tags:
        payload["tags"] = [{"name": k, "value": v} for k, v in tags.items()]
    request = urllib.request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        return result


def is_configured() -> bool:
    """Whether sending is possible right now."""
    try:
        _config()
    except EmailNotConfiguredError:
        return False
    return True
