## 2026-09-24 \u2014 Ask Sonar no longer defaults to a phantom Ollama provider

- Fixed "Unsupported X-AI-Provider" on hosted: the provider registry always
  reported Ollama as configured, so the UI defaulted every question to
  `X-AI-Provider: ollama` \u2014 a header the backend rejected with 400, on a host
  with no Ollama running. The registry now reports Ollama as configured only
  when `ASK_SONAR_PROVIDER=ollama` is set, and the frontend only sends
  provider/key headers when the user explicitly picks a provider via BYOK.
  Otherwise the server answers with its configured provider (or an honest
  "no provider configured" message), and the BYOK form is shown.
- `build_transient_byok_provider` now accepts `ollama` (self-hosted, no API
  key required) alongside `openai` and `anthropic`, so an explicit Ollama
  choice works wherever Ollama is actually reachable.
- New tests: Ollama transient builder (keyless, case-insensitive), registry
  Ollama configured/unconfigured from env, and an API-level regression test
  for the `X-AI-Provider: ollama` header with no key.

---

## 2026-09-24 \u2014 Remediation re-materializes its source on demand

- Fixed "Remediation source repository is unavailable" for hosted scans: scan
  workers clone into a per-job workspace that is deleted after scanning, so the
  persisted `repository_path` never existed at approval time. Scan records now
  persist `repository_slug` and `branch`; `POST /api/ask-sonar/remediation/approve-and-run`
  resolves the source via the new `app/remediation/source.py` before issuing the
  authorization \u2014 reusing the checkout when present, otherwise shallow-cloning
  the recorded repository (with the approver's GitHub OAuth token for private
  repos) inside the scan root, then cleaning up after the workflow completes.
- Records persisted before slug tracking keep the original 409 behavior.
- New tests: `backend/tests/remediation/test_source.py` (reuse, re-clone,
  cleanup, token redaction, slug parsing, record round-trip) and endpoint
  coverage for the legacy-record 409 in
  `backend/tests/api/test_ask_sonar_remediation.py`.

---

## 2026-09-23 \u2014 Hosted auth without the dev flag

- The API boundary middleware now accepts a valid signed `sonar_session`
  cookie as a first-class production authentication path, equivalent to a
  Bearer token. The OAuth handshake endpoints (`/api/auth/{github,google}/login`
  and `/callback`) stay publicly reachable so sign-in can start; every other
  `/api/` route fails closed (401) without a valid Bearer token or session
  cookie.
- `CODESONAR_LOCAL_DEV=1` is no longer required for hosted operation and has
  been removed from `render.yaml`. It keeps its local-dev behavior: with no
  credentials configured, local requests still pass through unauthenticated.
- Startup validation now also passes when `SONAR_SESSION_SECRET` is explicitly
  set (fail-closed otherwise). The Blueprint marks `SONAR_SESSION_SECRET` as
  required on the first deploy.
- `validate_persistence_config` no longer demands PostgreSQL when no database is configured at all: the hosted beta's no-database posture (signed-cookie sessions, ephemeral history) now starts with a loud warning instead of refusing to boot. SQLite/non-PostgreSQL URLs in shared mode are still rejected.
- New regression tests: `backend/tests/security/test_session_cookie_auth.py`
  (valid/tampered/expired/unknown-user cookies, Bearer coexistence, anonymous
  OAuth handshake reachability, fail-closed startup, unchanged local-dev
  bypass).

---

## 2026-09-23 \u2014 One-click Render deploy (free tier)

- Added `render.yaml` Blueprint: one free Python web service (`pip install ./backend`, frontend `npm ci && npm run build`, `uvicorn app.main:app`). No database; sessions are signed cookies.
- The backend now serves the built dashboard SPA from the same origin when `frontend/dist` exists (guarded: local dev without a build behaves exactly as before). This keeps the UI's relative `/api` calls and the SameSite=Lax session cookie working with no CORS configuration \u2014 a separate Render static site cannot proxy `/api` to the backend.
- Render deploy is a two-step URL dance (documented in README): deploy once, then set `SONAR_PUBLIC_URL` / `CODESONAR_CORS_ORIGINS` to the public URL and redeploy before registering the GitHub/Google OAuth apps.
- ~~Superseded 2026-09-23 (see entry above): `CODESONAR_LOCAL_DEV=1` was set in the Blueprint so the hosted dashboard's OAuth session-cookie flow was accepted by the API boundary middleware.~~

---

