# Demo Repository — `demo/sample_repo`

A small, self-contained Python sample repository for Code Sonar's
private-beta demo. Intentionally produces:

- **clean findings** (everything passes)
- **moderate findings** (some `comment_markers:todo`, some `oversized_files` near threshold)
- **at least one serious finding** (`secrets:aws-access-key`)
- **hotspot ranking** (multiple findings + multiple analyzers on the same file)
- **score / grade** (drives the dashboard)

Two states are shipped:
- `state-A/` — initial state (current, fewer findings)
- `state-B/` — after "user fixed some TODOs but introduced a secret" (more findings in some places, fewer in others)

The drift demo:
1. Scan `state-A/` → record A
2. Switch to `state-B/` (replace the directory, OR just point the
   dashboard at the same parent dir after the user makes the
   changes described in `STATE-B-CHANGES.md`)
3. Scan again → record B
4. Hit "Compare with previous scan" → see NEW (the secret) +
   RESOLVED (the removed TODOs) + PERSISTENT (the unchanged findings)

## Files

| File | State | What it does |
|---|---|---|
| `app/__init__.py` | A+B | Clean Python module — no findings expected |
| `app/utils.py` | A+B | Small utility module with 1 intentional `TODO` comment (state A) |
| `app/utils.py` (B) | B only | TODOs removed + AWS key added |
| `app/legacy.py` | A | Large function (60 lines) → `oversized_functions:over-threshold` |
| `app/legacy.py` (B) | B | Same function, slightly longer (75 lines) → triggers `WORSENED` |
| `tests/test_utils.py` | A+B | Test file with 1 `TODO: ship it` comment |

## How to use

```bash
# Scan state A
cd /path/to/demo/sample_repo
# In Code Sonar: paste `state-A/` (or just this dir if state-A is the root)
# Run scan
# See: moderate findings, 1 hotspot

# Switch to state B
cd /path/to/demo/sample_repo/state-B
# In Code Sonar: re-paste the path
# Run scan again
# Hit "Compare with previous scan"
# See: NEW (secrets), RESOLVED (TODOs), WORSENED (oversized function)
```

**Note**: state-A and state-B are siblings of this README, not nested.
The "switch" means re-pointing the dashboard at the other directory.
For a smoother demo, use `git checkout` between two commits of the
same directory.
