"""Pre-launch consumer-compliance records: auto-renewal consent, cancellations,
marketing consent, age-gate confirmations, and GPC opt-out signals.

Records are append-only administrative proof kept for the retention period
the law requires (e.g. California AB 2863: auto-renewal consent records for
3 years). The JSON store is the local-dev fallback; the SQL store is used
when transactional persistence is configured.

Copyright © 2026 Michael Smith. All rights reserved.
"""
