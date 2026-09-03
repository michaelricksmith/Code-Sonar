"""Explicit operator command for an eligible tenant hard deletion."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.persistence import configure_persistence_from_env
from app.security.tenant import bind_tenant, reset_tenant


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True, help="Exact tenant selected by the operator")
    parser.add_argument(
        "--request-token",
        required=True,
        help="Stable deletion request/change-ticket token used only to make the command idempotent",
    )
    args = parser.parse_args()
    persistence = configure_persistence_from_env()
    if persistence is None:
        raise RuntimeError("Transactional persistence is required")
    token = bind_tenant(args.tenant)
    try:
        receipt = persistence.privacy.hard_delete(request_token=args.request_token)
    finally:
        reset_tenant(token)
    print(json.dumps(asdict(receipt), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
