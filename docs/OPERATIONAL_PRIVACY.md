# Operational privacy checkpoint

This checkpoint adds tenant-scoped privacy operations to the transactional
persistence boundary. Every `/api/privacy/*` request passes through the normal
bearer-token boundary; the tenant comes from the server-owned token mapping and
never from a request field or tenant header. Requests and completions create
tenant-scoped audit events.

## Retention policy

Each tenant may record scan, audit, export-artifact, backup, deletion-recovery,
and backup-deletion-lag day values. These records express policy and make
eligibility explicit. This checkpoint does not yet schedule scan/audit pruning
or configure a backup system. `backup_retention_days` and
`backup_deletion_lag_days` document the maximum intended persistence outside
the primary database; an operator must align them with the eventual managed
backup provider and legal requirements.

## Export contract

`POST /api/privacy/exports` returns HTTP 202 and a job resource. The MVP claims
and executes that queued job inline, while retaining `queued`, `running`,
`completed`, and `failed` states for a future worker. The versioned JSON archive
is encrypted by the configured persistence encryption provider and authenticated
to its tenant and job. The job records SHA-256 integrity metadata and expiry.

The decrypted manifest intentionally omits tenant IDs, server checkout and
repository paths, encrypted path columns, credentials/secrets, and raw webhook
payloads. Cross-tenant job and archive lookups return not found. The encrypted
blob currently remains in PostgreSQL; this is not cloud object storage.

## Deletion workflow

`POST /api/privacy/deletion-requests` marks the authenticated tenant pending
deletion and calculates an eligibility time from its recovery policy. Repeating
the request preserves the original window. There is deliberately no HTTP hard
delete endpoint.

After the recovery window, an operator runs:

`python scripts/hard_delete_tenant.py --tenant TENANT --request-token CHANGE_TICKET`

The command locks/idempotently identifies the request, invokes the injected
tenant-key crypto-erasure hook, removes tenant rows in foreign-key-safe order,
and leaves only a content-free receipt. The receipt contains no tenant ID or
content; its one-way request fingerprint supports safe retries. Local encryption
has no per-tenant key, so its honest hook status is `not_configured`.

## Still required for production

- Managed KMS/envelope-key implementation, key lifecycle, and verified erasure.
- Durable object storage and independently authorized archive delivery.
- Automated retention workers and legal-hold handling.
- Managed backup/PITR configuration, deletion propagation measurement, and
  restore drills.
- PostgreSQL row-level security and an operational incident/audit platform.

SQLite remains limited to tests and single-process local development.
