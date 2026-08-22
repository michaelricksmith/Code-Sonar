# Code Sonar — Technical Specification v1.0

**Last Updated:** 2026-08-21
**Status:** Draft for Michael review
**Target:** MVP launch

---

## 1. System Overview

### 1.1 Product Summary

Code Sonar is a "credit report for your codebase" that runs automatically on every push and surfaces:
- **Stale complex code** (untouched 90+ days, costing maintenance hours)
- **Vulnerable dependencies** (packages with known CVEs)
- **Maintenance debt trends** (score changes over time)

### 1.2 Core Value Proposition

> "Know what AI tools leave behind. Get a simple report every time you push."

### 1.3 Deployment Model

| Component | Model |
|-----------|-------|
| **Primary** | SaaS (multi-tenant) — GitHub/GitLab App |
| **Secondary** | CLI (local scan before push) |
| **Future** | Self-hosted (Enterprise, v2) |

---

## 2. Architecture Overview

### 2.1 High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CODE SONAR PLATFORM                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   GitHub    │    │   GitLab    │    │   Bitbucket │  (v2)          │
│  │     App     │    │     App     │    │     App     │                 │
│  └──────┬──────┘    └──────┬──────┘    └─────────────┘                 │
│         │                  │                                            │
│         └────────┬─────────┘                                            │
│                  │                                                      │
│                  ▼                                                      │
│         ┌────────────────┐                                              │
│         │  Webhook API   │  ← Receives push/PR events                  │
│         │  (Node/TS)     │                                              │
│         └───────┬────────┘                                              │
│                 │                                                        │
│                 ▼                                                        │
│         ┌────────────────┐                                              │
│         │ Job Queue      │  ← Redis-backed queue (BullMQ)              │
│         │ (Redis/BullMQ) │                                              │
│         └───────┬────────┘                                              │
│                 │                                                        │
│                 ▼                                                        │
│    ┌────────────┴────────────┐                                          │
│    │                         │                                          │
│    ▼                         ▼                                          │
│ ┌──────────┐          ┌──────────┐                                      │
│ │ Worker   │          │ Worker   │   ← Horizontal scaling               │
│ │ Pool     │          │ Pool     │                                      │
│ │ (Node/TS)│          │ (Node/TS)│                                      │
│ └────┬─────┘          └────┬─────┘                                      │
│      │                     │                                            │
│      └──────────┬──────────┘                                            │
│                 │                                                        │
│                 ▼                                                        │
│         ┌────────────────┐                                              │
│         │  Analysis      │  ← Git clone + static analysis               │
│         │  Engine        │                                              │
│         └───────┬────────┘                                              │
│                 │                                                        │
│                 ▼                                                        │
│         ┌────────────────┐                                              │
│         │  PostgreSQL    │  ← Results, trends, user data                │
│         │  (Supabase?)   │                                              │
│         └───────┬────────┘                                              │
│                 │                                                        │
│                 ▼                                                        │
│         ┌────────────────┐                                              │
│         │  Dashboard     │  ← Web app (Next.js/React)                   │
│         │  (Next.js)     │                                              │
│         └────────────────┘                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Breakdown

| Component | Tech | Purpose |
|-----------|------|---------|
| **Webhook API** | Node.js + TypeScript + Fastify | Receive GitHub/GitLab webhooks, validate signatures, enqueue jobs |
| **Job Queue** | Redis + BullMQ | Durable queue for analysis jobs, retry logic, dead letter handling |
| **Worker Pool** | Node.js + TypeScript | Pull jobs, clone repo, run analysis, post results |
| **Analysis Engine** | Custom + OSS linters | Complexity analysis, dependency scanning, git history mining |
| **Database** | PostgreSQL (Supabase?) | User accounts, orgs, repos, analysis results, trends |
| **Dashboard** | Next.js + React + Tailwind | Credit report UI, settings, trends, integrations |
| **CLI** | Node.js + TypeScript | Local scan, CI integration, pre-push hook |

---

## 3. Data Models

### 3.1 Core Entities

