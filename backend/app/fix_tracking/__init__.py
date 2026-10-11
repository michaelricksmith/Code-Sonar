"""Durable fix tracking for prompt-first remediation.

Copyright © 2026 Michael Smith. All rights reserved.

Replaces the ephemeral ``~/.code-sonar/prompt-events.jsonl`` file. Every
copied fix prompt is recorded as a ``FixAttempt`` with the user who copied
it; when a later rescan shows the finding is gone, the attempt is marked
verified. Verified attempts are the raw material for per-user fix stats,
streaks, and the weekly digest.
"""

from app.fix_tracking.models import FixAttempt
from app.fix_tracking.runtime import (
    get_fix_attempt_store,
    set_fix_attempt_store,
)

__all__ = ["FixAttempt", "get_fix_attempt_store", "set_fix_attempt_store"]
