# Client onboarding readiness runbook

This is an operator checklist for a future controlled client deployment. It is
not a compliance certification, security warranty, or evidence that an external
deployment occurred.

## Run the fail-closed preflight

From `backend/`, with the deployment environment and production encryption
provider injected into the process, run:

```console
python scripts/readiness.py
```

The command emits JSON and exits `0` only when every blocking check passes. It
exits `1` otherwise. Authenticated `GET /api/ops/readiness` returns the same
redacted contract and HTTP 503 while blocked. Never put environment variables,
database URLs, filesystem paths, private keys, or tokens in a ticket; share
only check codes and pass/fail state.

`ASK_SONAR_PROVIDER` is optional. `CALIBRATION_CORPUS_VALIDATED` is blocking and
remains false until the blinded, independently labeled benchmark is completed
and integrated. Do not describe current grades as externally validated.

## Required configuration

- Configure unique server-owned tenant credentials in
  `CODESONAR_API_TENANT_TOKENS`; do not use `local` or reuse tokens.
- Set an exact HTTPS production allowlist in `CODESONAR_CORS_ORIGINS`.
- Use PostgreSQL via `CODESONAR_DATABASE_URL`; SQLite is local-only.
- Apply Alembic migrations and verify revision `20260902_0002`.
- Inject a deployment-owned `production_safe` encryption provider and select it
  with `CODESONAR_ENCRYPTION_PROVIDER`. The local provider is forbidden.
- Provision `CODESONAR_DATA_ROOT` outside the checkout with least-privilege
  ownership/ACLs and no links or reparse points.
- Configure the GitHub App ID, private key, slug, install-state secret, and
  webhook secret. Select only client-approved repositories.
- Configure a stable randomly generated remediation approval secret of at
  least 32 characters and keep executor access least-privileged.
- Review the tenant retention policy before ingesting code or metadata.

## Deployment verification

1. Run backend tests, Ruff, strict mypy, frontend lint/build, dependency audit,
   and self-scan from a pinned release revision.
2. Run `alembic upgrade head`, then preflight in the service runtime identity.
3. Confirm unauthenticated access is denied and test tenants see only their own
   empty project lists.
4. Send a signed test webhook and confirm replay rejection without logging its
   payload.
5. Exercise export and deletion requests with synthetic tenant data. Do not
   hard-delete live client data during onboarding verification.
6. Record release revision, check codes, timestamps, operator identity, and
   blocker remediation, but never secrets.

Before ingestion, obtain agreement on repository scope, branches, retention and
deletion, remediation behavior, incident contact, export delivery, and whether
Ask Sonar is enabled. Explain that deterministic scoring is authoritative in
the product while external calibration remains open.

The gate does not complete managed KMS/key rotation, PostgreSQL row-level
security, managed backup/PITR, restore drills, automated retention, penetration
testing, or formal compliance assessment. These remain gates where required.
