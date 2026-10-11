"""Weekly digest email templates (HTML + plain text).

Copyright © 2026 Michael Smith. All rights reserved.

Copy rules: plain language, every number from real stored state, one
clear call to action. No leaderboard language, no generic "we miss you".
"""

from __future__ import annotations

from typing import Any

APP_URL = "https://code-sonar.onrender.com"


def render_text(digest: dict[str, Any], unsubscribe_url: str) -> str:
    lines = ["Your weekly code health report", ""]
    for repo in digest["repos"]:
        delta = repo["score_delta"]
        delta_text = (
            f" ({delta:+d} since last scan)" if isinstance(delta, int) else ""
        )
        lines.append(
            f"{repo['repository_label']}: score {repo['score']} "
            f"({repo['grade']}){delta_text}, "
            f"{repo['finding_count']} open issues, "
            f"{repo['resolved_count']} fixed since last scan"
        )
    lines.append("")
    lines.append(
        f"You verified {digest['verified_this_week']} "
        f"{'fix' if digest['verified_this_week'] == 1 else 'fixes'} this week."
    )
    if digest.get("cta"):
        lines.append("")
        lines.append(digest["cta"]["text"])
        lines.append(f"Open your report: {APP_URL}")
    lines.append("")
    lines.append(f"Unsubscribe: {unsubscribe_url}")
    return "\n".join(lines)


def render_html(digest: dict[str, Any], unsubscribe_url: str) -> str:
    rows = []
    for repo in digest["repos"]:
        delta = repo["score_delta"]
        if isinstance(delta, int):
            arrow = "▲" if delta > 0 else "▼" if delta < 0 else "■"
            delta_html = f'<span>{arrow} {delta:+d}</span>'
        else:
            delta_html = "<span>—</span>"
        rows.append(
            "<tr>"
            f"<td><strong>{repo['repository_label']}</strong></td>"
            f"<td>{repo['score']} ({repo['grade']})</td>"
            f"<td>{delta_html}</td>"
            f"<td>{repo['finding_count']} open</td>"
            f"<td>{repo['resolved_count']} fixed</td>"
            "</tr>"
        )
    cta_html = ""
    if digest.get("cta"):
        cta_html = (
            f'<p><a href="{APP_URL}">{digest["cta"]["text"]}</a></p>'
        )
    return f"""\
<html><body style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
<h2>Your weekly code health report</h2>
<table cellpadding="8" cellspacing="0" border="0">
<tr><th align="left">Repo</th><th>Score</th><th>Trend</th><th>Open</th><th>Fixed</th></tr>
{''.join(rows)}
</table>
<p>You verified <strong>{digest['verified_this_week']}</strong> fixes this week.</p>
{cta_html}
<p style="font-size: 12px; color: #666;">
<a href="{unsubscribe_url}">Unsubscribe</a> from the weekly digest.
</p>
</body></html>"""
