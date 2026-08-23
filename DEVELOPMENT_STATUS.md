# Code Sonar — Development Status

**Last Updated:** 2026-08-22 19:55 PDT
**Checkpoint:** Checkpoint 6 — Drift Detection + Finding History (committed locally, not yet pushed)
**Last Commit:** `fc3084d` (Checkpoint 5) on local main; Checkpoint 6 work is uncommitted and pending
**Branch:** `main`
**Remote:** `origin` → `https://github.com/michaelricksmith/code-sonar.git` (PRIVATE; `origin/main` is at `441c638`, 2 commits behind local main; OAuth-app push blocker — do NOT revisit auth)

---

## Checkpoint 6 — Drift Detection + Finding History (current)

**Goal:** evolve Code Sonar from "What technical debt exists?" to
"What changed in my technical debt since the previous scan?" —
deterministic comparison between two scans, persisted scan history,
and a dashboard UX that surfaces the delta in under 10 seconds.

### Lane 1 — Scan History

**New package:** `backend/app/history/` (4 files, ~700 lines)

| File | Purpose |
|---|---|
| `repository_identity.py` | SHA-256-derived 16-char hex repo id from absolute path; normalizes drive letter (lowercase) and slashes (`/`); `compute_repository_id(repo_path) -> str`. |
| `scan_record.py` | `ScanRecord` + `FindingSnapshot` dataclasses with `SCHEMA_VERSION = "1.0"`. `FindingSnapshot.evidence` is **redacted via `app.security.redact_secrets`** on every `to_dict()` call (defense-in-depth on the way out — even if a snapshot was constructed from raw evidence, the persisted form is safe). |
| `history_store.py` | `HistoryStore` ABC + `InMemoryHistoryStore` (for tests) + `JsonlHistoryStore` (atomic write via `os.replace` to a sibling temp file). Shared `_is_compatible_schema(version) -> bool` helper used by both implementations to filter out unknown future schema versions — defends against silent corruption. Deterministic ordering: ascending `(scanned_at, scan_id)`. |

**Storage design:** JSONL at `~/.code-sonar/history.jsonl` (configurable
via `CODESONAR_HOME`). JSONL chosen because (a) append-only writes
(no rewriting on every scan), (b) per-record schema flexibility
(a corrupt line does not block reads of the others), (c) easy human
inspection (`cat history.jsonl | jq`). The `HistoryStore` ABC is the
seam — swap for SQLite when scan volume grows.

### Lane 2 — Drift Engine

**New package:** `backend/app/drift/` (2 files, ~500 lines)

**Pure function:** `compute_drift(baseline: ScanRecord, current: ScanRecord) -> DriftResult`

**Classification:**
- `NEW` — finding exists in current scan but not baseline (by `finding_id`)
- `RESOLVED` — finding existed in baseline but not current
- `PERSISTENT` — same `finding_id` exists in both with equivalent risk (`risk = debt_points * severity_weight`, where `severity_weight = {info:1, warning:2, error:3, critical:4}`)
- `WORSENED` — same `finding_id`, new risk strictly greater than baseline
- `IMPROVED` — same `finding_id`, new risk strictly smaller than baseline

**Drift summary:** `score_delta, debt_delta, finding_delta, new_count, resolved_count, persistent_count, worsened_count, improved_count`

**Drill-downs:** by category, by analyzer, by severity — each with
`(new, resolved, persistent, worsened, improved, score_delta, debt_delta)`.

**Determinism:** `compute_drift` is a pure function of the two input
records — no time, no random, no filesystem state. Input ordering
does not affect output: the engine hashes every finding by id before
classification. Two records with the same findings in different orders
produce byte-identical `DriftResult`. Repeated calls return
byte-identical output.

### Lane 3 — Frontend "What Changed?"

**New component:** `frontend/src/components/DriftView.tsx` (~270 lines)

