# Code Sonar — Private-Beta Checklist (v0.1.0-beta.1)

**Created, built, and owned by Michael Smith (GitHub: `michaelricksmith`). Copyright © 2026 Michael Smith. All rights reserved.**

This checklist is the acceptance gate for putting Code Sonar in front
of 5–10 private-beta users. It is the source of truth for "ready or
not ready." Each item is either ✅ (verified) or has explicit next steps.

---

## INSTALLATION

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Fresh clone works | ✅ | `git clone https://github.com/michaelricksmith/code-sonar.git` produces a clean checkout |
| 2 | Dependencies install | ✅ | `scripts/start.bat` / `scripts/start.sh` run `pip install -e ".[dev]"` and `npm install` automatically |
| 3 | Startup works | ✅ | One-command: `scripts/start.bat` (Windows) or `./scripts/start.sh` (Unix). Backend on http://127.0.0.1:8000 (or 8765 if 8000 busy), Frontend on http://localhost:5173 |
| 4 | Health checks pass | ✅ | `GET /health` returns `{"status": "ok"}`; smoke script `backend/scripts/self_scan_smoke.py --min-analyzers 8` passes against the running server |

**Manual verification (fresh environment):**
```bash
# Windows
git clone https://github.com/michaelricksmith/code-sonar.git
cd code-sonar
scripts\start.bat
# Wait for "=== Code Sonar is starting ===" then open http://localhost:5173

# Unix / macOS / WSL
git clone https://github.com/michaelricksmith/code-sonar.git
cd code-sonar
./scripts/start.sh
tail -f logs/backend.log  # optional
```

---

## SCAN

| # | Item | Status | Evidence |
|---|---|---|---|
| 5 | Repository scan works | ✅ | `POST /api/scan {"repo_path": "..."}` returns a `ScanResponse` |
| 6 | Score returned | ✅ | `result.score` and `result.grade` present in response |
| 7 | Findings returned | ✅ | `result.findings` array with all per-finding metadata |
| 8 | Hotspot ranking returned | ✅ | `result.top_hotspots` (top 10) + `GET /api/hotspots` for full ranking |
| 9 | History stored | ✅ | `JsonlHistoryStore` appends every scan; `GET /api/history/latest?repo_path=...` retrieves |
| 10 | Second scan produces drift | ✅ | `GET /api/drift?repo_path=...` returns NEW/RESOLVED/PERSISTENT/WORSENED/IMPROVED classifications |

**Manual verification (drift demo):**
```bash
# Scan state A
curl -X POST http://127.0.0.1:8000/api/scan \
    -H 'Content-Type: application/json' \
    -d '{"repo_path": "demo/sample_repo/state-A"}'

# Switch to state B (or change files)
# Scan state B
curl -X POST http://127.0.0.1:8000/api/scan \
    -H 'Content-Type: application/json' \
    -d '{"repo_path": "demo/sample_repo/state-B"}'

# Compute drift
curl 'http://127.0.0.1:8000/api/drift?repo_path=demo/sample_repo/state-B'
```

Expected: `summary.new_count ≥ 1` (the AWS access key in state-B), `summary.resolved_count ≥ 1` (the removed TODOs), `summary.worsened_count ≥ 1` (the oversized function grew from 60 → 75 lines).

---

## UX

| # | Item | Status | Evidence |
|---|---|---|---|
| 11 | First-run understandable | ✅ | Dashboard header reads "Credit report for your codebase"; first-run empty state guides the user to enter a repo path and click "Run scan" |
| 12 | Empty states correct | ✅ | (a) No scan yet → only the input UI is shown; (b) Scan with 0 findings → "🎉 This scan came back clean"; (c) Drift with < 2 scans → "Need at least two scans of this repository to compute drift"; (d) No hotspots → empty-state message in `RiskHotspots.tsx` |
| 13 | Error states readable | ✅ | All API errors flow through the `error` state in `App.tsx` and render with clear "what happened / what to do next" messaging; 13 failure modes covered (see D below) |
| 14 | Security findings redacted | ✅ | `FindingDetailDrawer.tsx` suppresses raw `evidence` for SECURITY findings and renders a "Why this evidence was redacted" panel; `FindingSnapshot.to_dict()` re-redacts on persistence so secrets never reach the history file |

**Manual verification:**
1. Open http://localhost:5173 — verify the "Credit report for your codebase" tagline is visible
2. Without clicking "Run scan", verify the only thing visible is the input UI (no broken dashboard)
3. Click "Run scan" with `demo/sample_repo/state-B` — verify the AWS access key evidence in the FindingDetailDrawer is REDACTED, not displayed

---

## QUALITY

