# Transactional persistence foundation

This checkpoint replaces the process-local persistence seam when
`CODESONAR_DATABASE_URL` is configured. It is a foundation, not a claim that
Code Sonar has completed production data operations.

## Deployment modes

- Local single-process development may omit the database URL and retain the
  legacy files, or use `sqlite:///...` with `CODESONAR_LOCAL_DEV=1`.
- Any non-local/shared deployment must use a `postgresql+psycopg://...` URL.
  Startup rejects SQLite, a missing database, a non-current Alembic revision,
  or the local encryption provider in shared mode.
- Apply migrations once as a deployment step:

  `python -m alembic -c alembic.ini upgrade head`

  Web workers do not run PostgreSQL migrations automatically.

## Encryption

Project checkout paths are AES-256-GCM encrypted in local SQL development.
Ciphertext is authenticated with tenant, table, project, field, and schema
identity, preventing ciphertext from being moved across tenants or records.
Generate a local-only key with a cryptographically secure 32-byte random value
encoded using URL-safe base64 and set `CODESONAR_LOCAL_ENCRYPTION_KEY`.

Shared deployments require `CODESONAR_ENCRYPTION_PROVIDER` to name a
deployment-injected provider whose `production_safe` property is true. No KMS
adapter is shipped by this checkpoint, and an environment key is not accepted
as a production substitute.

## Legacy import

Legacy data is never imported during application startup. Run the explicit
operator command once per source file:

`python scripts/import_legacy_persistence.py --tenant TENANT --kind history --source PATH`

Kinds include history, projects, GitHub installations, webhook deliveries,
webhook jobs, and remediation outcomes. Each import, its source SHA-256, tenant,
and verified row count are recorded in `migration_ledger` in the same database
transaction as the imported rows. Re-running an identical import reports
`already_imported`; it does not duplicate data. Foreign-key order is intentional:
projects/scans/deliveries must exist before dependent jobs or outcomes.

Keep source files read-only until row counts and application smoke tests have
been verified. The importer does not delete or rewrite them.

## Filesystem boundary

`CODESONAR_DATA_ROOT` must be a real directory, not a symlink. New POSIX roots
are created with mode 0700; local roots are tightened to that mode and shared
roots with group/other permissions are rejected. SQLite files are owner-only
and cannot be symlinks. Shared Windows deployments verify ACLs and reject broad write grants
to Everyone, Builtin Users, or Authenticated Users.

## Concurrency guarantees

- A project scan, its normalized findings, and the project's latest baseline
  commit in one transaction.
- Webhook replay claims use the unique tenant/delivery key.
- Workers claim queued jobs with one conditional update and record a lease
  owner and expiry. A second worker cannot claim the same queued job.
- Tenant-owned tables use composite tenant/resource primary or foreign keys.

The PostgreSQL CI service exercises replay and worker-claim behavior. Local
SQLite is not evidence of multiworker production correctness.

## Explicitly unfinished

This checkpoint does not provide a production KMS adapter, automated key
rotation, retention/deletion/export jobs, PostgreSQL row-level-security policy,
managed backup/PITR configuration, or restore drills. Those remain release
gates and must not be inferred from the presence of the SQL schema.