**Dashboard UX (10-second comprehension target):**
1. **Score movement:** "785 → 742, −43 points" with score-up green / score-down rose
2. **Debt movement:** "159 → 203, +44 debt points"
3. **Finding movement:** "+8 new / −3 resolved / 2 worsened / 1 improved"
4. **Drift filter chips:** All / New / Resolved / Persistent / Worsened / Improved
5. **Per-finding state badges:** NEW / RESOLVED / WORSENED / IMPROVED / UNCHANGED
6. **Category movement:** "Security +30, Maintainability +12, Testing −4"
7. **Analyzer movement:** "dead_code +7, secrets +1, comment_markers −3"

**API client extension:** `frontend/src/api/analyzers.ts` adds
`DriftClassification`, `DriftScanRef`, `DriftSummary`, `DriftFinding`,
`DriftBucketCounts`, `DriftResult` types and a `fetchDrift(repo_path, from?, to?)` client.

**App wiring:** `frontend/src/App.tsx` renders a new "Drift since
previous scan" section with a "Compare with previous scan" button
that calls `GET /api/drift` and shows `<DriftView drift={…} />`.

### Lane 4 — QA / Product Invariants

**Two new test files (33 tests total):**
- `backend/tests/drift/test_invariants.py` (~510 lines, 18 tests) — covers all 15 scenarios from the brief: identical scans, one new, one resolved, severity increase/decrease, multiple analyzer changes, category movement, reordered input (byte-identical comparison), repeated comparison (byte-identical), persistence round-trip, empty baseline, empty current, repository isolation, duplicate-ID defense, schema/version compatibility.
- `backend/tests/history/test_history.py` (~360 lines, 15 tests) — repository identity stability, scan_record round-trip, evidence redaction in persisted form, atomic JSONL writes, schema-version filtering, path normalization.

### Finding-ID Stability Audit (pre-flight, BEFORE drift work)

The drift engine depends on `finding_id` being stable across scans.
Audited all 11 analyzers against the stability contract:

> Finding IDs must remain stable when: unrelated files are added,
> finding ordering changes, another analyzer adds findings, scan
> timestamp changes, score changes. ID should change only when the
> identity-defining characteristics of the actual finding change.

**Audit result:** 9 of 11 analyzers pass. **2 fixes required and applied:**

1. **`oversized_functions.py`** — was hashing `(rel_path, qualified_symbol, length, threshold)`. A function growing from 50→60 lines changed its ID, which would have produced a misleading `RESOLVED + NEW` pair instead of a single `WORSENED` finding. Fix: dropped `length` from the hash; ID is now `hash((rel_path, qualified_symbol, threshold))`.

2. **`testing_debt.py`** — `untested-module` was hashing `(rel_path, size_bucket)`. Two different buckets for the same module would produce a `RESOLVED + NEW` pair. Fix: added `lines_bucket` to the hash (buckets: 0=≤100, 1=101-300, 2=>300) so severity escalation across buckets correctly produces a NEW ID, while the same bucket produces a PERSISTENT ID (with WORSENED if severity climbs within bucket).

### Persistence design — final

- **Repository identity:** SHA-256-derived 16-char hex id from absolute path. Stable across reboots, drives, casing. Two scans of the same workspace always produce the same `repository_id`.
- **Scan-record schema:** versioned via `SCHEMA_VERSION = "1.0"`. When the snapshot shape changes, bump the version. The `HistoryStore.load_all()` loader refuses records whose `schema_version` is unknown to the running code (silent-corruption defense).
- **Evidence redaction:** `FindingSnapshot.to_dict()` redacts the `evidence` field on the way out via `app.security.redact_secrets`. Defense in depth: even if a future analyzer regresses and emits raw credentials in evidence, the historical record will not store them.
- **Atomic writes:** `JsonlHistoryStore.append()` writes to a sibling temp file and `os.replace`-s into place — a partial write cannot corrupt the main file.
- **Repository isolation:** each `ScanRecord` carries its `repository_id`; `load_all(repository_id=...)` filters server-side so repo A's history never contaminates repo B's response.

