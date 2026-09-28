## 2026-09-08 — Installed Cursor host-proof runner\n\nRun `backend/scripts/cursor_remediation_proof.py` only from a clean, current checkout with authenticated `agent`. Supply a new evidence path. Success requires the exact target file change, a passing tests-kind validator, resolved finding, positive score delta, negative debt delta, unchanged active checkout, and complete worktree/branch cleanup. Commit only the sanitized JSON result after review.\n\n## 2026-09-08 — Cursor remediation proof\n\nBranch `remediation/cursor-e2e-proof` adds a concrete real-Git integration test and operator evidence gate for finding → isolated worktree → Cursor executor → tests → rescan → score improvement → cleanup. CI substitutes only the external Cursor binary boundary. Do not claim the complete Cursor proof until the guarded workflow is executed on Michael Smith's authorized Windows host and sanitized evidence is committed under `docs/evidence/`. See `docs/cursor-remediation-proof.md`.\n\n# Code Sonar — End-of-Day Handoff

**Created, built, and owned by Michael Smith (GitHub: `michaelricksmith`). Copyright © 2026 Michael Smith. All rights reserved.**

## 2026-09-28 — Pre-public compliance (merged, deployed)

Branch `feature/prelaunch-compliance` → PR #85 (CI fully green: backend
tests+lint, frontend build+typecheck, self-scan smoke) → squash-merged
as `be2ea75`. Render deploy `dep-dastk2jncjis73esvtg0` live;
production `/health` 200, Alembic `20260927_0005` applied at startup
(runtime fail-closed pin), new frontend bundle (`index-CEY5vQAB.js`)
serving with compliance code.

