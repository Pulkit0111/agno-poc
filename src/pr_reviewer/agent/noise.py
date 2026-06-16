"""Noise-file filter (port of util/noise-files.ts intent).

Lockfiles, generated/minified/vendored artifacts — not worth reviewer attention.
"""

from __future__ import annotations

_NOISE_BASENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "composer.lock",
    "gemfile.lock",
    "poetry.lock",
    "cargo.lock",
    "go.sum",
    "go.work.sum",
    "uv.lock",
    "pipfile.lock",
}

_NOISE_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".map",
    ".snap",
    ".lock",
)

_NOISE_DIR_SEGMENTS = (
    "node_modules/",
    "vendor/",
    "dist/",
    "build/",
    ".next/",
    "__generated__/",
    "generated/",
)


def is_noise_file(path: str) -> bool:
    p = path.lower()
    base = p.rsplit("/", 1)[-1]
    if base in _NOISE_BASENAMES:
        return True
    if p.endswith(_NOISE_SUFFIXES):
        return True
    if any(seg in p for seg in _NOISE_DIR_SEGMENTS):
        return True
    return False
