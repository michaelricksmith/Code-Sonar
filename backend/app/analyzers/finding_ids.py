"""Stable, cross-process finding ID construction.

Finding IDs must be deterministic across processes: the drift view matches
findings across scans by ID. Python's built-in hash() is salted per process,
so IDs built from it silently reshuffle on every restart or redeploy.
Always build finding IDs with stable_finding_id, never with hash().
"""

import hashlib


def stable_finding_id(prefix: str, *parts: object) -> str:
    """Build a deterministic finding ID from a prefix and key parts.

    The parts are joined with a unit separator and hashed with SHA-256,
    so identical inputs always produce the identical ID in any process.
    """
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return prefix + hashlib.sha256(payload).hexdigest()[:16]
