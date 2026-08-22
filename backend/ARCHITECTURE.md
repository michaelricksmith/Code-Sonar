# Code Sonar Architecture — MVP Backend

**Version:** 0.1.0  
**Last Updated:** 2026-08-22  
**Status:** Architecture validated, ready for implementation

---

## Module Responsibilities

### 1. **app/models/** — Data Contracts
**Owner:** Data layer  
**Purpose:** Pydantic models defining shape of findings, scores, and analysis results

- `Finding`: Core normalized issue schema (all analyzers → Finding[])
- `AnalysisResult`: Aggregated scan output (score + findings + metadata)
- `Repository`: Repo metadata model
- **NO database ORM here** — pure Pydantic for serialization

**Key interface:**
```python
class Finding(BaseModel):
    id: str
    rule_id: str
    category: FindingCategory
    severity: FindingSeverity
    file_path: str
    evidence: str
    message: str
    debt_points: int
    analyzer: str
```

---

### 2. **app/analyzers/** — Analysis Engine
**Owner:** Analysis layer  
**Purpose:** Pluggable analyzer framework + 5 concrete analyzers

**Base interface:**
```python
class BaseAnalyzer(ABC):
    @abstractmethod
    async def analyze(self, repo_path: Path) -> list[Finding]:
        """Run analysis, return normalized findings."""
        pass
```

**Concrete analyzers (MVP):**
- `ComplexityAnalyzer`: Radon (Python), eslint (JS/TS)
- `StalenessAnalyzer`: GitPython (file age, churn)
- `SecurityAnalyzer`: pip-audit, npm audit, OSV API
- `DuplicationAnalyzer`: Placeholder (v1.1)
- `TestCoverageAnalyzer`: Placeholder (v1.1)

**Design constraint:** Each analyzer is **stateless**, **independent**, and returns `list[Finding]`.

---

### 3. **app/scoring/** — Scoring Engine
**Owner:** Scoring layer  
**Purpose:** Pure deterministic calculation: Finding[] → Score (0-100)

**Key interface:**
```python
def calculate_score(findings: list[Finding]) -> ScoringResult:
    """
    Input: All findings from all analyzers
    Output: Score (0-100) + category breakdown
    
    Formula:
      Score = 100 
            - (complexity_penalty * 0.30)
            - (staleness_penalty * 0.25)
            - (security_penalty * 0.25)
            - (duplication_penalty * 0.10)
            - (test_penalty * 0.10)
    """
    pass
```

**Design constraint:** NO database access, NO side effects, **pure function**.

---

### 4. **app/api/** — REST API Layer
**Owner:** API layer  
**Purpose:** FastAPI routes, request validation, response formatting

**Endpoints (MVP):**
- `POST /scan` — Trigger scan (repo URL or local path)
- `GET /scan/{scan_id}` — Get scan results
- `GET /health` — Health check

**Design constraint:** Thin layer. Business logic lives in analyzers/scoring, not routes.

---

### 5. **app/storage/** — Persistence Layer (Future)
**Owner:** Storage layer  
**Purpose:** SQLite adapter for scan results (SQLAlchemy)

**NOT IMPLEMENTED YET** — MVP v0.1 returns results in-memory only.

---

## Data Flow — Repository → Score → UI

```
┌─────────────┐
│ Repository  │ (GitHub URL, local path, or tarball)
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│ POST /scan                                          │
│ - Clone/extract repo                                │
│ - Detect language(s)                                │
│ - Route to analyzer(s)                              │
└──────┬──────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│ Analyzer Framework (app/analyzers/)                 │
│                                                     │
│  ┌────────────────┐  ┌────────────────┐            │
│  │ Complexity     │  │ Staleness      │            │
│  │ Analyzer       │  │ Analyzer       │            │
│  └────────┬───────┘  └────────┬───────┘            │
│           │                   │                     │
│           └─────────┬─────────┘                     │
│                     │                               │
│  ┌────────────────┐ │ ┌────────────────┐            │
│  │ Security       │─┤ │ Duplication    │            │
│  │ Analyzer       │ │ │ Analyzer       │            │
│  └────────────────┘ │ └────────────────┘            │
│                     │                               │
│                     ▼                               │
│              [ Finding[] ]                          │
│              Normalized findings from all analyzers │
└──────┬──────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│ Scoring Engine (app/scoring/)                       │
│                                                     │
│  Input:  list[Finding]                             │
│  Output: ScoringResult {                           │
│            score: 0-100                             │
│            breakdown: {                             │
│              complexity: 72,                        │
│              staleness: 85,                         │
│              security: 60,                          │
│              duplication: 90,                       │
│              testing: 50                            │
│            }                                        │
│          }                                          │
└──────┬──────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│ API Response (JSON)                                 │
│ {                                                   │
│   "scan_id": "abc123",                              │
│   "score": 72,                                      │
│   "grade": "C",                                     │
│   "breakdown": {...},                               │
│   "findings": [...],                                │
│   "scanned_at": "2026-08-22T17:00:00Z"             │
│ }                                                   │
└──────┬──────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│ Frontend (React)                                    │
│ - Credit report card UI                             │
│ - Findings table                                    │
│ - Category breakdown                                │
└─────────────────────────────────────────────────────┘
```

