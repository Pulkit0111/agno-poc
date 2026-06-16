"""Parse unified-diff patches to find which head-side lines are anchorable.

GitHub rejects an entire review if an inline comment points at a path:line not in
the diff. We use this to split comments into resolvable (post inline) vs
unresolvable (fall back to the body) — mirrors run.ts's isAnchorInDiff usage.
"""

from __future__ import annotations

import re

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def anchorable_lines(patch: str | None) -> set[int]:
    """Head-side (new file) line numbers that appear in the diff as added or
    context lines — the lines GitHub will accept an inline comment on."""
    out: set[int] = set()
    if not patch:
        return out
    new_line = 0
    in_hunk = False
    for raw in patch.splitlines():
        m = _HUNK_RE.match(raw)
        if m:
            new_line = int(m.group(1))
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw.startswith("+"):
            out.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            pass  # removed line — not on the head side
        elif raw.startswith("\\"):
            pass  # "\ No newline at end of file"
        else:  # context line
            out.add(new_line)
            new_line += 1
    return out


def is_anchor_in_diff(patches_by_path: dict[str, str | None], path: str, line: int) -> bool:
    if path not in patches_by_path:
        return False
    return line in anchorable_lines(patches_by_path[path])