## 2026-09-23 \u2014 User OAuth, async scan jobs, hosted Ask Sonar providers\n\n- Added real GitHub + Google OAuth Authorization Code flows (GET /api/auth/{github,google}/login \u2192 302 authorize redirect with signed state; /callback exchanges the code, fetches the profile, upserts a server-side user record, sets the HttpOnly Secure SameSite=Lax `sonar_session` signed-JWT cookie, and 302s to /app). GET /api/auth/me, POST /api/auth/logout, and GET /api/auth/repos (user's GitHub repos via their OAuth token) included. OAuth tokens are stored server-side only (0600 JSON store) and never returned to clients; all config from env only.\n- Added async scan jobs: POST /api/scan-job {repo: 'owner/name' or URL, branch?} shallow-clones into the scan-root workspaces dir (<scan-root>/workspaces/<job_id>/) (OAuth token injected for private repos, never logged or exposed) then runs the unchanged existing scan pipeline \u2014 same analyzers, scoring engine, and history store. GET /api/scan-job/{job_id} reports queued/running/done/error with human-readable steps ('Reading your files\u2026', 'Running 8 checks\u2026', 'Tallying your score\u2026').\n- Added hosted Ask Sonar providers: OpenAICompatibleProvider (configurable base_url, default https://api.openai.com/v1) and AnthropicProvider (native Messages API), following the Ollama dataclass pattern with injectable transports and a plain-language system instruction for non-technical users. GET /api/ask-sonar/providers lists {name, label, configured, source}. POST /api/ask-sonar/ask accepts X-AI-Provider + X-AI-API-Key headers for transient per-request BYOK (never persisted or logged). Env: ASK_SONAR_PROVIDER, OPENAI_API_KEY, ANTHROPIC_API_KEY, ASK_SONAR_BASE_URL, ASK_SONAR_MODEL (legacy CODE_SONAR_ASK_PROVIDER=ollama still works). Unconfigured providers return an honest error naming exactly what is missing.\n- Fixed the httpx proxy-env import crash: module-level httpx.Client constructions in github_integration.py and github_app.py now use trust_env=False (the VM's NO_PROXY contains bracketed IPv6 entries httpx cannot parse).\n- No scoring, analyzer, drift, or remediation behavior changed.\n\n---\n\n## 2026-09-08 — Installed Cursor host-proof runner\n\n- Added a guarded, fail-closed operator runner for the authenticated Cursor Agent CLI.\n- The runner uses an ephemeral fixture and production remediation components, records sanitized evidence, and never overwrites an existing evidence file.\n- Success requires passing tests, resolved finding, deterministic score improvement, active-checkout isolation, and cleanup.\n\n---\n\n## 2026-09-08 — Cursor remediation proof\n\n- Added a concrete real-Git integration test spanning authorization, isolated worktree creation, Cursor executor boundary, validation tests, Code Sonar rescan, deterministic score/debt comparison, outcome persistence, active-checkout isolation, and cleanup.\n- Added a fail-closed operator evidence gate for the required installed-Cursor run on the authorized Windows development host.\n- No production Cursor-success claim is made until that host evidence passes.\n\n---\n\n# Code Sonar — Changelog

**Created, built, and owned by Michael Smith (GitHub: `michaelricksmith`). Copyright © 2026 Michael Smith. All rights reserved.**

