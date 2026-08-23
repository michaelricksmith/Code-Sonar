# Code Sonar — Changelog

All notable changes to Code Sonar are documented in this file. The
format is loosely based on [Keep a Changelog](https://keepachangelog.com/)
without semantic-versioning.

---

## [v0.1.0-beta.1] — 2026-08-22

**Status:** First private-beta prerelease. Internal only — not published
publicly.

### Added

- **Risk Hotspots (Phase 1 of Fastest-Route-to-Private-Beta)** — deterministic
  per-file risk ranking with explainable per-file breakdown.
  - `backend/app/hotspots/__init__.py` — pure-function `compute_hotspots(findings, top_n=10)`
  - Hotspot score = `debt_total + severity_max_weight + finding_count + analyzer_diversity × 2`
  - Top-10 hotspots included in every `ScanResponse`
  - `GET /api/hotspots?repo_path=&limit=` for full ranking
  - `frontend/src/components/RiskHotspots.tsx` — ranked hotspot list with
    per-file breakdown, anomalies panel (single high-severity / multi-analyzer
    agreement), click-through to contributing findings
  - 17 backend tests covering determinism, ordering-independence,
    metadata extraction, explainability, realistic scenarios

- **One-command startup scripts**
  - `scripts/start.bat` (Windows-first; auto-picks port 8000 or 8765;
    launches backend + frontend in separate windows; waits for health check)
  - `scripts/start.sh` (Unix / macOS / WSL; backgrounds via `nohup`; PID files in `logs/`)
  - `scripts/stop.bat` / `scripts/stop.sh` — clean shutdown

- **Demo repository** — `demo/sample_repo/` with two states:
  - `state-A/` — clean + moderate + serious findings, intentional hotspots
  - `state-B/` — same files with TODOs removed + AWS access key added + function grown
  - Together they demonstrate the full drift story (NEW + RESOLVED + WORSENED)
  - AWS access key is intentionally fake-looking (not a real credential)

- **`PRIVATE_BETA_CHECKLIST.md`** — 22-item acceptance gate for private-beta
  readiness (INSTALLATION / SCAN / UX / QUALITY / DOCUMENTATION / RELEASE)

### Checkpoint 6 (carried in from prior commit `0d7b220`)

- **Drift detection + scan history** — pure-function drift engine,
  `JsonlHistoryStore` (atomic writes via `os.replace`), 5 new API endpoints
  (`POST /api/scan` auto-records, `GET /api/history/list`, `GET /api/history/latest`,
  `GET /api/history/{scan_id}`, `GET /api/drift`)
- **DriftView** — score/debt/finding movement cards, drift filter chips,
  per-finding state badges, category + analyzer drill-downs
- **Finding-ID stability audit** — 2 ID bugs in Checkpoint 5 analyzers fixed
  (`oversized_functions` dropped `length` from hash; `testing_debt` added
  `lines_bucket` to `untested-module` hash)
- **Evidence redaction on persistence** — `FindingSnapshot.to_dict()` redacts
  via `app.security.redact_secrets` on the way out (defense in depth)

### Acceptance gates (all GREEN)

- ruff: All checks passed
- mypy: Success, no issues found in 27 source files (+1 from C6's 26)
- pytest: **324 passed, 1 skipped** (up from 307 at C6; +17 from hotspots tests)
- frontend tsc --noEmit: clean
- vite build: 40 modules, 180.00 kB / 54.98 kB gzip, 348 ms
- Drift determinism: byte-identical for reordered inputs and repeated calls
- Scan persistence: byte-identical `load_all()` across repeated calls
- Repository isolation: repoA history never appears in repoB's `load_all()`
- No secrets through storage/API/UI: `FindingSnapshot.to_dict()` redacts on the way out

### Known limitations

See `PRIVATE_BETA_CHECKLIST.md` § Known limitations. Highlights:
- Only Python source is deeply analyzed (cyclomatic complexity + nesting + AST-based oversized-functions); other languages surface `debt_total/severity/analyzer_diversity` only
- No Git churn / ownership / dependency intelligence yet (deferred per "do not overbuild")
- Single-process FastAPI (SQLite swap is a future seam via `HistoryStore` ABC)
- No multi-user / auth / orgs (deferred)
- Not publicly released (internal / private-beta only)
- `git push` from the dev environment fails with OAuth-app credential blocker;
  commits accumulate on local main and reach `origin/main` manually

---

## [unreleased] — pre-v0.1.0-beta.1 development history

Phase 1–5 work (`b9bd8eb` → `bbbe607` → `332b4e7` → `b396110` → `de6808c` →
`0235901` → `fc3084d` → `0d7b220`) is reflected in `git log --oneline main` and
in `DEVELOPMENT_STATUS.md`. Highlights:

- MVP vertical slice (`b9bd8eb`)
- 7 analyzers: `comment_markers`, `oversized_files`, `oversized_functions`,
  `cyclomatic_complexity`, `nesting_depth`, `secrets`, `testing_debt`
- `DeadCodeAnalyzer` (`fc3084d`) — `unreachable`, `unused-private`, `stale-fixture`
- `path_classifier.py` (SOURCE / TEST / FIXTURE) + scoring audit
- Source-context modifier (1.0× / 0.25× / 0.25× at CATEGORY level)
- Shared determinism helpers + applied to all 8 analyzers
- 300–850 FICO-like scoring engine with documented rationale (50-line module docstring)
- CORS-enabled FastAPI + React dashboard
- `.github/workflows/ci.yml` 3-job CI (backend ruff + mypy + pytest, frontend tsc + vite, smoke self-scan)
- CI #1 fix: `0235901` ruff + mypy strict (26 files, +170/−166, zero product behavior change)
- GitHub repo: `michaelricksmith/code-sonar` (PRIVATE)
