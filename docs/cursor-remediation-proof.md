# Cursor remediation proof

This is the acceptance procedure for Code Sonar's first real remediation proof.

## What CI proves

`backend/tests/integration/test_cursor_remediation_proof.py` exercises the concrete
authorization service, disposable Git worktree manager, Cursor executor, validation
commands, repository scanner, deterministic scoring engine, history store, outcome
store, and orchestrator in one test. The external Cursor process boundary is
deterministic in CI so CI never requires a developer's Cursor account.

The test must prove all of these conditions:

- the selected finding exists in the persisted baseline;
- remediation runs only on a `code-sonar/remediation/*` worktree branch;
- the executor reports the changed file;
- a real test command passes inside the worktree;
- a real Code Sonar rescan resolves the selected finding;
- the deterministic score increases and debt points decrease;
- no regression is detected and a successful outcome label is recorded;
- the active checkout's HEAD, status, and target-file bytes remain unchanged;
- the disposable worktree and remediation branch are removed.

## What requires the Windows Cursor host

CI does not claim that an installed Cursor CLI edited a repository. That claim is
allowed only after the same workflow is run on the authorized Windows development
host with the executor explicitly configured as `cursor`.

Required runtime settings:

```powershell
$env:CODE_SONAR_REMEDIATION_EXECUTOR = "cursor"
$env:CODE_SONAR_CURSOR_COMMAND_JSON = '<approved Cursor argv JSON containing {workspace} and {instruction}>'
$env:CODE_SONAR_REMEDIATION_VALIDATORS_JSON = '[{"name":"pytest","kind":"tests","argv":["python","-m","pytest"],"timeout_seconds":300}]'
```

Use the installed Cursor command and flags verified by `--help`; do not guess or
store credentials in this repository. Start Code Sonar, scan an approved disposable
fixture repository, create a grounded Ask Sonar remediation plan, approve it once,
and preserve the returned sanitized workflow result.

## Evidence gate

A successful operator evidence file under `docs/evidence/` must include:

- UTC timestamp, Code Sonar commit SHA, and a non-sensitive repository identifier;
- executor name `cursor`;
- baseline and after-scan IDs;
- remediation branch name and base commit;
- changed relative file names;
- test/build command names and return codes, without captured source or secrets;
- finding resolved, regression detected, score delta, and debt-points delta;
- independently measured active-checkout HEAD/status/file-hash equality;
- independently measured worktree and temporary-branch cleanup.

The proof fails closed unless a tests-kind validator ran and passed, the target
finding disappeared, no regression was detected, score delta is positive, debt
delta is negative, the active checkout is unchanged, and cleanup completed.

## Current proof status

- Concrete full-stack CI integration proof: implemented on
  `remediation/cursor-e2e-proof`; awaiting GitHub Actions.
- Installed Cursor invocation evidence: pending execution on Michael Smith's
  authorized Windows host.
- Production claim: blocked until both gates pass.
