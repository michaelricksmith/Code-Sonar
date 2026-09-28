# Email setup (Code Sonar / CodeVitals)

**Current state:** the app sends all billing-lifecycle email (purchase
receipts, cancellation confirmations, annual renewal reminders) through a
provider-agnostic SMTP transport. With no provider configured it uses the
**log transport** — every message is logged and kept in the local outbox
(`~/.code-sonar/email-outbox`) so nothing is silently dropped, but nothing
leaves the machine.

**Decision:** send via **Resend** (free tier, 3,000 emails/month, no credit
card) using its SMTP interface (`smtp.resend.com:587`). The API key stays
in Render env vars — it is never committed to the repo.

## Founder steps

1. **Create a Resend account** at https://resend.com and create an API
   key (Permissions: *Sending access*).
2. **Verify the sending domain.** `codevitals.tech` is still in IONOS
   review. Until it is active you have two options:
   - Send from Resend's onboarding sender — test only: Resend only
     allows sends to the account owner's own address until a domain is
     verified, so this does NOT work for real users.
   - **Recommended: wait for `codevitals.tech`, then add it in
     Resend → Domains** and add the DKIM/SPF DNS records Resend shows
     you at IONOS. Sending works for all recipients once verified.
3. **Set these Render env vars** (Dashboard → your service → Environment):

   | Variable | Value |
   |---|---|
   | `EMAIL_PROVIDER` | `resend` |
   | `RESEND_API_KEY` | the key from step 1 (paste once, store in Secure Vault too) |
   | `EMAIL_FROM` | `CodeVitals <billing@codevitals.tech>` (after domain verified) |
   | `EMAIL_MARKETING_FROM` | `CodeVitals <updates@codevitals.tech>` (can split to a subdomain later) |
   | `EMAIL_FROM_NAME` | `CodeVitals` (optional; prepends a display name to a bare address) |

4. **Redeploy.** No code change needed — the transport reads env at
   send time.
5. **Verify:** place a test checkout, cancel it, and confirm you receive
   the receipt and cancellation emails. Then run
   `python scripts/annual_reminders.py --list` to preview who is due a
   renewal reminder (the script is idempotent — it records every send).

## Other providers

Any SMTP provider works — the Resend profile is just SMTP defaults:

```
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-username
SMTP_PASS=your-password
SMTP_TLS=true
EMAIL_FROM=CodeVitals <billing@codevitals.tech>
```

## What the app already does for compliance

- Purchase receipt includes renewal terms, cancellation policy, and a
  direct cancel link (CA AB 2863 retainable acknowledgment).
- Cancellation confirmation email on every cancel (in-app or webhook).
- Annual renewal reminders via `scripts/annual_reminders.py --send`
  (cron-safe, idempotent; run monthly from any scheduler).
- Marketing email only to opted-in users, with RFC 8058 one-click
  `List-Unsubscribe` headers on every marketing message.
- Bounded retries with backoff on transient SMTP failures; structured
  logs record routing metadata only (never email bodies).

## Notes

- Legacy `SONAR_EMAIL_TRANSPORT` / `SONAR_SMTP_*` env names still work
  as aliases for `EMAIL_PROVIDER` / `SMTP_*`.
- Keep transactional and marketing mail on separate sender addresses
  (they already are: `EMAIL_FROM` vs `EMAIL_MARKETING_FROM`); split
  them into subdomains (e.g. `mail.codevitals.tech`) if deliverability
  tuning is ever needed.

Copyright © 2026 Michael Smith. All rights reserved.
