"""Unit tests for ``app.compliance.email`` — delivery and transport.

Companion to ``tests/compliance/test_email.py`` (which covers
from-address resolution, unsubscribe tokens/URLs, and the billing and
marketing templates). This file covers message rendering
(``_as_message`` header wiring), ``marketing_headers()``,
``OutgoingEmail`` defaults, the ``_transient`` retry classification,
SMTP TLS/login toggles, ``build_transport`` selection, and the log
transport's single-attempt behavior.

SMTP is mocked; nothing leaves the machine. The log transport writes to a
temp outbox dir.

Copyright © 2026 Michael Smith. All rights reserved.
"""

from __future__ import annotations

import base64
import smtplib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.compliance import email as email_module
from app.compliance.email import (
    MARKETING,
    MAX_ATTEMPTS,
    TRANSACTIONAL,
    LogTransport,
    OutgoingEmail,
    SmtpTransport,
    _as_message,
    _transient,
    annual_renewal_reminder_email,
    build_transport,
    cancellation_confirmation_email,
    fee_change_notice_email,
    from_address,
    marketing_announcement_email,
    marketing_headers,
    purchase_receipt_email,
    send_email,
)


def _transactional_email() -> OutgoingEmail:
    return purchase_receipt_email(
        to="buyer@example.com",
        plan_name="Hobby",
        amount="$7",
        renews_at="2026-10-01",
        cancel_url="https://example.com/pricing",
    )


def _marketing_email(user_id: str = "user-123") -> OutgoingEmail:
    return marketing_announcement_email(
        to="fan@example.com",
        user_id=user_id,
        subject="New feature",
        paragraphs=["We shipped something."],
    )


# -- message rendering edge cases --------------------------------------------


