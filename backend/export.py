"""Export stored summaries into one delimited Markdown file.

Blocks are separated by a delimiter line carrying the video's title:

    @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@ [Title] @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
"""
from __future__ import annotations

from typing import Any

DELIMITER_LEFT = "@" * 42
DELIMITER_RIGHT = "@" * 48


def delimiter_line(title: str) -> str:
    clean = " ".join((title or "").split()) or "Untitled"
    return f"{DELIMITER_LEFT} [{clean}] {DELIMITER_RIGHT}"


def format_export(rows: list[dict[str, Any]]) -> str:
    blocks = []
    for row in rows:
        body = (row.get("summary") or "").strip()
        blocks.append(f"{delimiter_line(row.get('title') or '')}\n\n{body}\n")
    return "\n".join(blocks)