---

## Key Interfaces

### Analyzer → Scoring Interface

**Contract:**
```python
# All analyzers must produce Finding[]
findings: list[Finding] = []

for analyzer in [ComplexityAnalyzer(), StalenessAnalyzer(), SecurityAnalyzer()]:
    findings.extend(await analyzer.analyze(repo_path))

# Scoring engine accepts Finding[] only
result: ScoringResult = calculate_score(findings)
```

**Why this matters:**
- Analyzers are **decoupled** from scoring logic
- Easy to add new analyzers (just return Finding[])
- Easy to test scoring in isolation (mock Finding[])

---

### API → Frontend Interface

**Contract:**
```typescript
// Frontend expects this shape from POST /scan
interface ScanResult {
  scan_id: string;
  score: number;           // 0-100
  grade: "A" | "B" | "C" | "D" | "F";
  breakdown: {
    complexity: number;
    staleness: number;
    security: number;
    duplication: number;
    testing: number;
  };
  findings: Finding[];
  scanned_at: string;      // ISO 8601
}
```

**Backend guarantees:**
- Score is always 0-100
- Grade is deterministically derived from score
- Findings array is always present (empty if no issues)
- `scanned_at` is UTC timezone

---

## Module Boundaries — File Ownership

| Path | Owner | Modifies |
|------|-------|----------|
| `app/models/finding.py` | **Data team** | When adding new finding fields |
| `app/analyzers/*.py` | **Analyzer team** | When adding/fixing analyzers |
| `app/scoring/__init__.py` | **Scoring team** | When tuning score formula |
| `app/api/*.py` | **API team** | When adding endpoints |
| `app/main.py` | **Platform team** | When changing app-level config |

**Rule:** Analyzers should NEVER import from `scoring/`. Scoring imports from `models/` only.

---

## Structural Concerns & Risks

### ✅ **Well-Structured:**
1. **Clear separation of concerns** — analyzers don't know about scoring, scoring doesn't know about API
2. **Finding model is solid** — comprehensive fields, extensible metadata
3. **Analyzer framework is extensible** — easy to add new analyzers without touching existing code

### ⚠️ **Potential Issues:**

#### 1. **Missing Orchestration Layer**
**Risk:** Who coordinates "clone repo → run analyzers → score → respond"?

**Current state:** Likely in `POST /scan` route handler  
**Better:** Extract to `app/services/scan_service.py`

```python
class ScanService:
    async def scan_repository(self, repo_url: str) -> ScanResult:
        # 1. Clone repo
        # 2. Detect languages
        # 3. Run applicable analyzers
        # 4. Aggregate findings
        # 5. Calculate score
        # 6. Return result
```

**Action:** Create `app/services/` module for orchestration logic.

---

#### 2. **Analyzer Selection Logic Missing**
**Risk:** How do we decide which analyzers to run?

**Example:**
- Python repo → run `radon`, skip `eslint`
- JavaScript repo → run `eslint`, skip `radon`

**Recommendation:** Add `AnalyzerRegistry` that maps languages → analyzers

```python
class AnalyzerRegistry:
    def get_analyzers_for_language(self, language: str) -> list[BaseAnalyzer]:
        mapping = {
            "python": [ComplexityAnalyzer(), SecurityAnalyzer()],
            "javascript": [ComplexityAnalyzer(), SecurityAnalyzer()],
            # ...
        }
        return mapping.get(language, [])
```

