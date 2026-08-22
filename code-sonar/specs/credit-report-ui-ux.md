# Code Sonar — Credit Report UI/UX Spec

**Last Updated:** 2026-08-21
**Status:** Draft for Michael review

---

## 1. Design Philosophy

**"The credit report for your codebase"** — borrowing the familiarity of FICO/credit scores:

- Single number anyone can understand (0-100)
- Color-coded bands (green → red)
- Trend over time (getting better or worse?)
- Specific actionable items (not just "your score is bad")
- Zero learning curve — a PM, CTO, or junior dev all read it the same way

### Visual Identity

- **Dark mode default** (devs prefer it)
- **Accent color:** Teal/cyan for score, red for critical, amber for warnings
- **Typography:** Monospace for code references, sans-serif for everything else
- **Density:** Information-rich but not cluttered — card-based layout

---

## 2. Score Visualization

### 2.1 The Score Card (Hero Component)

The single most important element. Appears on dashboard, PR check, CLI output, notifications.

```
┌──────────────────────────────────────────────────┐
│                                                  │
│              CODE SONAR SCORE                    │
│                                                  │
│                   ┌───────┐                      │
│                   │       │                      │
│                   │   72  │                      │
│                   │  /100  │                      │
│                   └───────┘                      │
│                                                  │
│           ▲ +3 from last week                    │
│                                                  │
│    ░░░░░░░░░░████████████████░░░░░░░░░░░░        │
│    ▁▃▅▇▇▇▅▃▂▁▁▂▃▅▇▇▅▃▂▁▁▂▃▅▇▇▅▃               │
│    30 days ago              today                │
│                                                  │
│    ┌─────────────────────────────────────────┐   │
│    │  A (90+)  B (80)  C (70)  D (60)  F    │   │
│    │   ░░░      ░░░     ██      ░░░     ░░░  │   │
│    │                   ▲                     │   │
│    └─────────────────────────────────────────┘   │
│                                                  │
└──────────────────────────────────────────────────┘
```

### 2.2 Score Band Colors

| Band | Score | Color | Hex |
|------|-------|-------|-----|
| A | 90-100 | Green | #22C55E |
| B | 80-89 | Light Green | #84CC16 |
| C | 70-79 | Yellow | #EAB308 |
| D | 60-69 | Orange | #F97316 |
| F | 0-59 | Red | #EF4444 |

### 2.3 Score Breakdown (Expandable)

```
┌──────────────────────────────────────────────────┐
│                                                  │
│  Score Breakdown                                 │
│                                                  │
│  Complexity    ████████████░░░░  68/100  (-12)   │
│  Staleness     ██████████░░░░░░  58/100  (-18)   │
│  Security      █████████████░░░  85/100  (-5)    │
│  Duplication   ██████████████░░  91/100  (-3)    │
│  AI Code       ████████████████ 100/100  (0)     │
│                                                  │
│  Weighted Total: 72/100                          │
│                                                  │
└──────────────────────────────────────────────────┘
```

Each bar is clickable → drills into that category's findings.

---

## 3. Dashboard Layout

### 3.1 Main Dashboard (Repo View)