```typescript
// User
interface User {
  id: string;                    // UUID
  github_id?: string;            // GitHub user ID
  gitlab_id?: string;            // GitLab user ID
  email: string;
  name: string;
  created_at: Date;
  updated_at: Date;
}

// Organization
interface Organization {
  id: string;                    // UUID
  name: string;
  slug: string;                  // URL-friendly name
  plan: 'free' | 'team' | 'pro' | 'enterprise';
  seats_used: number;
  seats_limit: number;
  created_at: Date;
  updated_at: Date;
}

// Repository
interface Repository {
  id: string;                    // UUID
  org_id: string;                // FK to Organization
  external_id: string;           // GitHub repo ID or GitLab project ID
  provider: 'github' | 'gitlab' | 'bitbucket';
  name: string;
  full_name: string;             // owner/repo
  default_branch: string;
  language: string;              // Primary language
  last_analyzed_at: Date;
  is_active: boolean;            // Enabled/disabled by user
  created_at: Date;
  updated_at: Date;
}

// Analysis Run
interface AnalysisRun {
  id: string;                    // UUID
  repo_id: string;               // FK to Repository
  commit_sha: string;
  branch: string;
  trigger: 'push' | 'pr' | 'manual' | 'scheduled';
  status: 'pending' | 'running' | 'completed' | 'failed';
  score: number;                 // 0-100
  started_at: Date;
  completed_at: Date;
  created_at: Date;
}

// Finding (individual issue)
interface Finding {
  id: string;                    // UUID
  run_id: string;                // FK to AnalysisRun
  type: 'complexity' | 'staleness' | 'vulnerability' | 'duplication' | 'ai_code';
  severity: 'info' | 'warning' | 'error' | 'critical';
  file_path: string;
  line_start?: number;
  line_end?: number;
  message: string;
  suggestion?: string;           // Auto-fix or action
  metadata: Record<string, any>; // Type-specific data
  created_at: Date;
}

// Trend Snapshot (daily aggregate)
interface TrendSnapshot {
  id: string;                    // UUID
  repo_id: string;               // FK to Repository
  date: Date;                    // Snapshot date
  score: number;
  findings_count: number;
  complexity_avg: number;
  staleness_pct: number;
  vulnerability_count: number;
  created_at: Date;
}
```

### 3.2 Relationships

```
User ─┬─ belongs_to ─→ Organization (many-to-many via membership)
      │
      └─ owns ─→ API keys, preferences

Organization ─┬─ has_many ─→ Repositories
              │
              └─ has_many ─→ Memberships

Repository ─┬─ has_many ─→ AnalysisRuns
            │
            └─ has_one ─→ LatestScore (cached)

AnalysisRun ─┬─ has_many ─→ Findings
             │
             └─ has_one ─→ TrendSnapshot (if daily snapshot)
```

---

## 4. Webhook Flow

### 4.1 GitHub App Events

| Event | Action | Trigger |
|-------|--------|---------|
| `push` | Analyze pushed commit | Any push to any branch |
| `pull_request` | Analyze PR head commit | `opened`, `synchronize`, `reopened` |
| `installation` | Sync repos | `created`, `added` |
| `installation_repositories` | Sync repos | `added`, `removed` |

### 4.2 Webhook Processing Flow

```
GitHub Webhook
     │
     ▼
┌─────────────────┐
│ Validate HMAC   │  ← Verify X-Hub-Signature-256
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Parse Event     │  ← Extract repo, commit, branch
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Plan/Quota│  ← Does org have capacity?
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Enqueue Job     │  ← BullMQ job with repo context
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Return 202      │  ← Immediate response, async processing
└─────────────────┘
```

### 4.3 Analysis Job Flow

```
Worker picks up job
     │
     ▼
┌─────────────────────┐
│ Clone repo (shallow)│  ← git clone --depth=1 --branch=X
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Detect language(s)  │  ← package.json, requirements.txt, go.mod, etc.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Run analyzers       │
│ • Complexity (ESLint, radon, etc.)                               │
│ • Dependencies (npm audit, pip-audit, OSV)                       │
│ • Git history (git log, churn, ownership)                        │
│ • AI code detection (heuristics, optional LLM)                   │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Calculate score     │  ← Aggregate findings → 0-100 score
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Store results       │  ← PostgreSQL: AnalysisRun, Findings
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Post PR check       │  ← GitHub API: Create check run with summary
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Post PR comment     │  ← GitHub API: Comment with credit report
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│ Update dashboard    │  ← WebSocket or polling for live updates
└─────────────────────┘
```

---

## 5. Analysis Engine

### 5.1 Analyzer Types