Branch `feature/prelaunch-compliance` implements the launch compliance
surface on top of #77 billing. Backend: append-only `compliance_records`
table (Alembic `20260927_0005`, revision pin bumped; JSON fallback when
SQL is off), compliance API (`/api/compliance/status|age-gate|
age-gate/block|marketing-consent|gpc|unsubscribe/{token}|
reminders/annual`), checkout gated on `autorenew_consent: true` with a
timestamped consent record, in-app cancel/resume + subscription state,
post-purchase receipt and cancellation-confirmation transactional
emails (`SONAR_EMAIL_TRANSPORT` log/smtp/resend; RFC 8058 one-click
unsubscribe), neutral age gate (13+/18+; under-13 signups deleted, no
attempt record), marketing opt-in unchecked by default, GPC honored,
annual reminders via `scripts/annual_reminders.py --list/--send`.
Frontend: consent checkbox + disclosure on the pricing page, subscription
panel with two-step in-app cancel/resume, age gate on first sign-in,
draft legal pages at `#/legal/terms|privacy|accessibility` (pending
legal review), footer Terms/Privacy/Accessibility links, a11y pass
(skip link, landmarks, focus-visible). 25 new compliance tests; ruff +
strict mypy clean; full backend suite green except the 4 known Ask
Sonar failures on main. Also carries the one-line `answering.py`
`str(finding["file_path"])` mypy fix (PR #84's fix, not in this
branch's base). **Still unverified:** sandbox end-to-end purchase →
webhook → receipt; real email provider not configured (log transport
default); legal pages are drafts awaiting Michael's review.

## 2026-09-26 — Stripe billing is live (test mode)

Billing backend (#77) plus two deploy fixes (#78, #79) are merged and
live on production (deploy `dep-das7h53tqb8s739hojeg`, `/health` 200).
`#/pricing` serves the $0/$7/$14 tiers; checkout → Stripe → webhook →
plan flip is wired in test mode with all four `STRIPE_*` env vars set.

Two real bugs were caught by the failed deploys, not the test suite:
(1) #77's deploy died at startup — `runtime.py` fail-closed on Alembic
revision `20260926_0003` while the DB had migrated to `20260926_0004`
(`#78` bumps the pin; every future migration must bump it too, and
`20260926_0004` is now idempotent/portable across fresh and migrated
DBs). (2) `ApiBoundaryMiddleware` 401'd Stripe's webhook deliveries
(they carry no app session), so no subscription would ever activate —
`/api/billing/webhook` is now exempt alongside the GitHub webhook
(`#79`, with a fail-closed-mode regression test). Lesson: billing tests
run in local-dev mode where the middleware passes everything through;
prod-parity auth behavior needs explicit fail-closed tests.

**Still unverified:** end-to-end test purchase (sign in → pick Hobby/Plus
→ 4242 card → webhook flips plan → portal → cancel/downgrade to free).

> **Current handoff — 2026-09-25 PDT (late)**

Remediation now has three executors: `deterministic` (default, free
structural fixes — currently the only safe live path), `groq` (new
`backend/app/remediation/groq.py`: AI-generated fixes via Groq's
OpenAI-compatible API, no local binary so it runs on Render's free tier;
production env set to `CODE_SONAR_REMEDIATION_EXECUTOR=groq` with
`ASK_SONAR_PROVIDER=openai`,
`ASK_SONAR_BASE_URL=https://api.groq.com/openai/v1`,
`ASK_SONAR_MODEL=openai/gpt-oss-120b`, and `GROQ_API_KEY` now set in
the Render dashboard — deploy `dep-dar0cph42hec73ch645g` live on commit
`961c97f`, `/health` ok), and `cursor` (legacy CLI path;
installed-Cursor host proof still outstanding). Ask Sonar's
OpenAI-compatible provider now also accepts `GROQ_API_KEY`. The
remediation UI now surfaces execution outcomes (state/summary/error)
and offers retry when validation is missing — live on production.
The deterministic splitter from 2026-09-24 is intentionally NOT the live
fix path — its block-splitting is unproven on real files and must be
hardened or gated before production use. **Still unverified:** Groq
end-to-end on the live service (Ask Sonar answer + Approve & fix →
validation/rescan/score movement). Prior deployments 2026-09-25
of 106efe5/4c268d3/4b565f2 hit transient Render `update_failed` /
`build_failed` states; resolved — latest deploy is `live`.

> Previous handoff — 2026-09-23 PDT

Public-beta launch state. What's new since 2026-09-08: GitHub/Google OAuth
(`backend/app/oauth.py`), async scan jobs (`backend/app/scan_jobs.py` —
clones into `<scan-root>/workspaces/<job_id>/` so path-containment
validation accepts it; fixed 2026-09-23 after a live E2E found the old
`~/.code-sonar/workspaces` path failed validation), hosted Ask Sonar
providers with BYOK (`backend/app/ask_sonar/providers/`), full light-theme
frontend rebuild (`frontend/src/`, copy map in `frontend/src/copy/`,
landing + onboarding wizard + guided remediation). License stays
proprietary "All rights reserved". Next: deploy with OAuth credentials
registered (GitHub OAuth App + Google OAuth client; see README "Hosted
setup"), then flip the GitHub repo to public.

> Previous handoff — 2026-09-02 PDT

`scoring/calibration-reviewer-pilot` adds blinded packet generation and a precise
review/adjudication protocol. Never commit reviewer identity mappings, repository
identity, source, or customer data. Evaluation requires two finalized independent
labels and disagreement-preserving adjudication for every case.

The onboarding checkpoint adds `backend/scripts/readiness.py` and authenticated
`GET /api/ops/readiness`. Only stable codes and safe summaries leave the
process; values, paths, tenant IDs, and probe errors are not returned. Default
calibration is intentionally blocking because approved expert labels are not
complete. Use the new runbook and data-flow summary; do not treat the software
gate as deployment evidence or compliance certification.

The UI foundation checkpoint now routes local scans and managed GitHub project
baselines through one active frontend context. Overview, Findings, Risk Map,
History, Ask Sonar, and Remediations no longer operate independently from the
project dashboard. Continue with visual refinement only after preserving this
context boundary and its live API behavior.
- The first visual refinement is complete: the populated Overview uses a
  semantic 300–850 Credit Report Signal Core and live evidence-driven sonar
  field, with a responsive top-three priority queue. The duplicate project
  dashboard previously mounted above the application has been removed.
- Phase 2 began with a responsive application shell, accessible mobile navigation, and a redesigned real-data credit-score command center. The command center preserves the deterministic 300–850 score, grade, category normalization, findings, debt, severity, priority, repository, and scan metadata from the native scan response.

> RICK's first development-capability wave is installed and verified locally. Read `docs/RICK_CAPABILITY_ROADMAP.md`, `README.md`, the top of `DEVELOPMENT_STATUS.md`, and `CHANGELOG.md` as the current source of truth. The 2026-08-22 handoff below is retained only as historical context and must not be used to select new work.

## Current verification

- Stripe billing (test-mode ready, PR unmerged): flat-rate tiers with
  monthly quotas — free ($0: 1 repo, 5 scans/mo, 25 Ask Sonar/mo, 7-day
  history), hobby ($7/mo: 5 repos, 50 scans/mo, 500 Ask Sonar/mo, 90-day
  history), plus ($14/mo: 20 repos, 300 scans/mo, 2,000 Ask Sonar/mo,
  unlimited history, priority scans); fix prompts unlimited on every
  tier. Backend: `PLAN_LIMITS` in `backend/app/billing/plans.py`,
  `usage_counters` table + `users.stripe_customer_id` (Alembic
  `20260926_0004`), `/api/billing` checkout/webhook/portal/status,
  402 `upgrade_required` enforcement on scan creation and Ask Sonar
  (anonymous callers metered on free limits), 503 `billing_disabled`
  when Stripe keys are absent. Frontend: `#/pricing` page, sidebar
  quota display, 402 upgrade nudges, portal link for paid users.
  **62 new billing tests pass**; ruff + strict mypy clean; 4 Ask Sonar
  failures confirmed pre-existing on `origin/main`. Stripe products,
  price IDs, and keys still to be provisioned (test mode first).
- Google OAuth sign-in verified working end-to-end 2026-09-26 (browser
  login by the owner; production `/health` 200). Working configuration:
  Google Cloud project "Code sonar" (free tier, no billing), OAuth client
  `64683181748-h1udg7k0qe10v10k5jue1tg9bgdf5la6.apps.googleusercontent.com`
  (client ID is public-by-design — it appears in auth URLs — so it is
  recorded here; the secret is not), authorized redirect URI
  `https://code-sonar.onrender.com/api/auth/google/callback`, and Render
  env vars `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` set via
  the Render API (`~/workspace/skills/render/bin/render-env.py`).
  Durable lessons from the debug loop that preceded it: (a) keep exactly
  one OAuth client per Google Cloud project — a second client's secret
  paired with the first client's ID produced a bare `invalid_client`
  failure; if a spare client exists in the console, delete it; (b) Render
  dashboard env-var edits can silently not save — prefer the Render API
  and verify the stored value afterwards; (c) Render API env-var PUTs did
  not visibly auto-trigger a redeploy in this session — always check the
  deploy list afterwards and trigger a manual deploy if none appears.
- Database-backed user accounts: `users` table (Alembic `20260926_0003`)
  with per-email cross-provider identity linking, AES-GCM-encrypted GitHub
  tokens, `last_login_at` tracking, suspended-account rejection at login and
  session resolution, and a one-time non-destructive legacy JSON import at
  startup. **19 new tests pass**; existing OAuth/scan-job/session-cookie
  tests unaffected (607 passed / 1 skipped full suite; 4 pre-existing
  Ask Sonar failures unchanged from base).
- Operational privacy checkpoint: tenant-scoped retention policy, authenticated
  and audited encrypted export job contract, recovery-gated soft/hard deletion,
  content-free idempotent receipt, and crypto-erasure integration seam. The MVP
  export executor runs inline behind asynchronous states. Managed KMS/object
  storage/backup/PITR/restore drills remain open gates.
- Operational privacy validation: **459 passed, 2 skipped**, Ruff and strict
  mypy passed, Alembic reached `20260902_0002`, frontend lint/build passed, npm
  audit found 0 vulnerabilities, and the live self-scan exercised 8 analyzers.

- Transactional persistence foundation: SQLAlchemy unit of work, Alembic
  tenant-aware schema, PostgreSQL shared-deployment gate, atomic project scans,
  atomic webhook claims/leases, encrypted checkout paths, guarded data root,
  and explicit ledgered legacy imports. Local SQLite is not presented as SaaS
  readiness. Production KMS, retention/export/deletion, backup/PITR and restore
  drills remain open gates.
- Backend: **453 passed, 2 skipped** locally; PostgreSQL concurrency coverage is
  configured on the CI PostgreSQL 17 service.

- Remediation security checkpoint: server-minted signed/expiring/single-use
  authorization; immutable scan/finding/commit/executor binding; guaranteed
  worktree cleanup; direct remediation primitives closed; host paths removed
  from public scan/history/remediation responses.
- Tenant-isolation checkpoint: bearer credentials resolve to a server-owned
  tenant identity; projects, scan history, Ask Sonar/remediation plans, and
  GitHub installations deny cross-tenant lookup. A caller tenant header cannot
  override the credential binding. Signed webhooks resolve the tenant only from
  the stored installation owner and preserve it through queued scans; unknown
  installations cannot select a project. This is an application-layer checkpoint,
  not the final encrypted production data store.

- Backend: **434 passed, 1 skipped** with 86% measured coverage.
- Hotspot suite: **18 passed** with 100% engine coverage.
- Frontend TypeScript/Vite 8 production build: passed.
- Frontend ESLint 9 validation: passed.
- npm audit: 0 known vulnerabilities.
- Tailwind/PostCSS production compilation: working.
- Recent commits: `02207ea` hotspot determinism, `61f086a` frontend security, `331b611` Tailwind compilation.
- The current security increment adds fail-closed API bearer authentication,
  exact-origin CORS, and default scan-root containment. Local launchers opt into
  loopback-only developer mode; single-tenant deployments set `CODESONAR_API_TOKEN`,
  multi-tenant deployments set `CODESONAR_API_TENANT_TOKENS`, and all deployments set
  `CODESONAR_SCAN_ROOT`, `CODESONAR_CORS_ORIGINS`, and `CODESONAR_HOST`.
- RICK tools verified: Playwright 1.62.1, Trivy 0.74.0, Mermaid CLI 11.16.0, Sumy 0.13.0, Debugpy 1.8.21, VS Code JS Debug 1.117.0, and Streamlit 1.62.0.
- OpenClaw gateway: restarted after role-specific skill assignment and healthy.

## Current continuation instructions

1. Confirm `main` matches `origin/main`.
2. Choose one bounded task based on the real repository, not the archived checkpoint below.
3. Have RICK assign the correct specialist, independently review the diff, and run focused plus release-level verification.
4. Update status and changelog documents before committing.
5. Commit only intended tracked files and push to `origin/main`.
6. Preserve unrelated local RICK/OpenClaw files.

Michael Smith retains all product, release, ownership, and licensing authority. Do not attribute ownership to RICK or any AI/tool, grant a public license, rewrite Git history, or perform destructive cleanup without Michael Smith's explicit approval.

---

## Archived handoff from 2026-08-22

**Historical date:** 2026-08-22 01:15 PDT
**Status:** Work checkpoint — ready to resume tomorrow

---

## Current Project State

Code Sonar is in **specification phase**. Three specifications are complete or in progress:

1. **Market Analysis** — ✅ Complete
2. **Technical Specification v1.0** — ✅ Complete  
3. **Credit Report UI/UX Specification** — 🟡 In Progress (through Section 7)
4. **Technical Debt Scoring Specification** — ⏸️ Not started
5. **MVP Specification** — ⏸️ Not started

---

## Completed Files

| File | Path | Status | Size |
|------|------|--------|------|
| Market Analysis | `strategy/market-analysis.md` | ✅ Complete | ~12 KB |
| Technical Spec v1.0 | `specs/technical-spec-v1.md` | ✅ Complete | ~22 KB |
| Credit Report UI/UX | `specs/credit-report-ui-ux.md` | 🟡 Through Section 7 | ~27 KB |

---

## Incomplete Files

| File | Path | Status | Next Section |
|------|------|--------|--------------|
| Credit Report UI/UX | `specs/credit-report-ui-ux.md` | Section 7 complete | **Section 8** (next work point) |

**Section 7 completion verified:** Debt Trend Visualization is complete with all subsections through 7.8 (Accessibility).

**Do not regenerate Sections 1-7.** They are locked and approved.

---

## Exact Next Task

**Resume Credit Report UI/UX specification at Section 8.**

Expected sections remaining:
- Section 8: Finding Detail Views
- Section 9: Pull Request Integration
- Section 10: Notifications
- Section 11: Settings & Configuration
- Section 12: Mobile Responsiveness
- Section 13: Performance Requirements
- Section 14: Accessibility (WCAG AA)
- Section 15: Future Considerations

*(Section count may adjust as the specification develops)*

---

## Remaining Planned Work

After completing Credit Report UI/UX specification:

1. **Technical Debt Scoring Specification** — Deterministic scoring algorithm, category weights, penalty calculations, score band definitions
2. **Code Sonar MVP Specification** — Feature checklist, launch requirements, deployment plan, success metrics
3. **Cross-check all four specifications** — Consistency pass, alignment verification, gap identification
4. **Create CODE SONAR PRODUCT BASELINE** — Single consolidated document defining Code Sonar v1.0

---

## Known Blockers

None. All work is specification-phase and does not depend on external systems.

---

## Relevant Paths

- **Project root:** `C:\Users\bookm\.openclaw\workspace\code-sonar`
- **Specifications:** `C:\Users\bookm\.openclaw\workspace\code-sonar\specs\`
- **Strategy docs:** `C:\Users\bookm\.openclaw\workspace\code-sonar\strategy\`

---

## Current Architecture Decisions

### Product Positioning
- "Credit report for your codebase" — borrowing FICO metaphor for instant recognition
- 0-100 score with A-F bands (90+, 80-89, 70-79, 60-69, 0-59)
- Focus: stale complex code + vulnerable dependencies + maintenance debt trends

### Deployment Model
- **Primary:** SaaS (multi-tenant GitHub/GitLab App)
- **Secondary:** CLI (local scan before push)
- **Future:** Self-hosted (Enterprise, v2)

### Tech Stack
- **API:** Node.js + TypeScript + Fastify
- **Workers:** Node.js + TypeScript + BullMQ
- **Queue:** Redis + BullMQ
- **Database:** PostgreSQL (Supabase or RDS)
- **Dashboard:** Next.js 14 + React + Tailwind + shadcn/ui
- **CLI:** Node.js + TypeScript + oclif
- **Analysis:** ESLint, radon, gocyclo, npm audit, OSV
- **Infra:** AWS (ECS Fargate) or Vercel + Supabase

### Score Categories (Weighted)
1. **Complexity** (30%) — Cyclomatic/cognitive complexity, LOC, maintainability index
2. **Staleness** (25%) — Days since edit × complexity (complex + stale = expensive debt)
3. **Security** (25%) — Vulnerable dependencies, outdated packages, CVEs
4. **Duplication** (10%) — Copy-paste code blocks, repeated patterns
5. **Testing** (10%) — Coverage gaps, missing tests, flaky tests

---

## Scoring & Product Decisions Locked

- Score range: 0-100 (100 = no debt)
- Band colors: A (green #22C55E), B (light green #84CC16), C (yellow #EAB308), D (orange #F97316), F (red #EF4444)
- Default weights: Complexity 30%, Staleness 25%, Security 25%, Duplication 10%, Testing 10%
- Weights are configurable per-repo but default to above
- Trend display: 7/30/90-day sparklines, velocity, volatility, annotations
- Dashboard layout: Score Card (hero), Recent Activity, Top Issues, Trend Chart
- Responsive breakpoints: ≥1200px (3-col), 768-1199px (2-col), <768px (1-col stack)

---

## Git Status

```
On branch main
Your branch is up to date with 'origin/main'.

Untracked files:
  specs/
  strategy/

nothing added to commit but untracked files present
```

*(Git repository exists but no commits yet)*

---

## Verified RICK Runtime Configuration

### OpenClaw
- **Status:** ✅ Working
- **Version:** Latest (as of 2026-08-22)
- **Workspace:** `C:\Users\bookm\.openclaw\workspace`

### OmniRoute
- **Status:** ✅ Working
- **Endpoint:** `127.0.0.1:20128`
- **Tested:** 2026-08-21

### RICK/main Model
- **Fixed model:** `omniroute/kiro/claude-sonnet-4.5`
- **Status:** ✅ Verified working (2026-08-21)
- **Route:** OmniRoute → Kiro → Claude Sonnet 4.5
- **Do not switch back to GitHub Claude routes**

### Verified Providers (via OmniRoute)
- ✅ `kiro/claude-sonnet-4.5` — Verified working
- ✅ `kiro/qwen3-coder-next` — Verified callable
- ✅ `kiro/deepseek-3.2` — Verified callable
- ❌ `kiro/claude-sonnet-5` — Invalid through current route
- ❌ `github/claude-sonnet-4.6` — Unsupported through current chat route

---

## Known Maintenance Items

### OpenClaw Memory Index Embedding Mismatch
- **Issue:** Memory index embedding model mismatch detected
- **Impact:** Memory search may have degraded relevance
- **Status:** Unresolved, not blocking current work
- **Action:** Do not repair tonight; defer to maintenance window

---

## Instructions for Tomorrow

1. **Resume Credit Report UI/UX specification at Section 8**
2. Read `specs/credit-report-ui-ux.md` to verify Section 7 end point
3. Continue writing remaining sections (8+) without regenerating 1-7
4. After completing Credit Report UI/UX:
   - Build Technical Debt Scoring Specification
   - Build Code Sonar MVP Specification
   - Cross-check all four specifications
   - Create CODE SONAR PRODUCT BASELINE

---

## What NOT To Do

- ❌ Do not delete temporary files
- ❌ Do not reset Git
- ❌ Do not change providers
- ❌ Do not modify models
- ❌ Do not upgrade dependencies
- ❌ Do not perform migrations
- ❌ Do not regenerate completed specification sections (1-7)

---

**READY FOR TOMORROW: YES**

All files saved. No blockers. Clear next task. Runtime verified. Handoff complete.


## 2026-09-02 — UI integration handoff

Branch `feature/original-ui-integration` adds a space-inspired first-run repository gateway to the actual frontend. It does not replace the native dashboard or backend contracts. Local scans continue through `repo_path`; GitHub continues through the secure App/project workflow; ZIP is a disabled coming-soon card. The next safe action is tester validation before opening a pull request.

## 2026-09-02 — Scoring authority checkpoint

The backend now refuses to issue an authoritative score or grade after any
analyzer failure. Successful scan responses expose per-analyzer status and
`scoring_version=1.0`; history persists that version while loading older records
as `legacy-unversioned`. The benchmark scaffold is intentionally empty pending
real frozen outputs and blinded expert labels. Weights and thresholds are
unchanged. Run the focused scoring/API/history tests before integration.

## 2026-09-02 — Calibration Evidence v1 handoff

Branch `scoring/calibration-evidence-v1` establishes the evidence system needed
to measure grade accuracy without changing calibration. It adds anonymized,
hashed data contracts, a safe frozen-scan capture command, a metrics evaluator,
and a 12-slot metadata-only pilot manifest. The scorer now rejects duplicate
finding IDs and emits deterministic finding/category contribution details.
Existing calibration profiles retain their scores, so `SCORING_VERSION` stays
at `1.0`. The next product step is collecting real blinded expert labels; until
then, no score-accuracy claim or retuning is justified.

Final validation: 445 backend tests passed and 1 skipped with 86% coverage;
Ruff, strict mypy, frontend lint/build, and an eight-analyzer self-scan passed.
The self-scan initially revealed duplicate dead-code IDs for same-named methods;
the analyzer now uses stable location-aware SHA-256 IDs and the rerun passed.
