"""Shared fixtures for the compliance test package."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def clean_email_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate every EMAIL_* / SONAR_* knob the email module reads."""
    for name in (
        "EMAIL_PROVIDER",
        "SONAR_EMAIL_TRANSPORT",
        "EMAIL_FROM",
        "SONAR_EMAIL_FROM",
        "EMAIL_FROM_NAME",
        "EMAIL_MARKETING_FROM",
        "SONAR_EMAIL_MARKETING_FROM",
        "SMTP_HOST",
        "SONAR_SMTP_HOST",
        "SMTP_PORT",
        "SONAR_SMTP_PORT",
        "SMTP_TLS",
        "SONAR_SMTP_TLS",
        "SMTP_USER",
        "SONAR_SMTP_USER",
        "SMTP_PASS",
        "SONAR_SMTP_PASSWORD",
        "RESEND_API_KEY",
        "SONAR_PUBLIC_URL",
        "SONAR_EMAIL_OUTBOX_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SONAR_EMAIL_OUTBOX_DIR", str(tmp_path / "outbox"))
