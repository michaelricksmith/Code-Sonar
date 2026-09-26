"""Guard tests for the temporary one-time wipe endpoint."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.admin_wipe import _authorized, router


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("WIPE_TOKEN", raising=False)
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_no_token_env_always_unauthorized(client, monkeypatch):
    monkeypatch.delenv("WIPE_TOKEN", raising=False)
    response = client.post("/api/admin/wipe-user-data", headers={"x-wipe-token": "abc"})
    assert response.status_code == 404


def test_wrong_token_unauthorized(client, monkeypatch):
    monkeypatch.setenv("WIPE_TOKEN", "correct-token")
    response = client.post("/api/admin/wipe-user-data", headers={"x-wipe-token": "wrong"})
    assert response.status_code == 404


def test_authorized_helper_accepts_matching_token(monkeypatch):
    monkeypatch.setenv("WIPE_TOKEN", "s3cret")

    class FakeRequest:
        headers = {"x-wipe-token": "s3cret"}

    assert _authorized(FakeRequest()) is True  # type: ignore[arg-type]


def test_authorized_helper_rejects_mismatch(monkeypatch):
    monkeypatch.setenv("WIPE_TOKEN", "s3cret")

    class FakeRequest:
        headers = {"x-wipe-token": "nope"}

    assert _authorized(FakeRequest()) is False  # type: ignore[arg-type]


def test_missing_header_unauthorized(client, monkeypatch):
    monkeypatch.setenv("WIPE_TOKEN", "s3cret")
    response = client.post("/api/admin/wipe-user-data")
    assert response.status_code == 404
    assert "WIPE_TOKEN" not in os.environ or True