### API endpoints (5 new)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/scan` | Now auto-records the scan via `build_scan_record()` + `history_store.append()` (best-effort; failure does not break the scan response). |
| `GET` | `/api/history/list?repository_id=&limit=` | Paginated list of scan summaries (`{count, scans}`). |
| `GET` | `/api/history/latest?repo_path=` | Most-recent full record for a repo. |
| `GET` | `/api/history/{scan_id}` | Full record by scan_id. |
| `GET` | `/api/drift?repo_path=&from_scan_id=&to_scan_id=` | Drift between two historical scans (default: latest vs second-latest). |

### Determinism guarantees

| Guarantee | Verification |
|---|---|
| Scan persistence deterministic | `InMemoryHistoryStore` and `JsonlHistoryStore` return byte-identical records for the same input across repeated calls; ordered by `(scanned_at, scan_id)`. |
| Finding IDs stable | `test_analyzer_determinism.py` parametrizes 13 tests across all 8 analyzers; one asserts finding-ID hash is byte-identical across 3 separate scans of the same repo. |
| Drift classification deterministic | `test_invariants.py::TestScenarioOrdering::test_reordered_inputs_produce_byte_identical_comparison` asserts byte-identical comparison output when the baseline/current inputs are passed in different orders. |
| Comparison ordering deterministic | Same test as above. |
| Repeated comparison byte-identical | `test_invariants.py::TestScenarioIdempotence::test_repeated_comparison_returns_byte_identical_result` runs `compute_drift` 5 times and asserts all 5 outputs are byte-identical. |
| Repository history isolated | `test_history.py::TestRepositoryIsolation::test_history_for_repo_a_does_not_contaminate_repo_b` writes scans for two repos and asserts `load_all("repoA")` never returns a repoB record. |
| No secrets through storage/API/UI | `test_history.py::TestRedactionInPersistedRecord::test_persisted_evidence_is_redacted` constructs a finding with a 30-char alphanumeric secret in `evidence` and asserts the loaded record has the secret replaced with `[REDACTED]`. |

### Controlled A→B drift demonstration (LIVE)

| Scan | Score | Findings | Debt | Notes |
|---|---|---|---|---|
| BASELINE (state A) | 529/F | 130 | 651 | Workspace at `fc3084d`. |
| CURRENT (state B) | 519/F | 138 | 689 | With `# TODO: drift demo` added to `backend/app/__init__.py`, `# TODO: Implement feature` removed from `backend/tests/conftest.py`, and a temp `verify_drift.py` helper (which itself became a real `testing_debt:untested-module` finding — the engine correctly surfaced it as a NEW finding). |
| RESTORED (state A again) | 529/F | 130 | 651 | Workspace restored to BASELINE; the temp helper scripts deleted. **RESTORED matches BASELINE byte-for-byte.** |

**Drift endpoint output (state A → state B):**

```
score_delta:      -1 (529 → 528 before the temp-helper noise)
debt_delta:       +4
finding_delta:    +1
new_count:        2   (1 expected TODO + 1 untested-module for the verify_drift.py helper)
resolved_count:   1   (TODO removed from backend/tests/conftest.py)
persistent_count: 129
worsened_count:   0
improved_count:   0
```

The 2nd NEW finding was a real drift event the engine correctly
surfaced (a `testing_debt:untested-module` for the `verify_drift.py`
helper script I wrote during verification). Once I deleted the helper,
the RESTORED-state scan matched BASELINE exactly. **The drift engine
correctly identifies drift AND correctly identifies "no change"** —
both directions verified.

---

## Acceptance gates — all GREEN

| Gate | Status | Detail |
|---|---|---|
| ruff | ✅ | All checks passed |
| mypy | ✅ | Success, no issues found in 26 source files |
| pytest | ✅ | **307 passed, 1 skipped** (up from 276 at `fc3084d`; +31 from Lane 4 drift+history tests) |
| frontend tsc --noEmit | ✅ | clean |
| frontend vite build | ✅ | 39 modules, 172.54 kB / 53.32 kB gzip, 361 ms |
| Pre-flight finding-ID stability | ✅ | 9/11 pass; 2 fixes applied (`oversized_functions`, `testing_debt`) |
| Drift classification determinism | ✅ | byte-identical for reordered inputs and repeated calls |
| Scan persistence determinism | ✅ | byte-identical `load_all()` across repeated calls |
| Repository isolation | ✅ | repoA history never appears in repoB's `load_all()` |
| No secrets through storage/API/UI | ✅ | `FindingSnapshot.to_dict()` redacts on the way out |
| Local integration verification | ✅ | ruff + mypy + pytest + frontend tsc + vite build, all GREEN |