| Analyzer | Input | Output | Tools |
|----------|-------|--------|-------|
| **Complexity** | Source files | Cyclomatic complexity, cognitive complexity, LOC | ESLint (complexity plugin), radon (Python), gocyclo |
| **Staleness** | Git history | Days since last edit, churn rate, ownership | git log, git blame |
| **Vulnerabilities** | Lockfiles | CVEs, severity, fixed version | npm audit, pip-audit, OSV API, Snyk (optional) |
| **Duplication** | Source files | Duplicated blocks, % duplication | jscpd, PMD CPD |
| **AI Code Detection** | Source files | Likelihood of AI generation | Heuristics (comment style, naming patterns), optional LLM |

### 5.2 Complexity Analysis Details

**Metrics per file:**
- Lines of code (LOC)
- Cyclomatic complexity (CC)
- Cognitive complexity
- Maintainability index
- Function/class count
- Average function length

**Scoring:**
```
File complexity score = 100 - (
  (CC_normalized * 0.4) +
  (LOC_normalized * 0.2) +
  (cognitive_normalized * 0.3) +
  (duplication_pct * 0.1)
)
```

### 5.3 Staleness Analysis Details

**Metrics per file:**
- Days since last commit
- Number of unique authors (ownership concentration)
- Churn rate (additions + deletions over time)
- Last editor

**Staleness categories:**
| Days Since Edit | Category | Action |
|-----------------|----------|--------|
| 0-30 | Active | None |
| 31-90 | Dormant | Monitor |
| 91-180 | Stale | Review for deletion/refactor |
| 180+ | Dead | Flag for removal |

### 5.4 Vulnerability Analysis Details

**Data sources:**
- GitHub Advisory Database (via npm audit)
- OSV (Open Source Vulnerabilities)
- Snyk DB (optional, requires API key)

**Severity mapping:**
| Severity | Score Penalty |
|----------|---------------|
| Low | -1 |
| Medium | -3 |
| High | -5 |
| Critical | -10 |

---

## 6. Scoring Algorithm (v1)

### 6.1 Overall Score Formula

```
Score = 100
      - (complexity_penalty * 0.3)
      - (staleness_penalty * 0.25)
      - (vulnerability_penalty * 0.25)
      - (duplication_penalty * 0.1)
      - (ai_code_penalty * 0.1)
```

### 6.2 Component Penalties

**Complexity penalty:**
```javascript
complexity_penalty = files
  .filter(f => f.complexity > threshold)
  .reduce((sum, f) => sum + (f.complexity - threshold) * weight, 0)
```

**Staleness penalty:**
```javascript
staleness_penalty = files
  .filter(f => f.days_since_edit > 90)
  .reduce((sum, f) => sum + Math.min(f.days_since_edit / 30, 10), 0)
```

**Vulnerability penalty:**
```javascript
vulnerability_penalty = vulnerabilities
  .reduce((sum, v) => sum + severityWeight[v.severity], 0)
```

### 6.3 Score Bands

| Score | Band | Label |
|-------|------|-------|
| 90-100 | A | Excellent |
| 80-89 | B | Good |
| 70-79 | C | Fair |
| 60-69 | D | Poor |
| 0-59 | F | Critical |

---

## 7. API Contracts

### 7.1 REST API Endpoints

```
# Authentication
POST   /auth/github          # OAuth callback
POST   /auth/gitlab          # OAuth callback
DELETE /auth/logout          # Clear session

# Organizations
GET    /orgs                 # List user's orgs
POST   /orgs                 # Create org
GET    /orgs/:id             # Get org details
PATCH  /orgs/:id             # Update org
DELETE /orgs/:id             # Delete org

# Repositories
GET    /orgs/:org_id/repos   # List org repos
POST   /orgs/:org_id/repos   # Add repo (manual)
DELETE /repos/:id            # Remove repo
POST   /repos/:id/analyze    # Trigger manual analysis

# Analysis
GET    /repos/:repo_id/runs  # List analysis runs
GET    /runs/:id             # Get run details
GET    /runs/:id/findings    # Get findings for run

# Trends
GET    /repos/:repo_id/trends?days=30  # Get trend data

# Settings
GET    /orgs/:org_id/settings            # Get org settings
PATCH  /orgs/:org_id/settings            # Update settings
POST   /orgs/:org_id/integrations/slack  # Add Slack integration
DELETE /orgs/:org_id/integrations/:id    # Remove integration

# Webhooks (GitHub/GitLab)
POST   /webhooks/github      # GitHub webhook receiver
POST   /webhooks/gitlab      # GitLab webhook receiver
```

