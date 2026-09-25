> **Installed-Cursor host proof:** Run `backend/scripts/cursor_remediation_proof.py --evidence <new-json-path>` from a clean checkout. The guarded runner uses the authenticated Cursor Agent CLI inside a disposable Code Sonar worktree and fails unless tests pass, the finding resolves, the score improves, the active checkout is unchanged, and cleanup completes.\n\n> **Cursor remediation proof in progress (2026-09-08):** A concrete real-Git integration test now covers authorization, isolated worktree execution, tests, rescan, deterministic score improvement, active-checkout isolation, outcome capture, and cleanup. CI simulates only the external Cursor binary boundary. An installed-Cursor run on the authorized Windows host is still required before claiming the complete proof. See [docs/cursor-remediation-proof.md](docs/cursor-remediation-proof.md).\n\n# Code Sonar

**Created, built, and owned by Michael Smith (GitHub: [michaelricksmith](https://github.com/michaelricksmith)).**

Copyright © 2026 Michael Smith. Code Sonar—including its source code, product design, specifications, branding, and documentation—is proprietary intellectual property. All rights reserved unless Michael Smith expressly grants otherwise in writing.

> **Credit report for your codebase.**
- Phase 2 began with a responsive application shell, accessible mobile navigation, and a redesigned real-data credit-score command center. The command center preserves the deterministic 300–850 score, grade, category normalization, findings, debt, severity, priority, repository, and scan metadata from the native scan response.


Code Sonar scans a software repository, produces a single credit-score-style
metric (300–850), and tells you *why* it is what it is — which files
carry the most risk, what the dominant failure modes are, and what
changed since your last scan.

It is **deterministic and explainable**: the 300–850 score is computed by
local analyzers with no LLM and no randomness. The app can run fully
self-hosted; hosted features (GitHub/Google sign-in and hosted AI
explanations for Ask Sonar) send only what those features need to their
providers. We read your code to score it — we never train on it.

> **Status:** v0.2.0-beta (public beta).

Production onboarding has a redacted preflight at `GET /api/ops/readiness` and
`backend/scripts/readiness.py`. It fails closed on missing security,
persistence, integration, scoring-calibration, privacy, and remediation gates.
See [`docs/CLIENT_ONBOARDING_RUNBOOK.md`](docs/CLIENT_ONBOARDING_RUNBOOK.md) and
[`docs/CLIENT_DATA_FLOW_AND_PRIVACY.md`](docs/CLIENT_DATA_FLOW_AND_PRIVACY.md).

---

## Table of contents

1. [What is Code Sonar?](#1-what-is-code-sonar)
2. [What problem does it solve?](#2-what-problem-does-it-solve)
3. [Current capabilities](#3-current-capabilities)
4. [Screenshots](#4-screenshots)
5. [Requirements](#5-requirements)
6. [Installation](#6-installation)
7. [One-command startup](#7-one-command-startup)
8. [How to scan a repository](#8-how-to-scan-a-repository)
9. [How scoring works](#9-how-scoring-works)
10. [Finding categories](#10-finding-categories)
11. [Scan history + drift](#11-scan-history--drift)
12. [Risk hotspots](#12-risk-hotspots)
13. [Security / redaction behavior](#13-security--redaction-behavior)
14. [Known limitations](#14-known-limitations)
15. [Private-beta status](#15-private-beta-status)
16. [Development status](#16-development-status)
17. [License / status](#17-license--status)

---

## 1. What is Code Sonar?

Code Sonar is a credit-score-for-your-codebase tool. You point it at
a repository and it returns:

- A **score** (300–850, like a FICO score) and a **grade** (A / B / C / D / F)
- A **debt-point total** — how much maintenance pain the codebase carries
- A list of **findings** — what specific things are wrong, where they are, and how to fix them
- A list of **risk hotspots** — which files carry the most risk, with an explainable per-file breakdown
- A **drift view** — what changed in your technical debt since the previous scan

It is a **FastAPI + React** application. The backend runs deterministic
Python analyzers (no LLM, no randomness); the frontend is a single-page
dashboard.

---

## 2. What problem does it solve?

Software accumulates technical debt. The debt is usually invisible:
TODO comments, oversized functions, secrets in code, low test coverage.
By the time anyone notices, the codebase has rotted past the point of
easy recovery.

Code Sonar makes the debt **visible, quantified, and prioritized**.
You get a single number that summarizes the codebase's health, plus
the file-by-file breakdown that tells you where to start fixing.

It is **not** a replacement for human code review. It is a navigation
aid — the equivalent of a credit report for a borrower who has never
seen their FICO score.

---

## 3. Current capabilities

- **8 analyzers** running by default (see [§ 10](#10-finding-categories)):
  - `comment_markers` — TODO / FIXME / HACK / XXX
  - `oversized_files` — files above a configurable line-count threshold
  - `oversized_functions` — Python AST, function/method/nested-def detection
  - `cyclomatic_complexity` — uses `radon` for Python
  - `nesting_depth` — pure AST walker
  - `secrets` — AWS / GitHub PAT / Slack / JWT / high-entropy
  - `testing_debt` — modules without test coverage
  - `dead_code` — unreachable statements, unused-private, stale-fixture
- **Deterministic scoring** — the same input always produces the same
  output (score, grade, finding IDs). No randomness, no LLM, no
  external services.
- **Scan history** — every scan is auto-recorded to a local JSONL file
  at `~/.code-sonar/history.jsonl`. Repository-isolated.
- **Drift detection** — compare any two historical scans. NEW /
  RESOLVED / PERSISTENT / WORSENED / IMPROVED classifications.
- **Risk hotspots** — deterministic per-file risk score with explainable
  breakdown (debt total + severity max + finding count + analyzer
  diversity).
- **Click-through** — clicking a hotspot filters the findings table to
  that file's contributing findings.
- **Security redaction** — secret evidence is redacted on disk and in
  the UI; the dashboard never displays raw secrets.
- **One-command startup** — `scripts/start.bat` (Windows) or
  `./scripts/start.sh` (Unix) launches backend + frontend with health
  verification.
- **Demo repository** — `demo/sample_repo/` ships with state-A and
  state-B so you can see the full drift story without setting up your
  own repo.

---

## 4. Screenshots

Screenshot placeholders. Captures will be added during the private
beta once we have a polished dashboard with real-data runs against
real repositories.

| Screen | Placeholder |
|---|---|
| Dashboard (score + summary cards) | _to be captured during private beta_ |
| Risk hotspots section | _to be captured during private beta_ |
| Drift view | _to be captured during private beta_ |
| Finding detail drawer | _to be captured during private beta_ |

---

## 5. Requirements

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.11, 3.12, 3.13 supported; venv at `backend/.venv` created automatically |
| Node.js | 20+ | npm 10+ for the frontend |
| OS | Windows 10+ / macOS 12+ / Linux (Ubuntu 22.04+) | Windows is the primary development platform |
| Disk | ~500 MB | mostly `node_modules/` (~400 MB) and the Python venv (~150 MB) |

**No Docker.** **No cloud account.** **No API key.** All computation is
local.

---

## 6. Installation

```bash
# 1. Clone the repo
git clone https://github.com/michaelricksmith/code-sonar.git
cd code-sonar

# 2. Start it (handles venv + pip install + npm install automatically)
#    Windows:
scripts\start.bat
#    Unix / macOS / WSL:
./scripts/start.sh
```

The startup script will:
1. Verify Python and Node are on your PATH
2. Create `backend/.venv/` if missing
3. Install backend dependencies (`pip install -e ".[dev]"`) if missing
4. Install frontend dependencies (`npm install`) if missing
5. Launch the backend (port 8000, or 8765 if 8000 is busy)
6. Wait for the backend `/health` endpoint to return 200 (up to 20 seconds)
7. Launch the frontend (port 5173)

You should see:

```
=== Code Sonar is starting ===========================================
  Backend:  http://127.0.0.1:8000
  Frontend: http://localhost:5173
```

Open **http://localhost:5173** in your browser.

---

## 7. One-command startup

Already covered in [§ 6](#6-installation). One command, two windows
(or two background processes on Unix). No Docker.

To shut down:

```bash
# Windows
scripts\stop.bat

# Unix
./scripts/stop.sh
```

The stop scripts kill the backend and frontend windows (Windows) or
send SIGTERM to the PIDs (Unix). Belt-and-braces: any leftover process
bound to ports 8000 / 8765 / 5173 is also killed.

---

## 8. How to scan a repository

1. Open http://localhost:5173 in your browser.
2. In the **Repository path** input, type the absolute path to a
   repository you want to scan.
3. Click **Run scan**.
4. The dashboard populates with:
   - Score and grade
   - Findings count and total debt points
   - Source / test / fixture breakdown
   - Category scores
   - Top 10 risk hotspots
   - Findings table (filterable by severity / category / analyzer / search)
5. To see what changed, click **Compare with previous scan**. If you
   haven't scanned this repo before, the dashboard tells you to run
   another scan first.

**Try the demo:**

Scan `demo/sample_repo/state-A` first. You'll see ~3-5 findings. Then
scan `demo/sample_repo/state-B` (which removes the TODOs and adds an
AWS access key in `app/legacy.py`). Click **Compare with previous scan**
to see the drift: NEW (the AWS key), RESOLVED (the TODOs), WORSENED
(the oversized function grew from 60 to 75 lines).

---

## 9. How scoring works

Code Sonar uses a **FICO-style 300–850 score** where higher is better.
The grade bands are:

| Score | Grade | Interpretation |
|---|---|---|
| 800–850 | A | Healthy — minor issues, well-kept code |
| 740–799 | B | Good shape — a few things to tidy up |
| 670–739 | C | Fair — several issues worth fixing soon |
| 580–669 | D | Needs attention — plan your fixes |
| 300–579 | F | Critical — prioritize fixes now |

**The score is computed in three layers:**

1. **Severity math** — every finding carries `debt_points` based on its severity:
   - INFO = 1 debt point
   - WARNING = 2 debt points + 1 flat bonus
   - ERROR = 4 debt points + 3 flat bonus
   - CRITICAL = 8 debt points + 8 flat bonus
   The flat bonus keeps low-severity findings distinguishable in the score.
2. **Category weighting** — debt is bucketed into 6 categories (complexity, staleness, security, duplication, testing, maintainability) and weighted: COMPLEXITY 0.30, STALENESS 0.25, SECURITY 0.25, DUPLICATION 0.10, TESTING 0.10, MAINTAINABILITY 0.10. Per-category penalty is capped at 550 BEFORE category weighting. The category weights sum to 1.20 (extra headroom for overlapping categories).
3. **Source-context modifier** — findings in tests/ and fixture/ directories are multiplied by 0.25× AT THE CATEGORY LEVEL (not per-finding). This mutes bulk fixture findings from dominating the score. Test code carries its own debt, but not at production-code weight.

The full rationale is documented in `backend/app/scoring/engine.py`
(50-line module docstring).

**Confidence modifier:** findings with `confidence < 0.7` are halved.

**Code Sonar reports uncomfortable results when the evidence supports
them.** The score is not adjusted to make you feel better about your
codebase. If the analyzers find debt, the score reflects that debt.

---

## 10. Finding categories

| Category | Default weight | Examples |
|---|---|---|
| **Complexity** | 0.30 | oversized_functions, cyclomatic_complexity, nesting_depth |
| **Security** | 0.25 | secrets (AWS, GitHub PAT, JWT, etc.) |
| **Staleness** | 0.25 | TODO / FIXME / HACK / XXX comments |
| **Testing** | 0.10 | untested-module (testing_debt analyzer) |
| **Maintainability** | 0.10 | oversized_files, dead_code (unreachable / unused-private / stale-fixture) |
| **Duplication** | 0.10 | (reserved — no analyzer shipped yet) |

Each finding has a category, severity (info / warning / error /
critical), a debt-point contribution, a file path + line number, an
evidence string, and a `confidence` (0–1).

The 8 active analyzers:

| Analyzer | Category | What it detects |
|---|---|---|
| `comment_markers` | staleness | TODO / FIXME / HACK / XXX in source code |
| `oversized_files` | maintainability | files above 500 lines (configurable) |
| `oversized_functions` | complexity | Python functions/methods/nested defs above 50 lines (configurable) |
| `cyclomatic_complexity` | complexity | CC ≥ 10 (radon-based) |
| `nesting_depth` | complexity | AST-walking max depth ≥ 4 |
| `secrets` | security | AWS / GitHub PAT / Slack / JWT / high-entropy |
| `testing_debt` | testing | modules without test coverage |
| `dead_code` | maintainability | unreachable statements, unused private functions, stale test fixtures |

---

## 11. Scan history + drift

Every `POST /api/scan` automatically records the scan to
`~/.code-sonar/history.jsonl` (atomic writes, schema-versioned,
repository-isolated).

**API endpoints:**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/history/list?repository_id=&limit=` | Paginated scan summaries |
| `GET` | `/api/history/latest?repo_path=` | Most-recent full record for a repo |
| `GET` | `/api/history/{scan_id}` | Full record by scan_id |
| `GET` | `/api/drift?repo_path=&from_scan_id=&to_scan_id=` | Drift between two historical scans (default: latest vs second-latest) |

**Drift classifications:**

- **NEW** — finding exists in current scan but not baseline
- **RESOLVED** — finding existed in baseline but not current
- **PERSISTENT** — same finding_id in both with equivalent risk
- **WORSENED** — same finding_id, risk increased (debt × severity_weight)
- **IMPROVED** — same finding_id, risk decreased

Drift is **deterministic and ordering-independent**: two scans with
the same findings in different orders produce byte-identical drift
results.

The dashboard's **Drift since previous scan** section renders score
movement ("785 → 742, −43 points"), debt movement, finding movement
("+8 new / −3 resolved / 2 worsened / 1 improved"), filter chips
(All / New / Resolved / Persistent / Worsened / Improved), and per-category
+ per-analyzer drill-downs.

---

## 12. Risk hotspots

The Risk Hotspots section ranks your files by risk. Top 10 included in
every scan response; full ranking via `GET /api/hotspots`.

**Hotspot score** (no arbitrary tuning — uses weights that already
exist in the drift engine and scoring engine):

```
hotspot_score = debt_total + severity_max_weight + finding_count + analyzer_diversity × 2
```

Where `severity_max_weight` is the same severity-weight table as the
drift engine (info=1, warning=2, error=3, critical=4).

The per-file breakdown shows:
- `score` (top-line number, large)
- `severity_max` (highest severity on the file)
- `finding_count` + `debt_total`
- `analyzer_diversity` (number of distinct analyzers flagging the file)
- `analyzer_breakdown` chips (e.g. `cyclomatic_complexity ×2`, `comment_markers ×1`)
- Optional metadata-derived signals: `complexity_max`, `size_max`,
  `nesting_max` (extracted from analyzer `metadata` when present)
- An **anomalies panel** highlights: files with single high-severity
  findings; files flagged by many analyzers (multi-analyzer agreement)

**Clicking a hotspot filters the findings table below to that file's
contributing findings.** This is the "click-through" requirement from
the Fastest-Route-to-Private-Beta brief.

---

## 13. Security / redaction behavior

Code Sonar treats secrets as **first-class security concerns**:

The optional transactional persistence boundary uses SQLAlchemy repositories
and an Alembic tenant-aware baseline. Shared deployments fail closed unless
PostgreSQL and a deployment-injected production encryption provider are
configured; SQLite and the bundled AES-GCM provider are local-development only.
See [Transactional persistence](docs/TRANSACTIONAL_PERSISTENCE.md) for migration,
legacy import, filesystem, and remaining-readiness boundaries.
See [Operational privacy](docs/OPERATIONAL_PRIVACY.md) for tenant retention
records, encrypted export jobs, the deletion recovery/operator workflow, and
the explicit managed-KMS/object-storage/backup limitations.

### API and repository boundary

- Every `/api/**` route requires `Authorization: Bearer <token>` from
  `CODESONAR_API_TOKEN`. The GitHub webhook is the sole exception because it
  retains its dedicated HMAC verification.
- Shared deployments can configure `CODESONAR_API_TENANT_TOKENS` as a JSON
  object mapping tenant IDs to unique bearer tokens. Tenant identity is derived
  only from that server-side credential binding; `X-Code-Sonar-Tenant` and
  other caller-provided identity headers are ignored. Projects, scans/history,
  Ask Sonar grounding and remediation plans, and GitHub installations are
  tenant-scoped. The legacy `CODESONAR_API_TOKEN` remains bound to
  `CODESONAR_TENANT_ID` (default `local`) for single-tenant compatibility.
- Auth-exempt GitHub webhooks derive their tenant only by resolving the signed
  payload's installation ID against the server-owned installation registry.
  That binding follows queued scans and scopes webhook job/audit reads. Unknown
  installations cannot claim or resolve a tenant project.
- The server refuses to start without authentication configured. Valid
  production postures: `CODESONAR_API_TOKEN` (or `CODESONAR_API_TENANT_TOKENS`)
  for Bearer-token clients, or `SONAR_SESSION_SECRET` for OAuth
  session-cookie sign-in. Tokenless, secretless operation requires both
  `CODESONAR_LOCAL_DEV=1` and a loopback `CODESONAR_HOST`.
- `CODESONAR_CORS_ORIGINS` is a comma-separated exact origin allowlist. Its
  defaults include only the local frontend on ports 3000 and 5173.
- Caller-supplied scan, hotspot, history/drift, and remediation source paths
  must resolve below `CODESONAR_SCAN_ROOT` (default: the platform temporary
  directory's `code-sonar-scans` folder). The local launch scripts explicitly
  opt into `CODESONAR_UNSAFE_ALLOW_ANY_SCAN_PATH=1` for developer convenience;
  this flag must never be used for a shared or client-facing deployment.
- Remediation execution is available only through the grounded Ask Sonar
  approval workflow. Approval creates a server-owned signed capability that
  expires after five minutes, is bound to the scan/finding/plan/base commit and
  configured executor, and can be consumed only once. Direct caller-controlled
  remediation endpoints return `410 Gone`.
- Prepared remediation worktrees and branches are cleaned after every workflow
  exit. Public scan, history, and remediation responses do not include server
  repository paths.

This checkpoint provides application-layer tenant isolation for the existing
local stores. It does not replace the planned encrypted, transactional
production persistence layer.

1. **Detection** — the `secrets` analyzer matches AWS access keys, AWS
   secret keys, GitHub PATs, Slack tokens, JWTs, and high-entropy
   strings (≥ 32 chars of `[A-Za-z0-9+/=]` with no whitespace).
2. **UI suppression** — when you open a SECRET finding in
   `FindingDetailDrawer`, the raw `evidence` field is **never
   displayed**. Instead, the drawer shows a "Why this evidence was
   redacted" panel with the redaction reason and any safe surrounding
   context (from `metadata.safe_context` when present).
3. **Persistence redaction** — when a scan is recorded to the history
   file, every finding's `evidence` field is run through
   `app.security.redact_secrets` on the way out. **Defense in depth:**
   even if a snapshot was constructed from raw evidence, the persisted
   form has secrets replaced with `[REDACTED]`.
4. **API responses** — the `/api/scan`, `/api/history/*`, and
   `/api/drift` endpoints all return redacted evidence. Raw secrets
   never leave the analyzer.

**Verification:** `backend/tests/history/test_history.py::TestRedactionInPersistedRecord::test_persisted_evidence_is_redacted`
constructs a finding with a 30-char alphanumeric secret in `evidence`
and asserts the loaded record has it replaced with `[REDACTED]`.

---

## 14. Known limitations

| # | Limitation | Notes |
|---|---|---|
| 1 | Only Python source is deeply analyzed | Non-Python files still surface `debt_total/severity/analyzer_diversity` from comment_markers, secrets, oversized_files |
| 2 | No Git churn / ownership / dependency intelligence | Deferred per "do not overbuild" instruction. Future checkpoint. |
| 3 | Single-process FastAPI; not multi-worker | SQLite swap is a future seam via the `HistoryStore` ABC |
| 4 | No background queue; long scans block the request thread | Most scans complete in <2s |
| 5 | No multi-user / auth / orgs | Deferred per "do not overbuild" |
| 6 | Self-scan puts the workspace at 529/F | This is by design — Code Sonar reports uncomfortable results when the evidence supports them |
| 7 | v0.1.0-beta.1 is not publicly released | Internal / private-beta only |
| 8 | Private-beta product; public licensing and distribution are not enabled | Access and use require Michael Smith's express authorization |

---

## 15. Private-beta status

**Version:** v0.1.0-beta.1 (first private-beta prerelease, 2026-08-22).
**Distribution:** internal only — not published publicly.
**Audience:** 5–10 technically capable users who did not build Code
Sonar and can give honest feedback on real repositories.

See [`PRIVATE_BETA_CHECKLIST.md`](PRIVATE_BETA_CHECKLIST.md) for the
23-item acceptance gate. All items are ✅ as of the current verification.

---

## 16. Development status

| Stage | Status |
|---|---|
| MVP vertical slice | ✅ Shipped (`b9bd8eb`) |
| Sprint 2 analyzers | ✅ Shipped (commits `332b4e7`, `bbbe607`) |
| Sprint 2 build-mode | ✅ Shipped (commit `b396110`) |
| Checkpoint 4 (secrets analyzer + category breakdown) | ✅ Shipped (`de6808c`) |
| Checkpoint 5 (dead_code analyzer + scoring audit + security UX + shared determinism) | ✅ Shipped (`fc3084d`) |
| Checkpoint 6 (drift detection + scan history) | ✅ Shipped (`0d7b220`) |
| Checkpoint 7 (risk hotspots + private-beta productization) | ✅ Shipped (this release) |
| Intelligence UI rebuild | ✅ Shipped (`d73e9ba`) |
| Unified repository/scan UI context | ✅ Implemented across core product areas |
| Credit Report Signal Core | ✅ Live-data sonar score hero, accessible meter, responsive priority queue |
| Hotspot determinism hardening | ✅ Shipped (`02207ea`) |
| Frontend dependency security | ✅ Shipped (`61f086a`; npm audit: 0 vulnerabilities) |
| Tailwind production compilation | ✅ Shipped (`331b611`) |
| RICK development capability wave | ✅ Playwright 1.62.1, Trivy 0.74.0, Mermaid CLI 11.16.0, Sumy 0.13.0, Debugpy 1.8.21, VS Code JS Debug 1.117.0, Streamlit 1.62.0 |
| CI #1 fix | ✅ Shipped (`0235901`) |
| GitHub repo | ✅ Private (`michaelricksmith/code-sonar`) |
| `.github/workflows/ci.yml` | ✅ 3-job pipeline (backend ruff + mypy + pytest on Python 3.11, frontend tsc + vite on Node 20, smoke self-scan) |

**Current backend baseline:** **414 passed, 1 skipped** (verified 2026-08-31). The focused hotspot suite is 18/18 with 100% hotspot-engine coverage. Frontend lint and the TypeScript/Vite 8 production build pass, and `npm audit` reports 0 vulnerabilities. Playwright is now pinned as a frontend development dependency for browser-level testing.

See [`DEVELOPMENT_STATUS.md`](DEVELOPMENT_STATUS.md) and [`CHANGELOG.md`](CHANGELOG.md) for the full history.

---

## 17. License / status

See [`OWNERSHIP.md`](OWNERSHIP.md) for the canonical ownership and intellectual-property notice.

**License:** Proprietary — all rights reserved. No license to use,
copy, modify, distribute, sublicense, or commercialize Code Sonar is
granted unless Michael Smith expressly provides one in writing.

**Creator, owner, and maintainer:** Michael Smith (`michaelricksmith`).

**Development assistance:** RICK and other software-development tools
operate only under Michael Smith's direction and do not hold ownership
or intellectual-property rights in Code Sonar.

**Contact:** open a GitHub issue on `michaelricksmith/code-sonar`.

**Success condition for v0.1.0-beta.1:** A technically capable person
who did not build Code Sonar can follow this README, start the app,
scan a repository, understand the score, identify priority risks, run
another scan, and understand what changed.

**Status:** READY for private beta.


## Repository onboarding

The first-run experience is built for people who are not engineers:

1. **Sign in** with GitHub or Google (OAuth — no password).
2. **Pick a repo** from your GitHub repositories, or paste a repo URL.
3. **First scan** runs with an animated progress screen, then reveals your
   score with a plain-language explanation of what it means.
4. **Fix the top issue** — every issue has a guided, step-by-step fix flow,
   plus an optional "Fix this for me" approval-gated remediation.

The onboarding layer preserves the deterministic 300–850 score as the
product authority. Ask Sonar and ML remain evidence-grounded advisory
layers. The native `POST /api/scan` `repo_path` contract still works for
local checkouts and self-hosted use.

## Hosted setup (operators)

Sign-in and hosted AI features are configured entirely through environment
variables — no secrets are ever committed to the repo:

| Variable | Purpose |
|---|---|
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth App credentials |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth client credentials |
| `SONAR_PUBLIC_URL` | Public base URL, e.g. `https://sonar.example.com` (used for OAuth redirect URIs) |
| `SONAR_SESSION_SECRET` | Signs session cookies (falls back to a random per-process secret with a warning — set it in production) |
| `ASK_SONAR_PROVIDER` | `ollama` (self-host default), `openai`, or `anthropic` |
| `OPENAI_API_KEY` / `GROQ_API_KEY` / `ANTHROPIC_API_KEY` | Hosted provider keys (server default) |
| `ASK_SONAR_BASE_URL` / `ASK_SONAR_MODEL` | Override hosted endpoint/model (e.g. Groq: `https://api.groq.com/openai/v1`) |
| `CODE_SONAR_REMEDIATION_EXECUTOR` | `deterministic` (default, free), `groq` (AI fixes via Groq API), or `cursor` (Cursor Agent CLI) |
| `CODE_SONAR_GROQ_MODEL` | Model for Groq remediation (default `llama-3.3-70b-versatile`) |
| `CODESONAR_SCAN_ROOT` | Allowed scan root (defaults to `<tmp>/code-sonar-scans`) |

To enable sign-in, register a **GitHub OAuth App** and a **Google OAuth
client**, then set each provider's authorized redirect URI to
`<SONAR_PUBLIC_URL>/api/auth/github/callback` and
`<SONAR_PUBLIC_URL>/api/auth/google/callback` respectively. Users can also
supply their own AI provider key in the app (sent per-request, never
stored).

### Deploy to Render (free tier)

The repo ships a `render.yaml` Blueprint: **Render → New → Blueprint →
select `michaelricksmith/Code-Sonar` → Apply**. It provisions one free Python
web service; the backend also serves the built dashboard SPA from the same
origin (no separate static site, no CORS hacks needed).

After the first deploy Render shows the public URL. Then, in the service's
**Environment** tab:

1. Set `SONAR_PUBLIC_URL` and `CODESONAR_CORS_ORIGINS` to that URL (no
   trailing slash) and redeploy.
2. Register the GitHub OAuth App and Google OAuth client with the redirect
   URIs above, fill in the four OAuth env vars, and redeploy.

Set `SONAR_SESSION_SECRET` (any long random string) on the **first** deploy —
the server fails closed and will not start without it. Until step 2, sign-in
reports "not configured". The free service sleeps after 15 minutes idle
(30–60 s cold start); scan jobs do not survive restarts.

## Current limits (honest)

- Deep analysis is Python-focused; other languages get structural checks.
- Scan jobs run in-process (threaded) — there is no persistent background
  queue yet, so jobs don't survive a restart.
- The complete Cursor-remediation proof still requires the installed-Cursor
  host run noted at the top of this README; CI covers everything up to the
  external Cursor binary boundary.

## Scoring authority and calibration

The versioned blinded reviewer workflow and rubric live in
`backend/benchmarks/scoring/`. Metadata validation never counts as accuracy.

Authoritative scan responses now identify `scoring_version` and report the
completion status of every registered analyzer. If any analyzer fails, Code
Sonar returns an incomplete-scan error and does not issue a score or grade.
Historical records preserve the scoring version; older records load as
`legacy-unversioned`. A label-free benchmark template lives in
`backend/benchmarks/scoring/` for future blinded expert calibration.

Calibration Evidence v1 adds privacy-safe, versioned evidence contracts and a
capture/evaluation workflow. Captured artifacts contain anonymous case IDs and
derived finding facts only—never repository identity, source evidence, or host
paths. The 12-case manifest is a sampling skeleton, not claimed repository data
or fabricated expert labels. Scoring now rejects duplicate finding IDs and
publishes a deterministic contribution explanation for each finding and
category. Weights and grade thresholds remain unchanged.