```
┌─────────────────────────────────────────────────────────────────────┐
│  ☰  Code Sonar                              [search]   [avatar]    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─ Organization ──────────────────────────────────────────────┐   │
│  │  Acme Corp                              [Free] [Settings]   │   │
│  │  3 repos analyzed · 1,247 findings · Last scan: 2h ago     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─ Score Card ───────────┐  ┌─ Recent Activity ───────────────┐  │
│  │                         │  │                                 │  │
│  │    ┌───────────┐        │  │  ● main: 72 (+3)   2h ago      │  │
│  │    │           │        │  │  ● feat/auth: 68 (-5)  1d ago   │  │
│  │    │    72     │        │  │  ● fix/typo: 74 (+1)  3d ago   │  │
│  │    │   /100    │        │  │                                 │  │
│  │    └───────────┘        │  │  [View all runs →]              │  │
│  │  ▲ +3 this week         │  │                                 │  │
│  │                         │  └─────────────────────────────────┘  │
│  └─────────────────────────┘                                       │
│                                                                     │
│  ┌─ Top Issues ──────────────────────────────────────────────────┐  │
│  │                                                               │  │
│  │  🔴 CRITICAL (2)                                              │  │
│  │  ├─ lodash@4.17.20 — CVE-2024-XXXXX (CVSS 7.5)             │  │
│  │  │  Update to 4.17.21 → npm audit fix                        │  │
│  │  └─ axios@1.6.0 — CVE-2024-YYYYY (CVSS 8.1)                │  │
│  │     Update to 1.6.5 → npm audit fix                          │  │
│  │                                                               │  │
│  │  🟡 WARNINGS (5)                                              │  │
│  │  ├─ src/legacy/auth.ts — Complex (CC=28) × Stale (127 days)  │  │
│  │  │  Estimated: 12 hrs/mo maintenance                          │  │
│  │  ├─ src/legacy/payments.ts — Complex (CC=22) × Stale (98d)   │  │
│  │  │  Estimated: 8 hrs/mo maintenance                           │  │
│  │  ├─ src/old/utils.ts — Dead code indicators                   │  │
│  │  │  3 functions with zero imports                              │  │
│  │  ├─ src/api/routes.ts — 42% duplication detected              │  │
│  │  └─ 2 more warnings...  [Show all →]                         │  │
│  │                                                               │  │
│  │  ℹ️ INFO (8)  [Show all →]                                    │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ Trend ──────────────────────────────────────────────────────┐  │
│  │                                                              │  │
│  │  Score: 72  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │  │
│  │  75 ┤                    ╭─╮                                 │  │
│  │  70 ┤               ╭───╯ ╰───╮                             │  │
│  │  65 ┤          ╭────╯         ╰────╮                        │  │
│  │  60 ┤   ╭──────╯                   ╰─────╮                  │  │
│  │  55 ┤  ╯                               ╰╮                   │  │
│  │      └─────────────────────────────────────                  │  │
│  │      30d  25d  20d  15d  10d  5d  Today                       │  │
│  │                                                              │  │
│  │  Category trends:  [Complexity ▼] [Security ▼] [All ▼]      │  │
│  │                                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ Quick Actions ─────────────────────────────────────────────┐  │
│  │  [Rescan Now]  [Configure Rules]  [Invite Team]  [Upgrade]  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.1.1 Dashboard Component Behaviors

| Component | Behavior |
|-----------|----------|
| **Score Card** | Fixed top-left on desktop; collapses to top banner on mobile (< 768px). Click expands to show Score Breakdown (Section 2.3). |
| **Recent Activity** | Lists last 5 analysis runs with branch, score, delta, timestamp. Click any row → Scan Detail view. |
| **Top Issues** | Grouped by severity (Critical → Warning → Info). Each finding shows file, primary signal, estimated effort. Click → Finding Detail (Section 8). "[Show all →]" navigates to full Findings List with filters. |
| **Trend Chart** | 30-day sparkline by default. Hover shows exact score/date. Category dropdown filters to single-signal trend. Responsive: stacks below Top Issues on mobile. |
| **Quick Actions** | Primary: Rescan Now (triggers manual analysis). Secondary: Configure Rules, Invite Team, Upgrade (plan gating). |

#### 3.1.2 Responsive Breakpoints

| Breakpoint | Layout Change |
|------------|---------------|
| **≥ 1200px** | 3-column: Score Card + Recent Activity (left), Top Issues (center), Trend (right) |
| **768–1199px** | 2-column: Score Card + Top Issues (left), Recent Activity + Trend (right) |
| **< 768px** | Single column stack: Score Card → Recent Activity → Top Issues → Trend → Quick Actions |

#### 3.1.3 Empty/Loading/Error States (Dashboard)

| State | Display |
|-------|---------|
| **Initial load** | Skeleton loaders for each card (shimmer animation). Score Card shows "—" until first run completes. |
| **No analyses yet** | Empty state illustration + "No scans yet. Push code or click Rescan Now." |
| **Webhook disconnected** | Banner: "GitHub webhook not receiving events. [Reconnect]" |
| **Analysis failed** | Toast notification + run marked "Failed" in Recent Activity with error detail on click. |

---

## 4. Repository Overview

### 4.1 Repository List View (Org Level)

Landing page after login. Shows all repositories in the organization.

```
┌─────────────────────────────────────────────────────────────────────┐
│  ☰  Code Sonar                              [search]   [avatar]    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─ Filters ────────────────────────────────────────────────────┐  │
│  │  [All ▼]  [Score: All ▼]  [Language: All ▼]  [Search repos]  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ Repository Table ────────────────────────────────────────────┐  │
│  │                                                                   │  │
│  │  Repository              │ Score │ Trend   │ Last Scan  │ Action │  │
│  ├──────────────────────────┼───────┼─────────┼────────────┼────────┤  │
│  │ acme/api-gateway         │  82   │ ▲ +5    │ 1h ago     │ [View] │  │
│  │ acme/payment-service     │  68   │ ▼ -3    │ 4h ago     │ [View] │  │
│  │ acme/frontend-web        │  74   │ ─ 0     │ 2h ago     │ [View] │  │
│  │ acme/legacy-admin        │  45   │ ▼ -12   │ 3d ago     │ [View] │  │
│  │ acme/ml-pipeline         │  91   │ ▲ +2    │ 30m ago    │ [View] │  │
│  │                                                                   │  │
│  │  Showing 5 of 12 repos    [Load more]                          │  │
│  │                                                                   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Table Columns:**
- **Repository**: Name with provider icon (GitHub/GitLab). Click → Repo Dashboard (Section 3.1).
- **Score**: Large number with band color background. Tooltip shows breakdown on hover.
- **Trend**: Sparkline (7-day) + delta from 7 days ago. Green/red delta indicator.
- **Last Scan**: Relative time. Red if > 24h (stale scan).
- **Action**: Primary [View] button. Overflow menu: [Rescan], [Settings], [Disable].