### 7.2 Key Response Shapes

**Analysis Run:**
```json
{
  "id": "run_abc123",
  "repo_id": "repo_xyz",
  "commit_sha": "a1b2c3d4",
  "branch": "main",
  "trigger": "push",
  "status": "completed",
  "score": 72,
  "score_band": "C",
  "findings_summary": {
    "complexity": 12,
    "staleness": 5,
    "vulnerability": 3,
    "duplication": 2,
    "ai_code": 0
  },
  "started_at": "2026-08-21T15:00:00Z",
  "completed_at": "2026-08-21T15:00:45Z"
}
```

**Finding:**
```json
{
  "id": "finding_def456",
  "type": "staleness",
  "severity": "warning",
  "file_path": "src/legacy/auth.ts",
  "line_start": 1,
  "line_end": 342,
  "message": "File untouched for 127 days with high complexity (CC=28)",
  "suggestion": "Consider refactoring or adding ownership documentation",
  "metadata": {
    "days_since_edit": 127,
    "complexity": 28,
    "loc": 342,
    "estimated_hours_per_month": 12
  }
}
```

---

## 8. GitHub App Permissions

### 8.1 Required Permissions

| Permission | Access Level | Purpose |
|------------|--------------|---------|
| **Contents** | Read-only | Clone repo for analysis |
| **Metadata** | Read-only | Basic repo info |
| **Pull requests** | Read and write | Post PR checks and comments |
| **Checks** | Read and write | Create check runs with analysis results |
| **Webhooks** | Read and write | Receive push/PR events |

### 8.2 Subscribe to Events

- `push`
- `pull_request`
- `installation`
- `installation_repositories`

---

## 9. Security Considerations

### 9.1 Data Handling

| Data Type | Storage | Retention | Notes |
|-----------|---------|-----------|-------|
| Source code | Temp only | Deleted after analysis | Never stored permanently |
| Analysis results | PostgreSQL | Per plan (30 days - 3 years) | Aggregated findings, not raw code |
| User data | PostgreSQL | Until account deletion | Email, name, OAuth tokens |
| Logs | Structured logs | 30 days | No code in logs |

### 9.2 Authentication

- OAuth 2.0 with GitHub/GitLab
- JWT for API sessions
- API keys for CLI and CI integrations

### 9.3 Authorization

- Role-based access control (RBAC)
  - Owner: Full org access
  - Admin: Manage repos, settings
  - Member: View dashboards, trigger manual scans
  - Viewer: Read-only dashboard access

### 9.4 Secrets Management

- GitHub App private key: Stored in secrets manager (AWS Secrets Manager / Vault)
- Database credentials: Secrets manager
- OAuth tokens: Encrypted at rest

---

## 10. Infrastructure

### 10.1 Deployment Target

| Environment | Platform | Notes |
|-------------|----------|-------|
| **Production** | AWS (ECS Fargate) or Vercel + Supabase | Serverless-first for cost efficiency |
| **Staging** | Same as prod, smaller scale | |
| **CI/CD** | GitHub Actions | Build, test, deploy |

### 10.2 Service Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     PRODUCTION                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────┐     ┌─────────────┐                   │
│  │   Route 53  │────▶│  CloudFront │  (CDN, DDoS)      │
│  └─────────────┘     └──────┬──────┘                   │
│                             │                           │
│                             ▼                           │
│                      ┌─────────────┐                    │
│                      │   ALB/NLB   │                    │
│                      └──────┬──────┘                    │
│                             │                           │
│              ┌──────────────┼──────────────┐            │
│              │              │              │            │
│              ▼              ▼              ▼            │
│        ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│        │ API (ECS)│  │Dashboard │  │ Webhooks │        │
│        │ Fargate  │  │ (Next.js)│  │  (ECS)   │        │
│        └────┬─────┘  └────┬─────┘  └────┬─────┘        │
│             │              │              │            │
│             └──────────────┼──────────────┘            │
│                            │                           │
│                            ▼                           │
│                     ┌─────────────┐                    │
│                     │    Redis    │  (ElastiCache)     │
│                     └──────┬──────┘                    │
│                            │                           │
│                            ▼                           │
│                     ┌─────────────┐                    │
│                     │ Workers (ECS)│  (auto-scaling)   │
│                     └──────┬──────┘                    │
│                            │                           │
│                            ▼                           │
│                     ┌─────────────┐                    │
│                     │ PostgreSQL  │  (RDS or Supabase) │
│                     └─────────────┘                    │
│                                                         │
│                     ┌─────────────┐                    │
│                     │    S3       │  (artifact storage)│
│                     └─────────────┘                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 10.3 Scaling Strategy