class TestAsMessageEdges:
    def test_transactional_has_no_unsubscribe_headers(
        self, clean_email_env: None
    ) -> None:
        msg = _as_message(_transactional_email())
        assert msg["List-Unsubscribe"] is None
        assert msg["List-Unsubscribe-Post"] is None

    def test_marketing_without_url_has_no_unsubscribe_headers(
        self, clean_email_env: None
    ) -> None:
        email = OutgoingEmail(
            to="fan@example.com",
            subject="News",
            text_body="Hi",
            kind=MARKETING,
        )
        msg = _as_message(email)
        assert msg["List-Unsubscribe"] is None

    def test_marketing_uses_marketing_from(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("EMAIL_MARKETING_FROM", "news@example.com")
        msg = _as_message(_marketing_email())
        assert msg["From"] == "news@example.com"

    def test_custom_headers_are_merged(
        self, clean_email_env: None
    ) -> None:
        email = OutgoingEmail(
            to="buyer@example.com",
            subject="Hi",
            text_body="Hello",
            headers={"X-Campaign": "spring"},
        )
        msg = _as_message(email)
        assert msg["X-Campaign"] == "spring"

    def test_custom_headers_cannot_override_standard(
        self, clean_email_env: None
    ) -> None:
        email = OutgoingEmail(
            to="buyer@example.com",
            subject="Hi",
            text_body="Hello",
            headers={"From": "evil@example.com"},
        )
        msg = _as_message(email)
        assert msg["From"] == email_module.email_from()

    def test_plain_text_only_when_no_html(self, clean_email_env: None) -> None:
        email = OutgoingEmail(to="a@example.com", subject="Hi", text_body="Hello")
        msg = _as_message(email)
        assert msg.get_content_type() == "text/plain"


class TestMarketingHeaders:
    def test_header_shape(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("SONAR_PUBLIC_URL", "https://app.example.com")
        headers = marketing_headers("user-123")
        assert headers["List-Unsubscribe"].startswith(
            "<https://app.example.com/api/compliance/unsubscribe/"
        )
        assert headers["List-Unsubscribe"].endswith(">")
        assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


class TestOutgoingEmailDefaults:
    def test_defaults(self, clean_email_env: None) -> None:
        email = OutgoingEmail(to="a@example.com", subject="Hi", text_body="Hello")
        assert email.html_body == ""
        assert email.kind == TRANSACTIONAL
        assert email.template == ""
        assert email.headers is None
        assert email.list_unsubscribe_url == ""


# -- retry classification ------------------------------------------------------


class TestTransient:
    def test_smtp_4xx_is_transient(self) -> None:
        assert _transient(smtplib.SMTPResponseException(450, b"mailbox busy"))

    def test_smtp_5xx_is_permanent(self) -> None:
        assert not _transient(smtplib.SMTPResponseException(550, b"rejected"))

    def test_connection_drop_is_transient(self) -> None:
        assert _transient(smtplib.SMTPServerDisconnected("gone"))

    def test_timeout_is_transient(self) -> None:
        assert _transient(TimeoutError("timed out"))

    def test_value_error_is_permanent(self) -> None:
        assert not _transient(ValueError("bad address"))

    def test_max_attempts_constant(self) -> None:
        assert MAX_ATTEMPTS == 3


# -- smtp transport toggles ----------------------------------------------------


class TestSmtpTransportToggles:
    def _mock_smtp(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> MagicMock:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        monkeypatch.setattr(
            email_module.smtplib, "SMTP", lambda *a, **k: mock_client
        )
        return mock_client

    def test_no_tls_no_login_skips_both(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        mock_client = self._mock_smtp(monkeypatch)
        transport = SmtpTransport(host="mail.example.com", use_tls=False)
        result = transport.send(_transactional_email(), _as_message(_transactional_email()))
        assert result == {"transport": "smtp"}
        mock_client.starttls.assert_not_called()
        mock_client.login.assert_not_called()
        mock_client.send_message.assert_called_once()

    def test_login_skipped_without_username(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        mock_client = self._mock_smtp(monkeypatch)
        transport = SmtpTransport(host="mail.example.com", use_tls=True)
        transport.send(_transactional_email(), _as_message(_transactional_email()))
        mock_client.starttls.assert_called_once()
        mock_client.login.assert_not_called()

    def test_login_called_with_username(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        mock_client = self._mock_smtp(monkeypatch)
        transport = SmtpTransport(
            host="mail.example.com", username="user", password="secret"
        )
        transport.send(_transactional_email(), _as_message(_transactional_email()))
        mock_client.login.assert_called_once_with("user", "secret")

    def test_custom_name_used_in_receipt(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        self._mock_smtp(monkeypatch)
        transport = SmtpTransport(host="mail.example.com", name="custom")
        result = transport.send(_transactional_email(), _as_message(_transactional_email()))
        assert result == {"transport": "custom"}


class TestBuildTransportToggles:
    def test_smtp_tls_false(self, clean_email_env: None, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        monkeypatch.setenv("SMTP_TLS", "false")
        transport = build_transport()
        assert isinstance(transport, SmtpTransport)
        assert transport.use_tls is False

    def test_smtp_default_port(self, clean_email_env: None, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        transport = build_transport()
        assert isinstance(transport, SmtpTransport)
        assert transport.port == 587

    def test_smtp_legacy_password_alias(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        monkeypatch.setenv("SONAR_SMTP_PASSWORD", "legacy-secret")
        transport = build_transport()
        assert isinstance(transport, SmtpTransport)
        assert transport.password == "legacy-secret"

    def test_resend_smtp_pass_fallback(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("EMAIL_PROVIDER", "resend")
        monkeypatch.setenv("SMTP_PASS", "re_fallback")
        transport = build_transport()
        assert isinstance(transport, SmtpTransport)
        assert transport.password == "re_fallback"


# -- send_email log path --------------------------------------------------------


class TestSendEmailLog:
    def test_log_transport_single_attempt(
        self, clean_email_env: None, tmp_path: Path
    ) -> None:
        receipt = send_email(_marketing_email())
        assert receipt["transport"] == "log"
        assert receipt["attempt"] == "1"
        assert receipt["message_id"]
        assert len(list((tmp_path / "outbox").glob("*.json"))) == 1

    def test_log_receipt_carries_outbox_file(
        self, clean_email_env: None, tmp_path: Path
    ) -> None:
        receipt = send_email(_transactional_email())
        outbox_file = Path(receipt["outbox_file"])
        assert outbox_file.parent == tmp_path / "outbox"
        assert outbox_file.exists()

    def test_log_transport_base_send_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            email_module.EmailTransport().send(
                _transactional_email(), _as_message(_transactional_email())
            )