**Filters:**
- **All / Active / Archived / Disabled** — repo status
- **Score**: All / Excellent (A) / Good (B) / Fair (C) / Poor (D) / Critical (F)
- **Language**: Multi-select from detected languages
- **Search**: Fuzzy match on repo name, owner

### 4.2 Repository Settings View

Accessed from Repo Dashboard → [Settings] or Repository Table overflow → [Settings].

```
┌─────────────────────────────────────────────────────────────────────┐
│  ← Back to acme/payment-service                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─ General ────────────────────────────────────────────────────┐  │
│  │  Repository: acme/payment-service                             │  │
│  │  Provider: GitHub                                              │  │
│  │  Default Branch: main                                         │  │
│  │  Primary Language: TypeScript                                 │  │
│  │  Status: ● Active  [Disable]                                  │  │
│  │  Webhook: ✓ Connected  [Reconnect]                            │  │
│  │  Last Scan: 2026-08-21 14:23 UTC  [Rescan Now]               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ Scan Configuration ──────────────────────────────────────────┐  │
│  │  [x] Scan on push                                              │  │
│  │  [x] Scan on pull request                                      │  │
│  │  [ ] Scan on schedule (cron)  [0 2 * * *]                    │  │
│  │  [x] Include test files in complexity                          │  │
│  │  [ ] Include generated files                                   │  │
│  │                                                                   │  │
│  │  Excluded paths:                                                │  │
│  │  dist/  |  build/  |  node_modules/  |  .generated/  [+ Add]   │  │
│  │                                                                   │  │
│  │  Complexity threshold (CC): 15  [slider 5–50]                │  │
│  │  Staleness threshold (days): 90  [slider 30–365]             │  │
│  │  Duplication threshold (%): 10  [slider 1–50]                │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ Notifications ───────────────────────────────────────────────┐  │
│  │  [x] PR check status                                          │  │
│  │  [x] PR comment summary                                       │  │
│  │  [ ] Slack: #engineering-alerts  [Configure]                 │  │
│  │  [ ] Email on score drop > 10 points                          │  │
│  │  [ ] Weekly digest (Mondays 9am)                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─ Danger Zone ─────────────────────────────────────────────────┐  │
│  │  [Disable Repository]  [Delete All Data]                      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 5. Technical Debt Credit Score Display

### 5.1 Design Requirements

The Credit Score Display is the **primary brand touchpoint**. It must:
- Be instantly recognizable as a "credit score" metaphor
- Communicate score, band, and trajectory at a glance
- Work at multiple sizes: hero (dashboard), medium (PR check), compact (CLI, notifications)
- Be accessible (WCAG AA contrast, screen reader friendly)

### 5.2 Size Variants

#### 5.2.1 Hero (Dashboard, Landing)

```
┌──────────────────────────────────────────────────┐
│                                                  │
│              CODE SONAR SCORE                    │
│                                                  │
│                   ┌───────┐                      │
│                   │       │                      │
│                   │   72  │                      │
│                   │  /100  │                      │
│                   └───────┘                      │
│                                                  │
│           ▲ +3 from last week                    │
│                                                  │
│    ░░░░░░░░░░████████████████░░░░░░░░░░░░        │
│    ▁▃▅▇▇▇▅▃▂▁▁▂▃▅▇▇▅▃▂▁▁▂▃▅▇▇▅▃               │
│    30 days ago              today                │
│                                                  │
│    ┌─────────────────────────────────────────┐   │
│    │  A (90+)  B (80)  C (70)  D (60)  F    │   │
│    │   ░░░      ░░░     ██      ░░░     ░░░  │   │
│    │                   ▲                     │   │
│    └─────────────────────────────────────────┘   │
│                                                  │
└──────────────────────────────────────────────────┘
```
- **Size:** 320×280px minimum
- **Animation:** Score counts up on load (600ms ease-out). Trend line draws left-to-right (800ms).
- **Interactions:** Click → expands Score Breakdown panel. Hover band labels → tooltip with band description.

#### 5.2.2 Medium (PR Check, Repo Table Row Expanded)

```
┌────────────────────────────────────┐
│  CODE SONAR  │  72  │  ▁▃▅▇▇▅▃▂▁  │
│  Fair (C)    │  ▲+3  │  30-day    │
└────────────────────────────────────┘
```
- **Size:** ~400×60px (horizontal)
- **Usage:** GitHub PR check annotation, expanded repo table row, scan history list
- **Elements:** Badge label, score, band, mini-sparkline, delta

#### 5.2.3 Compact (CLI, Notification, Mobile Banner)

```
CODE SONAR: 72/100 (C) ▲+3
```
- **Size:** Single line
- **Usage:** CLI output, Slack/Teams message, email subject, mobile notification
- **Color:** ANSI color in CLI (green/yellow/orange/red per band)

#### 5.2.4 Badge (Static, Embeddable)

```
┌─────────────────┐
│ Code Sonar: 72  │  ← Shields.io style
└─────────────────┘
```
- **Usage:** README badges, GitHub repo description, documentation
- **Generated:** Dynamic image endpoint `/badge/<repo_id>.svg`

### 5.3 Score Display States

| State | Hero | Medium | Compact |
|-------|------|--------|---------|
| **Loading** | Skeleton pulse | "—" with spinner | "CODE SONAR: —" |
| **No data** | "No scans yet" + CTA | "Not scanned" | "CODE SONAR: —" |
| **Error** | "Unable to load score" + retry | "Error" | "CODE SONAR: ERR" |
| **Stale (>24h)** | Warning icon on timestamp | Clock icon + "stale" | "(stale)" suffix |

### 5.4 Accessibility

- **ARIA:** `role="img" aria-label="Code Sonar score: 72 out of 100, Fair, up 3 points from last week"`
- **Color:** Never rely on color alone — always include band letter (A–F) and numeric score
- **Focus:** All interactive variants (Hero click, badge link) have visible focus ring
- **Reduced motion:** `prefers-reduced-motion` disables count-up and line-draw animations

---

## 6. Score Categories

### 6.1 Category Definitions

Each category contributes to the weighted total score. Categories are **deterministic signals** — not AI judgments.

| Category | Key | Weight | What It Measures |
|----------|-----|--------|------------------|
| **Complexity** | `complexity` | 30% | Cyclomatic/cognitive complexity, LOC, maintainability index |
| **Staleness** | `staleness` | 25% | Days since edit × complexity (complex + stale = expensive debt) |
| **Security** | `security` | 25% | Vulnerable dependencies, outdated packages, CVEs |
| **Duplication** | `duplication` | 10% | Copy-paste code blocks, repeated patterns |
| **Testing** | `testing` | 10% | Coverage gaps, missing tests, flaky tests |

> **Note:** Weights are configurable per-repo in Settings (Section 4.2) but default to above. Changes to weights recalculate historical scores retroactively with a version marker.

### 6.2 Category Score Calculation (Summary)

Each category produces a **0–100 sub-score** where 100 = no debt in that category.

| Category | 100 = | 0 = |
|----------|-------|-----|
| Complexity | All files CC ≤ threshold, MI ≥ 80 | Most files exceed thresholds severely |
| Staleness | No file > 30 days stale | Most code > 180 days stale + complex |
| Security | Zero vulnerabilities, all deps current | Critical CVEs in production deps |
| Duplication | < 3% duplicated lines | > 30% duplicated lines |
| Testing | Coverage ≥ 80%, no gaps | Coverage < 20%, critical paths untested |

### 6.3 Category Display

#### 6.3.1 Score Breakdown Panel (Expanded from Hero)

```
┌──────────────────────────────────────────────────┐
│  Score Breakdown                    [× Close]    │
│                                                  │
│  Complexity      ████████████░░░░  68/100  (-12)  │
│  Staleness       ██████████░░░░░░  58/100  (-18)  │
│  Security        █████████████░░░  85/100  (-5)   │
│  Duplication     ██████████████░░  91/100  (-3)   │
│  Testing         ███████████████░░  95/100  (-1)  │
│                                                  │
│  Weighted Total: 72/100  (Fair / C)              │
│                                                  │
│  [View Complexity Details →]                     │
│  [View Staleness Details →]                      │
│  [View Security Details →]                       │
│  [View Duplication Details →]                    │
│  [View Testing Details →]                        │
│                                                  │
└──────────────────────────────────────────────────┘
```

- **Bar:** Visual 0–100, color matches band (Section 2.2)
- **Delta:** Points lost vs. perfect 100 in parentheses
- **Links:** Navigate to category-specific findings list (Section 6.4)

#### 6.3.2 Category Card (Findings List Header)

When user clicks "[View Complexity Details →]", they see:

```
┌─────────────────────────────────────────────────────────────────────┐
│  ← Back to Dashboard          Complexity                    [⚙]    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─ Category Score ────────────────────────────────────────────┐   │
│  │                                                              │   │
│  │       ┌─────────┐                                           │   │
│  │       │         │                                           │   │
│  │       │   68    │                                           │   │
│  │       │  /100   │                                           │   │
│  │       └─────────┘                                           │   │
│  │              Fair (C)   ▼ -12 from perfect                  │   │
│  │                                                              │   │
│  │  Weight: 30% of total score                                 │   │
│  │                                                              │   │
│  │  ████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░    │   │
│  │  30-day trend: ▁▃▅▇▅▃▂▁▁▂▃▅▇▇▅▃▂▁                           │   │
│  │                                                              │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─ What This Means ──────────────────────────────────────────┐   │
│  │  12 files exceed complexity threshold (CC > 15).           │   │
│  │  Highest: src/legacy/auth.ts (CC=28, MI=32)                │   │
│  │  Estimated maintenance overhead: 28 hrs/month              │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─ Findings (12) ────────────────────────────────────────────┐   │
│  │  [Severity ▼] [File ▼] [Sort: Impact ▼]                    │   │
│  │                                                             │   │
│  │  🔴 src/legacy/auth.ts           CC=28  MI=32  [-12 pts]   │   │
│  │  🔴 src/legacy/payments.ts       CC=22  MI=41  [-8 pts]    │   │
│  │  🟡 src/api/routes.ts            CC=18  MI=55  [-5 pts]    │   │
│  │  🟡 src/services/billing.ts      CC=17  MI=58  [-4 pts]    │   │
│  │  🟡 8 more...                [Show all]                    │   │
│  │                                                             │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.4 Category-Specific Finding Views