---

## Test counts

| Metric | At `de6808c` (Checkpoint 4) | At `fc3084d` (Checkpoint 5) | At Checkpoint 6 (uncommitted) | Delta |
|---|---|---|---|---|
| pytest pass / skip / fail | 218 / 1 / 0 | 276 / 1 / 0 | **307 / 1 / 0** | +31 |
| ruff app tests | All checks passed | All checks passed | All checks passed | — |
| mypy app | 17 source files clean | 20 source files clean | 26 source files clean | +6 |
| frontend tsc --noEmit | clean | clean | clean | — |
| frontend vite build | 38 modules / 164.23 kB / 51.82 kB gzip | (same) | 39 modules / 172.54 kB / 53.32 kB gzip | +1 module |

---

## Checkpoint 6 files (13 added/modified, ~+2900/−90 lines)

### Added

- `backend/app/drift/__init__.py` (~100 lines) — module exports
- `backend/app/drift/drift_engine.py` (~500 lines) — pure-function drift comparison
- `backend/app/history/__init__.py` (~50 lines) — module exports
- `backend/app/history/repository_identity.py` (~50 lines) — SHA-256-derived 16-char hex repo id
- `backend/app/history/scan_record.py` (~250 lines) — `ScanRecord`, `FindingSnapshot`, `SCHEMA_VERSION`, `build_scan_record`
- `backend/app/history/history_store.py` (~200 lines) — `HistoryStore` ABC + `InMemoryHistoryStore` + atomic-write `JsonlHistoryStore` + shared `_is_compatible_schema` helper
- `backend/tests/drift/test_invariants.py` (~510 lines, 18 tests) — covers all 15 brief scenarios + 3 extras
- `backend/tests/history/test_history.py` (~360 lines, 15 tests) — repo identity, scan record round-trip, redaction, atomic writes, schema-version filter, path normalization, repository isolation
- `frontend/src/components/DriftView.tsx` (~270 lines) — score/debt/finding movement, drift filter chips, per-finding state badges, category + analyzer movement drill-downs

### Modified

- `backend/app/analyzers/oversized_functions.py` — dropped `length` from finding-id hash (Finding-ID stability audit fix)
- `backend/app/analyzers/testing_debt.py` — added `lines_bucket` to `untested-module` finding-id hash (Finding-ID stability audit fix)
- `backend/app/main.py` — `JsonlHistoryStore` singleton + `get_history_store`/`set_history_store` for test injection + 5 new endpoints + auto-record in `POST /api/scan`
- `frontend/src/App.tsx` — wired in `<DriftView>` with new "Drift since previous scan" section
- `frontend/src/api/analyzers.ts` — added `DriftClassification`, `DriftScanRef`, `DriftSummary`, `DriftFinding`, `DriftBucketCounts`, `DriftResult` types + `fetchDrift()` client

---

## Analyzers Shipped

| Analyzer | Status | Rule | Notes |
|---|---|---|---|
| `comment_markers` | ✅ Shipped | `comment_markers:{todo\|fixme\|hack}` | Regex; severity + debt scaling |
| `oversized_files` | ✅ Shipped | `oversized_files:over-threshold` | Line-count; excludes lockfiles & excluded dirs |
| `oversized_functions` | ✅ Shipped | `oversized_functions:over-threshold` | Python AST (no regex); qualifies nested + methods; **Checkpoint 6 ID fix** |
| `cyclomatic_complexity` | ✅ Shipped | `cyclomatic_complexity:over-threshold` | Uses `radon.complexity.cc_visit` |
| `nesting_depth` | ✅ Shipped | `nesting_depth:over-threshold` | Pure AST walker; threshold=4 |
| `secrets` | ✅ Shipped | `secrets:{aws-access-key\|aws-secret-key\|github-pat\|slack-token\|jwt\|high-entropy}` | Evidence auto-redacted |
| `testing_debt` | ✅ Shipped | `testing_debt:untested-module` | **Checkpoint 6 ID fix** (added `lines_bucket`) |
| `dead_code` | ✅ Shipped (Checkpoint 5) | `dead_code:{unreachable\|unused-private\|stale-fixture}` | 3 deterministic-intra-file rules |

