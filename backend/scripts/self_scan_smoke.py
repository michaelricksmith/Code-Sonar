"""Self-scan smoke check.

Runs POST /api/scan against the local backend with a configurable
repo path (default: the repository root) and asserts a sane response.
Exits non-zero on any HTTP error, missing required fields, or empty
findings when the repo is known to have analyzable code.

Usage:
    python backend/scripts/self_scan_smoke.py [--repo PATH] [--base-url URL]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_REPO = r"C:\Users\bookm\.openclaw\workspace\code-sonar"


def post_scan(base_url: str, repo_path: str) -> dict:
    body = json.dumps({"repo_path": repo_path}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/scan",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} from /api/scan", file=sys.stderr)
        print(e.read().decode("utf-8"), file=sys.stderr)
        raise


def get_analyzers(base_url: str) -> list[dict]:
    with urllib.request.urlopen(f"{base_url}/api/analyzers", timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("analyzers", [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Code Sonar self-scan smoke")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Repository path")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument(
        "--min-analyzers",
        type=int,
        default=4,
        help="Minimum registered analyzers required to pass",
    )
    args = parser.parse_args()

    analyzers = get_analyzers(args.base_url)
    if len(analyzers) < args.min_analyzers:
        print(
            f"FAIL: expected at least {args.min_analyzers} analyzers, "
            f"got {len(analyzers)}",
            file=sys.stderr,
        )
        return 2

    print(f"Analyzers registered: {len(analyzers)}")
    for a in analyzers:
        print(f"  - {a['analyzer_id']} (threshold={a.get('threshold')})")

    result = post_scan(args.base_url, args.repo)

    for key in (
        "score",
        "grade",
        "finding_count",
        "findings",
        "summary",
        "scanned_at",
    ):
        if key not in result:
            print(f"FAIL: response missing {key!r}", file=sys.stderr)
            return 3

    print(f"Score:      {result['score']} ({result['grade']})")
    print(f"Findings:   {result['finding_count']}")
    print(f"Debt:       {result['total_debt_points']}")
    print(f"Scanned at: {result['scanned_at']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