Each category has tailored finding display:

| Category | Primary Metrics Shown | Action Hints |
|----------|----------------------|--------------|
| **Complexity** | CC, Cognitive Complexity, MI, LOC | "Refactor into smaller functions", "Extract class" |
| **Staleness** | Days stale, churn rate, last author, ownership % | "Add ownership docs", "Schedule refactor", "Delete if dead" |
| **Security** | CVE ID, CVSS, fixed version, dependency tree path | "npm audit fix", "Update to x.y.z", "Replace package" |
| **Duplication** | % similar, block size, file locations | "Extract shared utility", "Use shared component" |
| **Testing** | Coverage %, uncovered lines, critical paths | "Add unit tests for X", "Improve integration coverage" |

### 6.5 Category Interaction Details

| Interaction | Behavior |
|-------------|----------|
| **Click finding row** | → Finding Detail page (Section 8) |
| **Click file path** | → File-level view with annotated source (future) |
| **Hover delta (-12 pts)** | Tooltip: "This file contributes 12 points to the 30-point complexity penalty" |
| **Sort by Impact** | Default. Sorts by points contributed to category penalty (descending) |
| **Filter by severity** | Multi-select: Critical / Warning / Info |
| **Configure thresholds [⚙]** | Opens repo settings scoped to this category (Section 4.2) |

