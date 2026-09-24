"""Tests for on-demand remediation source re-materialization."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.history import build_scan_record
from app.remediation import source as remediation_source
from app.remediation.source import resolve_remediation_source
from app.scan_jobs import _repository_slug
from app.scoring.engine import calculate_score


def _record(
    repository_path: str,
    repository_slug: str | None = None,
    branch: str | None = None,
):
    return build_scan_record(
        repository_id="repo-1",
        repository_path=repository_path,
        findings=[],
        scoring=calculate_score([]),
        scan_id="scan-1",
        scanned_at="2026-09-24T00:00:00+00:00",
        repository_slug=repository_slug,
        branch=branch,
    )


def _fake_clone(dest: Path) -> None:
    """Stand in for a real shallow clone: materialize a directory at dest."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "README.md").write_text("# fake clone\n", encoding="utf-8")


def test_existing_checkout_is_reused_without_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        remediation_source,
        "_shallow_clone",
        lambda *args: calls.append(args) or _fake_clone(args[2]),
    )
    record = _record(str(tmp_path))

    source = resolve_remediation_source(record)

    assert source.path == str(tmp_path.resolve())
    assert calls == []
    source.dispose()
    # Dispose is a no-op for pre-existing checkouts.
    assert tmp_path.is_dir()


def test_missing_path_without_slug_raises_unavailable() -> None:
    record = _record("/tmp/definitely-not-a-real-checkout")

    with pytest.raises(
        ValueError, match="Remediation source repository is unavailable"
    ):
        resolve_remediation_source(record)


def test_reclone_on_demand_inside_scan_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspaces = tmp_path / "workspaces"
    monkeypatch.setattr(remediation_source, "WORKSPACES_ROOT", workspaces)
    seen: dict[str, object] = {}

    def fake_clone(clone_url: str, branch: str | None, dest: Path) -> None:
        seen["clone_url"] = clone_url
        seen["branch"] = branch
        _fake_clone(dest)

    monkeypatch.setattr(remediation_source, "_shallow_clone", fake_clone)
    record = _record(
        "/tmp/definitely-not-a-real-checkout",
        repository_slug="octocat/Hello-World",
        branch="main",
    )

    source = resolve_remediation_source(record, github_token="token-123")

    assert seen["clone_url"] == "https://x-access-token:token-123@github.com/octocat/Hello-World.git"
    assert seen["branch"] == "main"
    cloned = Path(source.path)
    assert cloned.parent == workspaces
    assert (cloned / "README.md").is_file()
    source.dispose()
    assert not cloned.exists()


def test_failed_clone_cleans_up_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspaces = tmp_path / "workspaces"
    monkeypatch.setattr(remediation_source, "WORKSPACES_ROOT", workspaces)

    def failing_clone(clone_url: str, branch: str | None, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        raise RuntimeError("boom")

    monkeypatch.setattr(remediation_source, "_shallow_clone", failing_clone)
    record = _record(
        "/tmp/definitely-not-a-real-checkout",
        repository_slug="octocat/Hello-World",
    )

    with pytest.raises(RuntimeError, match="boom"):
        resolve_remediation_source(record)
    assert list(workspaces.iterdir()) == []


def test_clone_failure_redacts_oauth_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=128,
            stdout="",
            stderr="https://x-access-token:secret-token-abc@github.com/o/n.git: auth failed",
        )

    monkeypatch.setattr(remediation_source.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as excinfo:
        remediation_source._shallow_clone(
            "https://x-access-token:secret-token-abc@github.com/o/n.git",
            None,
            Path("/tmp/unused-dest"),
        )
    assert "secret-token-abc" not in str(excinfo.value)
    assert "x-access-token:***@" in str(excinfo.value)


def test_record_round_trip_preserves_slug_and_branch() -> None:
    record = _record("/tmp/x", repository_slug="o/n", branch="develop")
    restored = type(record).from_dict(record.to_dict())
    assert restored.repository_slug == "o/n"
    assert restored.branch == "develop"


def test_old_records_without_slug_default_to_none() -> None:
    record = _record("/tmp/x", repository_slug="o/n", branch="develop")
    data = record.to_dict()
    del data["repository_slug"]
    del data["branch"]
    restored = type(record).from_dict(data)
    assert restored.repository_slug is None
    assert restored.branch is None


@pytest.mark.parametrize(
    ("clone_url", "expected"),
    [
        ("https://github.com/octocat/Hello-World.git", "octocat/Hello-World"),
        ("https://github.com/octocat/Hello-World", "octocat/Hello-World"),
        ("https://github.com/my-org/my.repo", "my-org/my.repo"),
        ("https://gitlab.com/octocat/Hello-World.git", None),
        ("https://github.com/octocat", None),
        ("https://github.com/octocat/a/b", None),
        ("not a url", None),
    ],
)
def test_repository_slug_parsing(clone_url: str, expected: str | None) -> None:
    assert _repository_slug(clone_url) == expected


def test_record_without_slug_exposes_none() -> None:
    record = _record("/tmp/x")
    assert record.repository_slug is None
    assert record.branch is None
    assert record.to_dict()["repository_slug"] is None
    # from_dict tolerates the new-style payload missing nothing either.
    namespace_record = SimpleNamespace(
        repository_path="/tmp/definitely-not-a-real-checkout",
    )
    with pytest.raises(
        ValueError, match="Remediation source repository is unavailable"
    ):
        resolve_remediation_source(namespace_record)