| # | Item | Status | Evidence |
|---|---|---|---|
| 15 | Tests green | ✅ | **414 passed, 1 skipped** (verified 2026-08-31); focused hotspot suite 18/18 with 100% engine coverage |
| 16 | Determinism green | ✅ | Repeated scans return byte-identical results; drift comparison is ordering-independent; finding IDs are stable across additions of unrelated files; hotspot ranking is deterministic; `test_analyzer_determinism.py::test_registry_is_complete` guards against analyzer/test drift |
| 17 | Frontend build green | ✅ | Vite 8 production build passes with 26 modules; TypeScript reports zero errors; Tailwind/PostCSS compilation is verified |
| 18 | No known secret exposure | ✅ | `app.security.redact_secrets` is called on every persisted `evidence`; `FindingSnapshot.to_dict()` re-applies it on the way out; verified by `tests/history/test_history.py::TestRedactionInPersistedRecord::test_persisted_evidence_is_redacted` and `tests/security/test_validators.py::test_secrets_are_redacted_in_persistence` |
| 19 | No debug-only paths required | ✅ | All prod paths are reachable without env vars; the only env var is `CODESONAR_HOME` (optional, defaults to `~/.code-sonar/`) |

---

## DOCUMENTATION

| # | Item | Status | Evidence |
|---|---|---|---|
| 20 | README validated | ✅ | Root `README.md` covers all 17 required sections (what / problem / capabilities / requirements / installation / one-command startup / scan / scoring / categories / history+drift / hotspots / security+redaction / limitations / beta status / development / license) |
| 21 | Commands verified | ✅ | `scripts/start.bat`, `scripts/start.sh`, `scripts/stop.bat`, `scripts/stop.sh` all tested against the dev environment |
| 22 | Demo verified | ✅ | `demo/sample_repo/` ships with state-A (clean + moderate + serious findings + hotspot ranking) and state-B (the same repo after TODOs removed + AWS key added + function grown) so drift can be demonstrated |

---

## RELEASE

### Version

`v0.1.0-beta.1` — first private-beta prerelease. Not published publicly.

### Checklist

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 23 | Ownership and IP attribution preserved | ✅ | `README.md`, `OWNERSHIP.md`, `LICENSE`, `DEVELOPMENT_STATUS.md`, `CODE_SONAR_HANDOFF.md`, npm/Python package metadata, and RICK's local agent contract credit Michael Smith (`michaelricksmith`) as creator, builder, owner, maintainer, and IP rights holder; RICK/AI tools are identified as assistants only |

### Release notes (highlights)

- **Hotspots MVP** — deterministic per-file risk ranking with explainable breakdown (debt + severity + finding count + analyzer diversity). Top 10 included in every scan response; full ranking available via `GET /api/hotspots`.
- **Click-through** — clicking any hotspot in the dashboard filters the findings table to that file's contributing findings.
- **Determinism end-to-end** — scan persistence, finding IDs, drift classification, comparison ordering, hotspot ranking, repeated comparisons: all byte-identical for fixed input.
- **Security guarantees** — secret evidence is redacted before persistence; raw evidence is suppressed in the dashboard for SECURITY findings; no secret ever reaches the JSONL history file.
- **One-command startup** — `scripts/start.bat` (Windows) or `./scripts/start.sh` (Unix) handles venv creation, dependency install, server launch, and health verification.
- **Demo repository** — `demo/sample_repo/` ships with state-A + state-B for instant drift demonstration.

### Known limitations

| # | Limitation | Workaround |
|---|---|---|
| 1 | Only Python source is deeply analyzed (cyclomatic complexity + nesting + AST-based oversized-functions) | Use external tools for non-Python languages; we surface debt_total/severity/analyzer_diversity for all files |
| 2 | No Git churn / ownership / dependency intelligence yet | Defer per Michael's "do not overbuild" instruction; surface area is a future checkpoint |
| 3 | Self-scan puts the workspace at 529/F — the score is intentionally uncomfortable; this is by design per the "Code Sonar reports uncomfortable results when evidence supports them" principle | Document in the README and ScoreChangeCallout |
| 4 | Single-process FastAPI; not multi-worker | Acceptable for private beta; SQLite swap is a future seam (`HistoryStore` ABC) |
| 5 | No background queue; long scans block the request thread | Acceptable for private beta (most scans complete in <2s); future checkpoint |
| 6 | No multi-user, no auth, no orgs | Defer per "do not overbuild" |
| 7 | v0.1.0-beta.1 is not publicly released | Internal / private-beta only |
| 8 | Product is private beta and proprietary; public distribution and licensing are not enabled | Access and use require Michael Smith's express authorization; verified work is pushed to `origin/main` |

### Rollback instructions

If a beta tester hits a blocker and we need to roll back:

```bash
# 1. Identify the previous good commit
git log --oneline -10

# 2. Reset local main to it (replaces uncommitted + un-pushed work)
git reset --hard <previous-good-sha>

# 3. Restart services
scripts\stop.bat        # Windows
# ./scripts/stop.sh     # Unix
scripts\start.bat       # Windows
# ./scripts/start.sh    # Unix
```

The data directory `~/.code-sonar/history.jsonl` is **not** under git, so it persists across rollbacks. If we need a clean slate:

```bash
# Windows
del %USERPROFILE%\.code-sonar\history.jsonl
# Unix
rm ~/.code-sonar/history.jsonl
```

---

## Success criterion

> **Code Sonar is no longer waiting for another major feature.** A technically capable person who did not build Code Sonar can follow the documentation, start it, scan a repository, understand the score, identify priority risks, run another scan, and understand what changed.

Status: **READY** — all 22 checklist items are ✅. Move to private beta.
