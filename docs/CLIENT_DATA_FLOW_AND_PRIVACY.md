# Client data flow and privacy summary

This describes the current application boundary. It is not a privacy policy,
data-processing agreement, or certification.

## Data flow

1. An authenticated tenant connects an approved GitHub App installation or
   selects a repository contained under the configured scan root.
2. Code is checked out into a server-controlled workspace. Deterministic local
   analyzers read bounded files and produce findings, completion status, and a
   versioned 300–850 score. Incomplete analysis produces no authoritative score.
3. PostgreSQL stores tenant-keyed projects, scans, findings, webhook state,
   remediation outcomes, privacy jobs, and audits. Sensitive checkout paths are
   encrypted through the injected provider.
4. The UI receives labels, relative finding locations, aggregates, scores, and
   trends. Public responses do not return server checkout paths.
5. Ask Sonar is optional. Its provider receives bounded grounded context and
   has no authority to change the deterministic score.
6. Remediation needs a server-minted, signed, expiring, immutable, single-use
   authorization. It executes in an isolated workspace that is always cleaned,
   followed by tests and a deterministic rescan.

## Tenant and privacy controls

- Bearer credentials map to server-owned tenant identities; caller tenant
  headers have no authority. Application queries use tenant-aware keys.
- Signed GitHub webhooks resolve tenant scope from stored installation
  ownership. Unknown installations cannot select a project.
- Exact CORS origins, scan-root containment, evidence truncation, and secret
  redaction reduce accidental exposure.
- Tenant retention settings, encrypted exports, recovery-gated deletion, audit
  events, and content-free deletion receipts have an authenticated API contract.

Production still requires deployment-owned encryption/KMS, PostgreSQL migration
and backup controls, tested restoration, monitoring, incident response, and any
contractually required independent assessment. Calibration contracts exist but
grades are not externally validated while approved expert labels are absent.
