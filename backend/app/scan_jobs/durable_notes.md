# Durable scan jobs — design notes

## Goal
Turn the existing in-process scan jobs into something that survives a process restart or cold start. A lost job during a VC demo is the highest operational risk.

## Current state
- Frontend already calls `POST /api/scan-job` and polls `GET /api/scan-job/{id}` (`frontend/src/api/scanJobs.ts`).
- Status values: `queued | running | done | error`.
- Backend currently runs jobs in-process (threaded). Restart loses them.

## Minimal durable shape (fits existing Postgres)
```sql
CREATE TABLE scan_jobs (
  id UUID PRIMARY KEY,
  repository_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','interrupted')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  error_message TEXT,
  result_scan_id TEXT,
  payload JSONB
);
```

## Worker rules
1. On startup, any row left in `running` is marked `interrupted` (or reset to `queued`).
2. Worker claims the oldest `queued` job, sets `running` + `started_at`, runs the existing deterministic scan, then writes `succeeded` + `result_scan_id` or `failed` + message.
3. Frontend already polls; map `interrupted` / `failed` to the existing `error` status and show the recovery line.

## Why this is enough for the raise
- Demo no longer dies on a redeploy or free-tier restart.
- Fail-closed scoring is preserved (no partial score).
- Reuses the Postgres you already have once the plan is upgraded.

## Next implementation step
Alembic migration + small worker loop in the existing FastAPI process (or a Render background worker). Engine stays untouched.