---

#### 3. **Error Handling Not Defined**
**Risk:** What happens if one analyzer crashes?

**Scenarios:**
- `radon` throws exception → fail entire scan? Or skip and continue?
- Repo clone fails → return 500? Or return partial result?

**Recommendation:** Fail-fast for critical errors (clone failure), graceful degradation for analyzer errors.

```python
try:
    findings = await analyzer.analyze(repo_path)
except Exception as e:
    logger.error(f"{analyzer.__class__.__name__} failed: {e}")
    # Continue with other analyzers
```

---

#### 4. **No Async/Await Consistency**
**Risk:** Mixing sync and async code leads to blocking workers.

**Current state:** `BaseAnalyzer.analyze()` is async, but underlying tools (radon, git) are sync.

**Recommendation:** Wrap sync calls in `asyncio.to_thread()`:

```python
async def analyze(self, repo_path: Path) -> list[Finding]:
    # Run blocking radon call in thread pool
    results = await asyncio.to_thread(radon_cc, str(repo_path))
    return self._parse_results(results)
```

---

## Scoring Engine — Implementation Notes

**Formula (from spec):**
```python
Score = 100
      - (complexity_penalty * 0.30)
      - (staleness_penalty * 0.25)
      - (security_penalty * 0.25)
      - (duplication_penalty * 0.10)
      - (testing_penalty * 0.10)
```

**Missing detail:** How are penalties calculated?

**Recommendation:**
```python
def _calculate_complexity_penalty(findings: list[Finding]) -> float:
    """
    Complexity penalty based on:
    - Number of high-complexity findings
    - Severity weighting
    - Debt points
    """
    complexity_findings = [f for f in findings if f.category == "complexity"]
    
    penalty = sum(
        f.debt_points * SEVERITY_WEIGHTS[f.severity]
        for f in complexity_findings
    )
    
    # Normalize to 0-100 scale
    return min(penalty / MAX_PENALTY, 100)
```

**Action:** Document penalty calculation logic in `app/scoring/README.md`.

---

## Testing Strategy

### Unit Tests (per module)
```
tests/
├── test_models.py          # Pydantic validation
├── test_analyzers.py       # Each analyzer in isolation
├── test_scoring.py         # Score calculation with mock findings
└── test_api.py             # FastAPI route tests
```

### Integration Tests
```
tests/integration/
└── test_full_scan.py       # End-to-end: repo URL → score
```

**Key test case:** Mock Finding[] → verify score calculation is deterministic.

---

## Performance Considerations

### Bottlenecks (Expected)
1. **Git clone** — Large repos slow (100MB+ takes 10-30s)
2. **Radon analysis** — O(n) with file count (1000 files ~5-10s)
3. **npm audit** — Network call to registry (2-5s)

### Mitigations
- Use shallow clone (`git clone --depth=1`)
- Run analyzers in parallel (`asyncio.gather()`)
- Cache npm/pip audit results (24h TTL)

---

## Open Questions for Implementation Team

1. **Repo cloning:** Use GitPython or subprocess `git clone`? (subprocess faster)
2. **Temporary directories:** Use `tempfile.TemporaryDirectory()` or persistent cache?
3. **Analyzer timeouts:** Should each analyzer have a max runtime? (Yes, 60s default)
4. **Score caching:** Should we cache scores for same commit SHA? (v1.1 feature)
5. **Partial results:** If 3/5 analyzers succeed, return partial score or fail? (Return partial)

---

## Summary — Ready for Implementation

✅ **Validated:**
- Module boundaries are clear
- Data flow is well-defined
- Finding model is comprehensive
- Analyzer framework is extensible

⚠️ **Action Items Before v0.1:**
1. Create `app/services/scan_service.py` for orchestration
2. Add `AnalyzerRegistry` for language → analyzer mapping
3. Define error handling strategy (fail-fast vs graceful degradation)
4. Document penalty calculation in `app/scoring/README.md`
5. Add async wrapper for blocking analyzer calls

**No structural blockers.** Proceed with implementation.

---

**Next Step:** Implement `ScanService` and first analyzer (ComplexityAnalyzer).
