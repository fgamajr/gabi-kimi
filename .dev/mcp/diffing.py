from __future__ import annotations

import difflib


def unified_diff(before: str, after: str, from_name: str = "before", to_name: str = "after") -> str:
    if before == after:
        return ""
    lines = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=from_name,
        tofile=to_name,
        lineterm="",
    )
    return "\n".join(lines)