------

## 7. Debt Trend Visualization

### 7.1 Purpose

Debt trend visualization answers the single most important question for stakeholders: **\"Is our codebase getting better or worse?\"** It transforms point-in-time scores into a narrative of trajectory, enabling proactive decisions before debt becomes crisis.

### 7.2 Trend Chart Variants

#### 7.2.1 Hero Trend (Dashboard — 30-Day Default)

Primary visualization on Repo Dashboard (Section 3.1). Shows overall score trajectory with category overlay capability.

\\\
┌─────────────────────────────────────────────────────────────────────┐
│  Trend                          [30d ▼] [Category: Overall ▼]     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  100 ┤                                                             │
│      │                                                             │
│   90 ┤                                                             │
│      │                                                             │
│   80 ┤           ╭─────╮                                         │
│      │        ╭╯     ╰╮                                          │
│   70 ┤   ╭────╯         ╰────╮                                   │
│      │  ╯                     ╰──╮                               │
│   60 ┤╯                           ╰────╮                         │
│      │                                ╰──╮                       │
│   50 ┤                                  ╰──────╮                 │
│      │                                       ╰──╮                │
│   40 ┤                                          ╰────╮           │
│      │                                              ╰─╮          │
│   30 ┤                                                ╰╮         │
│      └─────────────────────────────────────────────┘          │
│      30d      25d      20d      15d      10d       5d    Today │
│                                                                     │
│  ┌─ Legend ──────────────────────────────────────────────────┐   │
│  │  ━━━ Overall (72)    ━━━ Complexity (68)  ━━━ Security (85) │
│  │  ━━━ Staleness (58)  ━━━ Duplication (91) ━━━ Testing (95)  │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
\\\

