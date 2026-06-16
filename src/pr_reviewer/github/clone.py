"""Shallow clone of a repo at the PR head SHA — port of shallow-clone.ts.

git init + fetch --depth 1 of the exact SHA (falling back to the PR head ref for
cross-fork PRs whose head SHA isn't directly fetchable), then checkout. Context
manager: the temp dir is rm -rf'd on exit. Nothing is persisted.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
import time
from typing import Optional

from ..observability.logging_setup import get_logger, redact

log = get_logger("review.clone")
_CLONE_PREFIX = "bott-poc-review-"


class CloneError(RuntimeError):
    pass


def sweep_stale_clones(max_age_seconds: int = 3600) -> int:
    """Remove clone temp dirs left behind by killed processes. Returns count removed."""
    removed = 0
    pattern = os.path.join(tempfile.gettempdir(), _CLONE_PREFIX + "*")
    for path in glob.glob(pattern):
        try:
            if time.time() - os.path.getmtime(path) > max_age_seconds:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            pass
    return removed


def _run(args: list[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False
    )


class CloneHandle:
    """Live checkout. Use as a context manager; `.path` is the repo root."""

    def __init__(self, path: str):
        self.path = path

    def __enter__(self) -> "CloneHandle":
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def shallow_clone(
    owner: str,
    name: str,
    head_sha: str,
    *,
    pr_number: Optional[int] = None,
    token: Optional[str] = None,
) -> CloneHandle:
    if token:
        url = f"https://x-access-token:{token}@github.com/{owner}/{name}.git"
    else:
        url = f"https://github.com/{owner}/{name}.git"

    tmp = tempfile.mkdtemp(prefix=_CLONE_PREFIX)
    try:
        for cmd in (["git", "init", "-q"], ["git", "remote", "add", "origin", url]):
            r = _run(cmd, cwd=tmp)
            if r.returncode != 0:
                raise CloneError(f"{' '.join(cmd[:2])} failed: {redact(r.stderr.strip())}")

        # Try the exact SHA first (works for same-repo PRs). Fall back to the
        # PR head ref for cross-fork PRs where the SHA isn't directly fetchable.
        fetched_ref = head_sha
        r = _run(["git", "fetch", "--depth", "1", "origin", head_sha], cwd=tmp)
        if r.returncode != 0 and pr_number is not None:
            r2 = _run(
                ["git", "fetch", "--depth", "1", "origin", f"pull/{pr_number}/head"],
                cwd=tmp,
            )
            if r2.returncode != 0:
                raise CloneError(
                    f"fetch failed for both {head_sha} and pull/{pr_number}/head: "
                    f"{redact(r.stderr.strip())} | {redact(r2.stderr.strip())}"
                )
            fetched_ref = "FETCH_HEAD"
        elif r.returncode != 0:
            raise CloneError(f"fetch failed for {head_sha}: {redact(r.stderr.strip())}")

        r = _run(["git", "checkout", "-q", fetched_ref], cwd=tmp)
        if r.returncode != 0:
            # FETCH_HEAD checkout sometimes needs a detach; retry explicitly.
            r = _run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=tmp)
            if r.returncode != 0:
                raise CloneError(f"checkout failed: {redact(r.stderr.strip())}")
        return CloneHandle(tmp)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