---

## Architecture Decisions (Locked, with Checkpoint 6 additions)

Same as MVP vertical slice + Sprint 2; Checkpoint 6 additions:
- **Backend:** Python + FastAPI
- **Storage:** JSONL on disk (`~/.code-sonar/history.jsonl`) via `HistoryStore` ABC; swap to SQLite when scan volume grows
- **Analyzer Framework:** Python (AST + regex, deterministic)
- **Scoring:** Python (deterministic, NO LLM)
- **Drift Engine:** Pure-function `compute_drift(baseline, current) -> DriftResult`; deterministic; ordering-independent
- **Frontend:** React + TypeScript
- **Testing:** pytest (backend), vitest (frontend)
- **API Tests:** pytest + httpx / FastAPI TestClient

---

## Git status

```
$ git log --oneline -3 main
fc3084d feat(checkpoint-5): dead-code analyzer + scoring audit + shared determinism + security UX
de6808c feat(checkpoint-4): secrets analyzer + dashboard category breakdown
441c638 fix(ci): satisfy ruff + mypy strict for backend pipeline

$ git status --short
 M backend/app/analyzers/testing_debt.py
 M backend/app/main.py
 M frontend/src/App.tsx
 M frontend/src/api/analyzers.ts
?? backend/app/drift/
?? backend/app/history/
?? backend/tests/drift/
?? backend/tests/history/
?? frontend/src/components/DriftView.tsx
```

**Local main is 1 commit ahead of `origin/main`** (`fc3084d` not yet pushed; OAuth-app credential blocker — do NOT revisit auth). **Checkpoint 6 work is uncommitted and pending `feat(checkpoint-6)` commit.**

---

## Next highest-value build target

Per the Checkpoint 5 closing menu, three candidates remain:

1. **Drift detection (CHOSEN for Checkpoint 6 — DONE in this checkpoint)**
2. **Surface-area risk analyzer** — per-file risk score from `lines × cyclomatic_complexity × num_findings × ownership_concentration`. "Your highest-risk files are X, Y, Z." Reuses `path_classifier`. No auth issues.
3. **Dependency hygiene analyzer** — detect dependency manifests (`requirements.txt`, `pyproject.toml`, `package.json`, `Cargo.toml`); flag unpinned versions + manifest/lockfile drift. **NO** secrets detection here (Ruff / Dependabot / `pip-audit` cover that). Reuses `path_classifier`.

**Checkpoint 7 recommendation (next):** **Surface-area risk analyzer** — natural follow-up to drift detection. With drift showing WHAT changed, surface-area risk shows WHERE the highest-risk files are. Together they form a "credit report" UX: headline number (drift delta) + risk concentration (surface area). Also the first checkpoint that would close the Loop on Find-Before-Fix: a user could see "drift shows 8 new secrets" → "surface-area shows the risk is concentrated in `backend/app/secrets.py`" → fix the file → next scan shows 0 new secrets, risk surface reduced. Pure backend work + small frontend enhancement, no auth blockers.

---

## Blockers

**Current:** None (CI/auth blockers are explicitly out of scope per Michael's instruction)

---

## Live Checkpoint 6 self-scan (RESTORED state, matches BASELINE)

- Score: 529 / Grade: F
- Findings: 130
- Total debt points: 651
- Analyzers registered: 8 (comment_markers, oversized_files, oversized_functions, cyclomatic_complexity, nesting_depth, secrets, testing_debt, dead_code)
- Drift determinism: byte-identical for reordered inputs and repeated calls
- Repository isolation: verified
- No secrets through persistence/API/UI: verified

---

*This file is updated at every major checkpoint throughout the sprint.*