**Interactions:**
- **Time range selector:** 7d / 30d / 90d / 1y / All
- **Category filter:** Overall (default) / individual categories / custom multi-select
- **Hover:** Tooltip with exact score, date, and delta from previous period
- **Click data point:** → Scan Detail view for that run
- **Legend click:** Toggle category series on/off

#### 7.2.2 Compact Trend (Repo Table, PR Check, Mobile)

Miniature sparkline for space-constrained contexts.

\\\
┌────────────────────────────────────────────────────┐
│ acme/payment-service  │  68  │ ▁▂▃▅▇▅▃▂▁  │ ▼ -3  │
│ acme/api-gateway      │  82  │ ▂▃▅▇▇▅▃▂▁  │ ▲ +5  │
│ acme/legacy-admin     │  45  │ ▁▁▁▁▁▂▂▃▃  │ ▼ -12 │
└────────────────────────────────────────────────────┘
\\\

- **Size:** ~120×20px sparkline
- **Color:** Band color of most recent score (green/yellow/orange/red)
- **Delta:** 7-day change with arrow
- **Click:** Expands to Hero Trend

#### 7.2.3 Comparative Trend (Org View, Executive View)

Side-by-side repository comparison for portfolio-level visibility.

\\\
┌─────────────────────────────────────────────────────────────────────┐
│  Portfolio Trend — Last 90 Days                          [Export] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  100 ┤  ╭────────────────────────────────────────── ml-pipeline    │
│      │  │                                                       │
│   90 ┤  │  ╭────────────────────── api-gateway                   │
│      │  │  │                                                    │
│   80 ┤  │  │  ╭───────────── frontend-web                       │
│      │  │  │  │                                                │
│   70 ┤  │  │  │  ╭────── payment-service                        │
│      │  │  │  │  │                                             │
│   60 ┤  │  │  │  │  ╭── legacy-admin                            │
│      │  │  │  │  │  │                                           │
│   50 ┤  │  │  │  │  │                                           │
│      └──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┘ │
│      90d    75d    60d    45d    30d    15d     Today           │
│                                                                     │
│  [ ] Show only repos with score < 60    [ ] Highlight declines    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
\\\

