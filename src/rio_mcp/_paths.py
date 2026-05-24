"""Resolve bundled reference data and the local cache directory."""
from __future__ import annotations

import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent


def reference_dir() -> Path:
    """Bundled reference data (stay-spending unit costs + sector mapping).

    Installed layout: ``rio_mcp/data/reference``. Dev layout (running from a
    source checkout): ``<repo>/data/reference``.
    """
    for cand in (_PKG / "data" / "reference", _PKG.parents[1] / "data" / "reference"):
        if cand.exists():
            return cand
    return _PKG / "data" / "reference"


def cache_dir() -> Path:
    """Writable cache for extracted coefficient tables.

    Override with ``RIO_MCP_CACHE_DIR``; defaults to ``~/.cache/korea-rio-mcp``.
    """
    base = os.environ.get("RIO_MCP_CACHE_DIR")
    path = Path(base) if base else Path.home() / ".cache" / "korea-rio-mcp"
    path.mkdir(parents=True, exist_ok=True)
    return path