| Component | Scaling Trigger | Strategy |
|-----------|-----------------|----------|
| API | CPU > 70% or RPS > 1000 | Horizontal (ECS tasks) |
| Workers | Queue depth > 100 | Horizontal (ECS tasks) |
| Dashboard | CPU > 70% | Horizontal (Vercel auto-scales) |
| Database | Connections > 80% | Vertical (upgrade instance) |
| Redis | Memory > 80% | Vertical (upgrade node) |

---

## 11. Tech Stack Summary

| Layer | Technology | Rationale |
|-------|------------|-----------|
| **API** | Node.js + TypeScript + Fastify | Fast, type-safe, good ecosystem for GitHub SDK |
| **Workers** | Node.js + TypeScript + BullMQ | Same stack as API, easy to share code |
| **Queue** | Redis + BullMQ | Durable, well-supported, good observability |
| **Database** | PostgreSQL (Supabase or RDS) | Relational, JSONB for flexible findings, good extensions |
| **Dashboard** | Next.js 14 + React + Tailwind + shadcn/ui | Fast dev, SSR, good DX, modern components |
| **CLI** | Node.js + TypeScript + oclif | Industry standard for Node CLIs |
| **Analysis** | ESLint, radon, gocyclo, npm audit, OSV | Best-in-class OSS tools, no reinventing wheels |
| **CI/CD** | GitHub Actions | Native for GitHub App, good marketplace |
| **Infra** | AWS (ECS Fargate) or Vercel + Supabase | Serverless-first, cost-efficient for startup |
| **Monitoring** | Datadog or Sentry | APM, error tracking, logs in one place |

---

## 12. MVP Scope (v1)

### 12.1 Must Have (v1.0)

- [x] GitHub App installation flow
- [x] Push webhook handling
- [x] PR check run creation
- [x] Complexity analysis (TypeScript/JavaScript only)
- [x] Staleness analysis (git history)
- [x] Vulnerability scanning (npm audit + OSV)
- [x] Score calculation (0-100)
- [x] Dashboard: Repo list, score, findings
- [x] CLI: Local scan

### 12.2 Should Have (v1.1)

- [ ] PR comment with summary
- [ ] Slack integration
- [ ] Trend charts (7/30/90 days)
- [ ] Custom complexity thresholds
- [ ] Python support

### 12.3 Nice to Have (v2)

- [ ] GitLab support
- [ ] Self-hosted deployment
- [ ] AI code detection
- [ ] Duplication analysis
- [ ] Custom rules engine
- [ ] SSO/SAML
- [ ] API access

---

## 13. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| GitHub rate limits | High | Medium | Cache results, batch repos, use conditional requests |
| Large repos timeout | Medium | High | Shallow clone, file filtering, incremental analysis |
| Analyzer false positives | High | Medium | Tunable thresholds, user feedback loop |
| Stripe billing integration bugs | Low | High | Test mode, thorough integration tests |
| Worker queue backlog | Medium | Medium | Auto-scaling, priority queue for PRs |
| Database bloat from findings | Medium | Medium | Retention policies, aggregation, archiving |

---

## 14. Open Questions

1. **Supabase vs RDS?** (Simplicity vs control)
2. **Vercel for dashboard or ECS?** (DX vs unified infra)
3. **Snyk API for vulnerabilities or OSV only?** (Better data vs cost/complexity)
4. **Self-hosted in v1 or defer?** (Enterprise demand vs engineering cost)
5. **AI code detection: heuristics only or LLM-assisted?** (Accuracy vs latency/cost)

---

## 15. Next Steps

1. **Michael review this spec** → approve/reject/request changes
2. **Define scoring algorithm in detail** (separate spec)
3. **Design Credit Report UI** (separate spec)
4. **Define MVP launch checklist**
5. **Begin scaffolding repo**

---

*This spec is a living document. Update as decisions are made.*
