# Code Sonar — Development Status

**Last Updated:** 2026-08-22 13:55 PDT
**Sprint:** Sprint 2 — Source-Code Analyzers
**Overall Progress:** ~35%

---

## Current Sprint Goal

Land two Sprint 2 source-code analyzers on top of the working MVP
vertical slice:

1. `oversized_files` — detect source files above a configurable
   line-count threshold.
2. `oversized_functions` — Python AST-based detection of functions,
   async functions, class methods, and nested defs above a configurable
   line-count threshold.

Alongside: filename-specific lockfile filtering so generated
dependency metadata (package-lock.json, yarn.lock, pnpm-lock.yaml,
poetry.lock, Pipfile.lock, etc.) does not trigger source-code
maintainability debt.

---

## Active Phase

**Phase 3 — Source-Code Analyzer Rollout**

---

## Analyzers Shipped

| Analyzer | Status | Rule | Notes |
|----------|--------|------|-------|
| comment_markers | ✅ Shipped | `comment_markers:{todo|fixme|hack}` | Regex; severity + debt scaling |
| oversized_files | ✅ Shipped | `oversized_files:over-threshold` | Line-count; excludes lockfiles & excluded dirs |
| oversized_functions | ✅ Shipped | `oversized_functions:over-threshold` | Python AST (no regex); qualifies nested + methods |

---

## Completed Checkpoints

- ✅ Phase 1 — Codebase Audit / Specs
- ✅ Phase 2 — MVP Vertical Slice (commit `b9bd8eb`)
  - Security validators wired into traversal + `/api/scan`
  - 300–850 FICO-like scoring engine
  - React dashboard wired to `POST /api/scan`
  - 54 → 66 → 109 tests passing
- ✅ Sprint 2 Checkpoint 1 — `oversized_files` (commit `bbbe607` from Checkpoint 0 + Checkpoint 1 self-scan; current self-scan as of Checkpoint 1 reported 17 findings / 55 debt points — superseded)
- ✅ Sprint 2 Checkpoint 2 — lockfile filter + `oversized_functions`
  (commit `332b4e7`)

---

## Sprint 2 Checkpoint 2 — Verified State

**Commit:** `332b4e7` — `feat(backend): lockfile filtering + oversized_functions analyzer (Python AST)`

**Tests:** 109 passing / 0 failing / 1 skipped · 86% coverage

**Lockfile filtering result:**
Filename-specific gate in `app/security/__init__.py` (`LOCKFILE_NAMES`).
`is_lockfile()` is consulted by `OversizedFilesAnalyzer._is_eligible`
and the Python AST walker. Ordinary `.json` / `.yaml` files (e.g.
`package.json`, `tsconfig.json`, `config.yaml`) remain analyzable.
Verified: `frontend/package-lock.json` no longer produces a finding
(was a CRITICAL 5272-line false positive in Checkpoint 1).

**`oversized_functions` analyzer (Python AST, no regex):**
Detects `ast.FunctionDef`, `ast.AsyncFunctionDef`, methods, and
nested defs. Severity scales (WARNING → ERROR → CRITICAL) on how far
the function exceeds the configured threshold. Malformed Python
sources are silently skipped. Finding IDs are deterministic
(`hash(rel_path, qualified_symbol, length, threshold)`).
Symbols are qualified (`C.method`, `outer.inner`).

Thresholds (defaults):
- Files: 500 lines (warning at ≥500+1; error at ≥1000; critical at ≥1500)
- Functions: 50 lines (warning at >50; error at ≥100; critical at ≥150)

Real `oversized_functions` findings in the repo (5):
| severity | file | symbol | length | factor |
|---|---|---|---|---|
| warning | `backend/app/analyzers/oversized_functions.py` | `_iter_python_functions` | 69 | 1.36× |
| warning | `backend/app/analyzers/oversized_functions.py` | `OversizedFunctionsAnalyzer._build_finding` | 53 | 1.04× |
| error | `backend/app/scoring/engine.py` | `calculate_score` | 81 | 1.61× |
| warning | `backend/tests/conftest.py` | `test_repo_fixture` | 64 | 1.27× |
| warning | `backend/tests/conftest.py` | `sample_findings_fixture` | 62 | 1.23× |

**Self-scan (verified twice, byte-identical):**
- Score: 832 / Grade: A
- Finding count: 21
- Total debt points: 61
- Findings by analyzer: comment_markers=13, oversized_files=3,
  oversized_functions=5
- Determinism: PASS (identical score / count / debt / finding IDs
  across consecutive scans)

---

## Sprint Progress

| Checkpoint | Status | Commit |
|-----------|--------|--------|
| MVP vertical slice (Phase 2) | ✅ | `b9bd8eb` |
| Sprint 2 Checkpoint 1 (`oversized_files`) | ✅ | `bbbe607` (frontend milestone) |
| Sprint 2 Checkpoint 2 (lockfile filter + `oversized_functions`) | ✅ | `332b4e7` |

---

## Architecture Decisions (Locked)

Same as MVP vertical slice; no changes this checkpoint:
- Backend: Python + FastAPI
- Storage: SQLite (planned; not exercised yet)
- Analyzer Framework: Python (AST + regex, deterministic)
- Scoring: Python (deterministic, NO LLM)
- Frontend: React + TypeScript
- Testing: pytest (backend), vitest (frontend)
- API Tests: pytest + httpx / FastAPI TestClient

---

## Test Coverage Requirements

✅ Analyzer determinism
✅ Scoring determinism
✅ API endpoint contracts
✅ Finding normalization schema
✅ Security (path traversal, symlinks, file size limits, lockfile exclusion)

---

## Blockers

**Current:** None

---

## Latest Test Status

**Backend:** 109 passing / 0 failing / 1 skipped / 86% coverage
**Frontend:** TypeScript clean; bundle built
**Integration:** Self-scan determinism verified

---

## Git Status

**Branch:** main
**Last Commit:** `332b4e7` (lockfile filtering + oversized_functions)
**Working Tree:** Clean
**Remote:** Not configured

---

## Next Actions (Awaiting approval)

1. Sprint 2 Checkpoint 3 — third source-code analyzer
   (candidate: function complexity / cyclomatic complexity via AST)
2. Continue Sprint 2 with remaining analyzers from the Phase 2 plan

---

*This file is updated at every major checkpoint throughout the sprint.*
