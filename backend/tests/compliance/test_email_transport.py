"""Tests for the provider-agnostic email transport.

SMTP is mocked; nothing leaves the machine. The log transport is the
safe default and is exercised against a temp outbox dir.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import smtplib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.compliance import email as email_module
from app.compliance.email import (
    LogTransport,
    OutgoingEmail,
    SmtpTransport,
    _as_message,
    build_transport,
    purchase_receipt_email,
    send_email,
)


@pytest.fixture
def outbox_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SONAR_EMAIL_OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    monkeypatch.delenv("SONAR_EMAIL_TRANSPORT", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SONAR_SMTP_HOST", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)


def _receipt_email() -> OutgoingEmail:
    return purchase_receipt_email(
        to="buyer@example.com",
        plan_name="Hobby",
        amount="$7",
        renews_at=None,
        cancel_url="https://example.com/pricing",
    )


# -- provider resolution ------------------------------------------------------


def test_default_is_log_transport(outbox_env: None) -> None:
    transport = build_transport()
    assert isinstance(transport, LogTransport)


def test_unknown_provider_falls_back_to_log(
    outbox_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "carrier-pigeon")
    assert isinstance(build_transport(), LogTransport)


def test_resend_profile_resolves_to_smtp(
    outbox_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    transport = build_transport()
    assert isinstance(transport, SmtpTransport)
    assert transport.name == "resend"
    assert transport.host == "smtp.resend.com"
    assert transport.port == 587
    assert transport.username == "resend"
    assert transport.password == "re_test_key"


def test_resend_without_key_falls_back_to_log(
    outbox_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    assert isinstance(build_transport(), LogTransport)


def test_custom_smtp_provider(outbox_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("EMAIL_FROM_NAME", "CodeVitals")
    monkeypatch.setenv("EMAIL_FROM", "billing@example.com")
    transport = build_transport()
    assert isinstance(transport, SmtpTransport)
    assert transport.host == "mail.example.com"
    assert transport.port == 2525
    assert email_module.email_from() == "CodeVitals <billing@example.com>"


def test_smtp_without_host_falls_back_to_log(
    outbox_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    assert isinstance(build_transport(), LogTransport)


def test_legacy_env_aliases_still_work(
    outbox_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SONAR_EMAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SONAR_SMTP_HOST", "legacy.example.com")
    transport = build_transport()
    assert isinstance(transport, SmtpTransport)
    assert transport.host == "legacy.example.com"


# -- sending ------------------------------------------------------------------


def test_log_transport_never_sends_and_keeps_outbox(outbox_env: None, tmp_path: Path) -> None:
    receipt = send_email(_receipt_email())
    assert receipt["transport"] == "log"
    outbox = tmp_path / "outbox"
    files = list(outbox.glob("*.json"))
    assert len(files) == 1
    assert "buyer@example.com" in files[0].read_text()


def test_smtp_send_success(outbox_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    monkeypatch.setattr(email_module.smtplib, "SMTP", lambda *a, **k: mock_client)
    receipt = send_email(_receipt_email())
    assert receipt["transport"] == "smtp"
    assert receipt["attempt"] == "1"
    assert receipt["message_id"]
    mock_client.starttls.assert_called_once()
    mock_client.send_message.assert_called_once()


def test_transient_failure_retries_then_succeeds(
    outbox_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    calls = {"n": 0}

    def _flaky_send(message: object) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise smtplib.SMTPServerDisconnected("gone")

    mock_client.send_message.side_effect = _flaky_send
    monkeypatch.setattr(email_module.smtplib, "SMTP", lambda *a, **k: mock_client)
    monkeypatch.setattr(email_module, "_sleep", lambda s: None)
    receipt = send_email(_receipt_email())
    assert receipt["attempt"] == "2"
    assert calls["n"] == 2


def test_permanent_failure_raises_without_retry(
    outbox_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.send_message.side_effect = smtplib.SMTPDataError(550, b"rejected")
    monkeypatch.setattr(email_module.smtplib, "SMTP", lambda *a, **k: mock_client)
    monkeypatch.setattr(email_module, "_sleep", lambda s: None)
    with pytest.raises(smtplib.SMTPDataError):
        send_email(_receipt_email())
    assert mock_client.send_message.call_count == 1


def test_retry_exhaustion_raises_after_max_attempts(
    outbox_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "mail.example.com")
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.send_message.side_effect = smtplib.SMTPServerDisconnected("gone")
    monkeypatch.setattr(email_module.smtplib, "SMTP", lambda *a, **k: mock_client)
    monkeypatch.setattr(email_module, "_sleep", lambda s: None)
    with pytest.raises(smtplib.SMTPServerDisconnected):
        send_email(_receipt_email())
    assert mock_client.send_message.call_count == email_module.MAX_ATTEMPTS


# -- templates -----------------------------------------------------------------


def test_receipt_amount_renders_single_dollar_sign() -> None:
    email = _receipt_email()
    assert "$7/month" in email.text_body
    assert "$$7" not in email.text_body
    assert "$$7" not in email.html_body


def test_receipt_amount_also_works_without_dollar() -> None:
    email = purchase_receipt_email(
        to="buyer@example.com",
        plan_name="Plus",
        amount="14",
        renews_at=None,
        cancel_url="https://example.com/pricing",
    )
    assert "$14/month" in email.text_body
    assert "$$14" not in email.text_body


# -- headers -------------------------------------------------------------------


def test_message_has_message_id_and_date() -> None:
    msg = _as_message(_receipt_email())
    assert msg["Message-ID"]
    assert msg["Date"]


def test_marketing_email_gets_one_click_unsubscribe_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SONAR_PUBLIC_URL", "https://app.example.com")
    email = email_module.marketing_announcement_email(
        to="fan@example.com",
        user_id="user-123",
        subject="New feature",
        paragraphs=["We shipped something."],
    )
    msg = _as_message(email)
    list_unsub = msg["List-Unsubscribe"]
    assert list_unsub.startswith("<https://app.example.com/api/compliance/unsubscribe/")
    assert list_unsub.endswith(">")
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_unsubscribe_token_round_trip_verifies() -> None:
    token = email_module.unsubscribe_token("user-123")
    assert email_module.verify_unsubscribe_token(token) == "user-123"
    assert email_module.verify_unsubscribe_token("bogus") is None