**Use cases:** Engineering VP reviews, board reporting, resource allocation decisions

### 7.3 Trend Data Semantics

| Concept | Definition | API Field |
|---------|------------|-----------|
| **Score at time T** | Weighted category score from analysis run at T | score |
| **Delta (7d)** | score(T) - score(T-7d) | delta_7d |
| **Delta (30d)** | score(T) - score(T-30d) | delta_30d |
| **Velocity** | Points/week over trailing 30d (linear fit slope) | elocity_30d |
| **Volatility** | Standard deviation of daily scores over 30d | olatility_30d |
| **Trend direction** | improving / stable / declining / olatile | 	rend |
| **Category trend** | Same metrics per category | categories[*].trend |

**Trend classification rules:**
- improving: velocity > +0.5 pts/week AND volatility < 3
- declining: velocity < -0.5 pts/week AND volatility < 3
- olatile: volatility ≥ 3 (regardless of velocity)
- stable: otherwise

### 7.4 Trend Annotations

Automated and manual markers on the trend line to explain inflection points.

\\\
┌─────────────────────────────────────────────────────────────────────┐
│  Trend with Annotations                                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  80 ┤           ╭─●─╮  ▲ Major refactor merged (PR #847)         │
│      │        ╭╯     ╰╮                                            │
│   70 ┤   ╭────╯         ╰────╮  ● CVE-2024-XXXXX introduced       │
│      │  ╯                     ╰──╮                                 │
│   60 ┤╯                           ╰────╮  ▲ Dependency upgrades   │
│      │                                ╰──╮                         │
│   50 ┤                                  ╰──────╮                  │
│      └────────────────────────────────────────────────────────────┘
│      30d                                    15d      Today          │
│                                                                     │
│  Annotations:  ● Auto (scan event)    ▲ Manual (team note)         │
│                [Add Note]                                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
\\\

**Auto-annotations (generated by system):**
- Score change ≥ 10 points in single run
- New critical vulnerability detected
- Category weight changed in settings
- Scan configuration changed (excluded paths, thresholds)
- Repository webhook reconnected after downtime

**Manual annotations (team-added):**
- \"Major refactor merged\"
- \"Tech debt sprint completed\"
- \"Legacy module deprecated\"
- Free-form note with timestamp and author

### 7.5 Trend Insights Panel

AI-generated (or rule-based) narrative summaries accompanying the chart.

\\\
┌─────────────────────────────────────────────────────────────────────┐
│  📈 Trend Insights — Last 30 Days                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  **Overall:** Improving (+0.8 pts/week). Score rose from 64 → 72.  │
│                                                                     │
│  **Drivers:**                                                       │
│  • Security improved +17 pts (dependency upgrades, Week 2)         │
│  • Complexity stable (68) — legacy/auth.ts still dominant drag     │
│  • Staleness worsening (-5 pts) — 3 files crossed 90-day threshold │
│                                                                     │
│  **Risks:**                                                         │
│  • Staleness velocity: -1.2 pts/week. Projected score in 30d: 53   │
│  • Volatility: 4.2 (high) — scores swing ±8 pts between runs       │
│                                                                     │
│  **Recommended Actions:**                                           │
│  1. Assign ownership to src/legacy/auth.ts (stops staleness bleed) │
│  2. Schedule dependency update sprint (locks security gains)       │
│  3. Enable scheduled scans (reduces volatility from manual runs)   │
│                                                                     │
│  [Dismiss]  [Create Tasks]  [View Full Report]                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
\\\

**Insight types:**
- **Trajectory:** Direction + velocity + projection
- **Drivers:** Top 3 category contributors to score change
- **Risks:** Negative velocities, high volatility, approaching thresholds
- **Recommendations:** Specific, prioritized, linked to settings/actions

### 7.6 Trend API Contract

\\\	ypescript
interface TrendPoint {
  timestamp: string;           // ISO 8601
  score: number;              // 0-100
  categories: {
    [key: string]: number;    // categoryKey -> 0-100
  };
  runId: string;              // analysis run identifier
  annotations?: Annotation[];
}

interface Annotation {
  id: string;
  type: 'auto' | 'manual';
  timestamp: string;
  label: string;
  description?: string;
  author?: string;            // for manual
  relatedRunId?: string;      // for auto
}

interface TrendResponse {
  repoId: string;
  range: { start: string; end: string };
  granularity: 'hour' | 'day' | 'week';
  points: TrendPoint[];
  summary: {
    currentScore: number;
    delta7d: number;
    delta30d: number;
    velocity30d: number;
    volatility30d: number;
    trend: 'improving' | 'stable' | 'declining' | 'volatile';
    categoryTrends: { [key: string]: CategoryTrend };
  };
  insights: Insight[];
}
\\\

### 7.7 Empty/Loading/Error States (Trend)

| State | Hero Trend | Compact Trend | Insights Panel |
|-------|------------|---------------|----------------|
| **Loading** | Skeleton axes + shimmer line | Gray sparkline placeholder | \"Analyzing trends...\" |
| **< 2 data points** | \"Need at least 2 scans for trend. [Rescan Now]\" | \"—\" | Hidden |
| **Single category selected, no data** | \"No data for [Category] in this range\" | N/A | Hidden |
| **Error** | \"Unable to load trend\" + [Retry] | \"ERR\" | \"Insights unavailable\" |

### 7.8 Accessibility (Trend)

- **SVG charts:** <svg role=\"img\" aria-labelledby=\"trend-title trend-desc\">
- **Text alternative:** \"Score trend over 30 days: started at 64, peaked at 78, currently 72. Overall improving at 0.8 points per week.\"
- **Data table fallback:** Hidden accessible table with all data points for screen readers
- **Keyboard:** Tab to chart → arrow keys navigate points → Enter opens Scan Detail
- **Color blind safe:** Pattern fills (dots/dashes) + color for category series
- **Reduced motion:** Static line (no draw animation), instant tooltip

---
