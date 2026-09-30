"""Unit tests for ``app.compliance.email``.

``test_email_transport.py`` covers provider resolution (log/smtp/resend,
legacy env aliases), the ``send_email`` retry policy, receipt amount
rendering, and the marketing one-click unsubscribe header on the message.
``test_compliance.py`` covers the unsubscribe token round-trip and the
transactional send path through the API layer.

This module covers the gaps: from-address resolution (``email_from`` /
``from_address``), the three remaining billing templates
(``cancellation_confirmation_email``, ``annual_renewal_reminder_email``,
``fee_change_notice_email``), marketing template details, ``_as_message``
header wiring edge cases, ``marketing_headers()``, the ``_transient``
retry classification, token tamper/secret-mismatch paths, SMTP TLS and
login toggles, and log-transport single-attempt behavior.

Companion file ``tests/compliance/test_email_delivery.py`` covers
message rendering, marketing headers, retry classification, transport
toggles, and the log transport.

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


# -- from-address resolution ------------------------------------------------


class TestEmailFrom:
    def test_default_placeholder(self, clean_email_env: None) -> None:
        assert email_module.email_from() == "Code Sonar <noreply@code-sonar.example>"

    def test_email_from_env_wins(self, clean_email_env: None, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_FROM", "billing@example.com")
        assert email_module.email_from() == "billing@example.com"

    def test_legacy_env_alias(self, clean_email_env: None, monkeypatch) -> None:
        monkeypatch.setenv("SONAR_EMAIL_FROM", "legacy@example.com")
        assert email_module.email_from() == "legacy@example.com"

    def test_email_from_prefers_new_over_legacy(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("EMAIL_FROM", "new@example.com")
        monkeypatch.setenv("SONAR_EMAIL_FROM", "legacy@example.com")
        assert email_module.email_from() == "new@example.com"

    def test_from_name_applies_to_bare_address(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("EMAIL_FROM", "billing@example.com")
        monkeypatch.setenv("EMAIL_FROM_NAME", "Code Sonar Billing")
        assert (
            email_module.email_from() == "Code Sonar Billing <billing@example.com>"
        )

    def test_from_name_ignored_when_address_has_brackets(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("EMAIL_FROM", "X <billing@example.com>")
        monkeypatch.setenv("EMAIL_FROM_NAME", "Other Name")
        assert email_module.email_from() == "X <billing@example.com>"

    def test_from_name_ignored_without_at_sign(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("EMAIL_FROM", "billing")
        monkeypatch.setenv("EMAIL_FROM_NAME", "Some Name")
        assert email_module.email_from() == "billing"

    def test_blank_from_name_is_not_applied(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("EMAIL_FROM", "billing@example.com")
        monkeypatch.setenv("EMAIL_FROM_NAME", "   ")
        assert email_module.email_from() == "billing@example.com"


class TestFromAddress:
    def test_transactional_default(self, clean_email_env: None) -> None:
        assert from_address() == email_module.email_from()

    def test_transactional_explicit(self, clean_email_env: None) -> None:
        assert from_address(kind=TRANSACTIONAL) == email_module.email_from()

    def test_marketing_falls_back_to_transactional(
        self, clean_email_env: None
    ) -> None:
        assert from_address(kind=MARKETING) == email_module.email_from()

    def test_marketing_from_env(self, clean_email_env: None, monkeypatch) -> None:
        monkeypatch.setenv("EMAIL_MARKETING_FROM", "news@example.com")
        assert from_address(kind=MARKETING) == "news@example.com"

    def test_marketing_legacy_env_alias(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("SONAR_EMAIL_MARKETING_FROM", "old-news@example.com")
        assert from_address(kind=MARKETING) == "old-news@example.com"

    def test_marketing_env_prefers_new_over_legacy(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("EMAIL_MARKETING_FROM", "news@example.com")
        monkeypatch.setenv("SONAR_EMAIL_MARKETING_FROM", "old-news@example.com")
        assert from_address(kind=MARKETING) == "news@example.com"

    def test_unknown_kind_returns_transactional(
        self, clean_email_env: None
    ) -> None:
        assert from_address(kind="bogus") == email_module.email_from()


# -- unsubscribe token edge cases --------------------------------------------


class TestVerifyUnsubscribeTokenEdges:
    def test_empty_string_is_invalid(self, clean_email_env: None) -> None:
        assert email_module.verify_unsubscribe_token("") is None

    def test_non_base64_is_invalid(self, clean_email_env: None) -> None:
        assert email_module.verify_unsubscribe_token("!!!not-base64!!!") is None

    def test_missing_colon_is_invalid(self, clean_email_env: None) -> None:
        token = base64.urlsafe_b64encode(b"no-colon-here").decode()
        assert email_module.verify_unsubscribe_token(token) is None

    def test_swapped_user_id_fails(self, clean_email_env: None) -> None:
        raw = base64.urlsafe_b64decode(
            email_module.unsubscribe_token("user-123").encode()
        ).decode()
        _, mac = raw.split(":", 1)
        forged = base64.urlsafe_b64encode(f"user-999:{mac}".encode()).decode()
        assert email_module.verify_unsubscribe_token(forged) is None

    def test_different_secret_fails(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("SONAR_SESSION_SECRET", "first-secret")
        token = email_module.unsubscribe_token("user-123")
        monkeypatch.setenv("SONAR_SESSION_SECRET", "second-secret")
        assert email_module.verify_unsubscribe_token(token) is None

    def test_missing_secret_fails_closed(self, monkeypatch) -> None:
        # No hardcoded fallback: without SONAR_SESSION_SECRET the token
        # machinery must refuse rather than mint forgeable tokens.
        monkeypatch.setenv("SONAR_SESSION_SECRET", "test-unsubscribe-secret")
        token = email_module.unsubscribe_token("user-123")
        monkeypatch.delenv("SONAR_SESSION_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="SONAR_SESSION_SECRET"):
            email_module.unsubscribe_token("user-123")
        with pytest.raises(RuntimeError, match="SONAR_SESSION_SECRET"):
            email_module.verify_unsubscribe_token(token)
        # Malformed tokens still return None without touching the secret.
        assert email_module.verify_unsubscribe_token("bogus") is None


class TestUnsubscribeUrl:
    def test_default_public_url(self, clean_email_env: None) -> None:
        url = email_module.unsubscribe_url("user-123")
        assert url.startswith("http://127.0.0.1:8000/api/compliance/unsubscribe/")

    def test_custom_public_url_trailing_slash_stripped(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("SONAR_PUBLIC_URL", "https://app.example.com/")
        url = email_module.unsubscribe_url("user-123")
        assert url.startswith("https://app.example.com/api/compliance/unsubscribe/")
        assert "//api" not in url


# -- billing templates -------------------------------------------------------


class TestCancellationConfirmation:
    def test_with_effective_at(self, clean_email_env: None) -> None:
        email = cancellation_confirmation_email(
            to="buyer@example.com",
            plan_name="Hobby",
            effective_at="2026-10-31",
        )
        assert email.kind == TRANSACTIONAL
        assert email.template == "cancellation_confirmation"
        assert "Hobby" in email.subject
        assert "2026-10-31" in email.text_body
        assert "You will not be charged again." in email.text_body
        assert "Keep my plan" in email.text_body

    def test_without_effective_at(self, clean_email_env: None) -> None:
        email = cancellation_confirmation_email(
            to="buyer@example.com",
            plan_name="Hobby",
            effective_at=None,
        )
        assert email.kind == TRANSACTIONAL
        assert email.template == "cancellation_confirmation"
        assert "Free plan" in email.text_body
        assert "You will not be charged again." in email.text_body
        assert "subscribe again" in email.text_body


class TestAnnualRenewalReminder:
    def test_reminder_content(self, clean_email_env: None) -> None:
        email = annual_renewal_reminder_email(
            to="buyer@example.com",
            plan_name="Hobby",
            amount="7",
            cancel_url="https://example.com/cancel",
        )
        assert email.kind == TRANSACTIONAL
        assert email.template == "annual_renewal_reminder"
        assert "renews monthly" in email.subject
        assert "$7/month" in email.text_body
        assert "https://example.com/cancel" in email.text_body

    def test_reminder_amount_with_dollar_sign(self, clean_email_env: None) -> None:
        email = annual_renewal_reminder_email(
            to="buyer@example.com",
            plan_name="Hobby",
            amount="$14",
            cancel_url="https://example.com/cancel",
        )
        assert "$14/month" in email.text_body
        assert "$$14" not in email.text_body


class TestFeeChangeNotice:
    def test_fee_change_content(self, clean_email_env: None) -> None:
        email = fee_change_notice_email(
            to="buyer@example.com",
            plan_name="Hobby",
            old_amount="$7",
            new_amount="14",
            effective_at="2026-11-01",
            cancel_url="https://example.com/cancel",
        )
        assert email.kind == TRANSACTIONAL
        assert email.template == "fee_change_notice"
        assert "Hobby" in email.subject
        assert "$7/month" in email.text_body
        assert "$14/month" in email.text_body
        assert "2026-11-01" in email.text_body
        assert "https://example.com/cancel" in email.text_body

    def test_fee_change_renders_no_double_dollar(self, clean_email_env: None) -> None:
        email = fee_change_notice_email(
            to="buyer@example.com",
            plan_name="Hobby",
            old_amount="$7",
            new_amount="$14",
            effective_at="2026-11-01",
            cancel_url="https://example.com/cancel",
        )
        assert "$$7" not in email.text_body
        assert "$$14" not in email.text_body


class TestPurchaseReceiptEdges:
    def test_empty_amount_renders_question_mark(self, clean_email_env: None) -> None:
        email = purchase_receipt_email(
            to="buyer@example.com",
            plan_name="Hobby",
            amount="",
            renews_at=None,
            cancel_url="https://example.com/pricing",
        )
        assert "$?/month" in email.text_body

    def test_renewal_date_included_when_provided(
        self, clean_email_env: None
    ) -> None:
        email = _transactional_email()
        assert "2026-10-01" in email.text_body

    def test_html_body_escapes_template_content(
        self, clean_email_env: None
    ) -> None:
        email = purchase_receipt_email(
            to="buyer@example.com",
            plan_name="<b>Hobby</b>",
            amount="7",
            renews_at=None,
            cancel_url="https://example.com/pricing",
        )
        assert "&lt;b&gt;Hobby&lt;/b&gt;" in email.html_body
        assert "<b>Hobby</b>" not in email.html_body


# -- marketing template -------------------------------------------------------


class TestMarketingAnnouncement:
    def test_marketing_kind_and_template(
        self, clean_email_env: None, monkeypatch
    ) -> None:
        monkeypatch.setenv("SONAR_PUBLIC_URL", "https://app.example.com")
        email = _marketing_email()
        assert email.kind == MARKETING
        assert email.template == "marketing_announcement"
        assert email.list_unsubscribe_url.startswith(
            "https://app.example.com/api/compliance/unsubscribe/"
        )

    def test_paragraphs_joined_as_text(self, clean_email_env: None) -> None:
        email = marketing_announcement_email(
            to="fan@example.com",
            user_id="user-123",
            subject="News",
            paragraphs=["One.", "Two."],
        )
        assert email.text_body == "One.\n\nTwo."

    def test_html_body_escapes_paragraphs(self, clean_email_env: None) -> None:
        email = marketing_announcement_email(
            to="fan@example.com",
            user_id="user-123",
            subject="News",
            paragraphs=["<script>alert(1)</script>"],
        )
        assert "&lt;script&gt;" in email.html_body
        assert "<script>" not in email.html_body