All notable changes to Code Sonar are documented in this file. The
format is loosely based on [Keep a Changelog](https://keepachangelog.com/)
without semantic-versioning.

## 2026-09-02 — Blinded calibration pilot workflow

- Added versioned score-blinded review packets, deterministic stratified finding
  sampling, reviewer/adjudication rubric, and fail-closed pilot orchestration.
- No repositories, labels, scoring weights, thresholds, or score versions changed.
- Added an operator-only candidate manifest with eight license-verified public
  repositories pinned to commits and four explicitly unpopulated controlled
  slots; repository identity never enters reviewer packets.

---

## [Unreleased] — 2026-09-02

### Onboarding readiness

- Added a redacted production preflight CLI and authenticated API with stable
  blocker codes and a non-blocking Ask Sonar provider check.
- Versioned the analyzer execution contract alongside scoring authority.
- Added operator onboarding and client data-flow/privacy documentation without
  claiming certification or external deployment.

### Added
- Added tenant retention-policy records and authenticated/audited privacy APIs;
  encrypted, versioned export jobs exclude host paths, secrets, and tenant IDs.
- Added a recovery-gated, operator-only hard-delete command with PostgreSQL
  concurrency locking, FK-safe removal, idempotent content-free receipts, and a
  deployment crypto-erasure hook. Backup retention/deletion lag is policy
  metadata, not a claim of managed backup or erasure completion.
- Added a tenant-aware SQLAlchemy persistence unit of work and Alembic baseline
  for projects, scans/findings, GitHub installations/webhooks/jobs, and
  remediation outcomes. Project scan persistence is atomic, webhook claims and
  worker leases use database compare-and-set semantics, and PostgreSQL is
  required for shared deployments.
- Added tenant-bound AES-GCM checkout-path encryption for local SQL development,
  a production encryption-provider injection contract, guarded data-root
  permission checks, and an explicit idempotent legacy JSON/JSONL importer with
  a transactional verification ledger.
- Added the Credit Report Signal Core: an accessible semantic 300–850 meter,
  live-evidence sonar field, integrated grade/risk narrative, scan provenance,
  and a clearer three-item remediation priority queue.
- Added Calibration Evidence v1: anonymized and hashable evidence contracts,
  privacy-safe scan capture, deterministic benchmark metrics with confidence
  intervals/strata, and a metadata-only 12-case pilot manifest.
- Added deterministic per-finding and per-category score contribution details.
- Added server-derived tenant identity from unique configured bearer tokens,
  tenant-scoped projects, scan history, Ask Sonar/remediation-plan access and
  GitHub installations, plus cross-tenant denial regression coverage. Caller
  tenant headers do not influence authorization. Verified GitHub webhooks bind
  to the server-owned installation tenant for project lookup and queued work;
  unknown installations remain unassigned and cannot resolve projects.
- Unified local and managed GitHub repository selection into one active frontend
  context shared by Overview, Findings, Risk Map, History, Ask Sonar, and
  Remediations. Persisted project baselines retain the backend's deterministic
  score and expose explicit empty states when live-only hotspot data is absent.
- Added explicit per-analyzer execution status, scoring-version provenance in
  scan/history payloads, backward-compatible legacy history loading, and a
  versioned blinded-label benchmark scaffold.
- Phase 2 began with a responsive application shell, accessible mobile navigation, and a redesigned real-data credit-score command center. The command center preserves the deterministic 300–850 score, grade, category normalization, findings, debt, severity, priority, repository, and scan metadata from the native scan response.


- Added pinned Playwright 1.62.1 as a frontend development dependency and installed its Chromium runtime for browser-level validation.
- Added RICK's isolated first capability wave: Trivy 0.74.0, Mermaid CLI 11.16.0, Sumy 0.13.0, Debugpy 1.8.21, and Streamlit 1.62.0; verified the existing VS Code JS Debug 1.117.0 component.
- Added role-scoped OpenClaw skills for browser testing, security scanning, diagrams, local summarization, debugging, and Streamlit prototypes while preserving existing execution approval gates.
- Rebuilt intelligence-focused dashboard and credit-report workflow through merge commit `d73e9ba`.
- Added same-file ordering regression coverage for risk-hotspot serialization.
- Added `frontend/postcss.config.cjs` so Tailwind utilities compile into production CSS.

### Fixed

- Removed the duplicate GitHub project dashboard mounted above every page; the
  tenant-aware project panel now appears only inside Repositories and retains
  the unified active-project context.

- Scoring now rejects duplicate finding IDs and uses canonical ordering plus
  accurate summation so adversarial input permutations cannot change results.
- Dead-code finding IDs now use stable SHA-256 inputs including source location,
  preventing same-named methods from colliding across classes.

- Prevented partial analyzer runs from silently producing an authoritative
  score or perfect A grade; incomplete scans now fail closed without a grade.

- Updated `eslint-plugin-react-hooks` from the incompatible 4.6 line to 5.2.0 and added an ESLint 9 flat configuration so the frontend lint command runs without forced or legacy dependency bypasses.
- Made `contributing_finding_ids` deterministic regardless of finding input order (`02207ea`).
- Removed redundant hotspot category-breakdown computation (`02207ea`).
- Restored the frontend production build environment and Tailwind processing (`331b611`).

### Security and maintenance

- Replaced caller-controlled remediation booleans and paths with a server-owned,
  signed, expiring, single-use authorization bound to the persisted scan,
  finding, plan, repository commit, executor, and remediation kind.
- Remediation worktrees and branches are removed after successful, failed, or
  stopped execution; expired authorizations cannot create a workspace.
- Closed legacy direct prepare/execute/validate/run endpoints and removed host
  repository paths from manual scan and history API responses.
- Added fail-closed bearer authentication for `/api/**`, preserving GitHub
  webhook HMAC authentication as the only exception.
- Replaced wildcard CORS with an exact, environment-configured origin allowlist.
- Made the configured scan root mandatory for caller-controlled scan, hotspot,
  history/drift, and remediation source paths; unsafe legacy path access now
  requires an explicit local-development flag.
- Removed unused vulnerable `react-router-dom` and `vitest` dependencies.
- Upgraded Vite to 8.2.2 and `@vitejs/plugin-react` to 6.1.1 (`61f086a`).
- Verified `npm audit`: 0 vulnerabilities.
- Verified backend: 414 passed, 1 skipped; frontend TypeScript/Vite production build: passed.

### Ownership

- Clarified that Michael Smith (`michaelricksmith`) is Code Sonar's creator, builder, owner, maintainer, and intellectual-property rights holder. RICK and other development tools are assistants only and hold no ownership rights.

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

- **`PRIVATE_BETA_CHECKLIST.md`** — originally a 22-item acceptance gate for private beta; now includes a 23rd ownership/IP preservation gate
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
- Historical release baseline: pytest **324 passed, 1 skipped**. Current verified baseline is **414 passed, 1 skipped** as documented in the 2026-08-31 Unreleased section.
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
- Historical development environments required manual authenticated pushes; the current workflow verifies and pushes completed tasks to `origin/main`

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


## [Unreleased] — Original UI integration

### Added

- Space-inspired, reduced-motion-aware first-run repository gateway.
- Clear local checkout and GitHub App onboarding paths.
- Honest disabled state for planned ZIP archive ingestion.

### Preserved

- Deterministic 300–850 scoring authority.
- Native repository API clients, findings, hotspots, drift, history, Ask Sonar, and remediation workflows.
