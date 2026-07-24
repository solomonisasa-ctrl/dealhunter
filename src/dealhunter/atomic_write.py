"""Atomic file writes for the JSON/YAML files under data/ and config/.

A plain path.write_text() can interleave with a concurrent writer - e.g.
the dashboard's background hunt thread and a second manual trigger, or a
local "Refresh now" racing a GitHub Actions run pulling/pushing the same
files - and corrupt the file (one write's tail glued onto another's).
Writing to a temp file in the same directory and then os.replace()-ing it
into place is atomic on both Windows and POSIX, so readers always see
either the fully-old or fully-new content, never a half-written mix.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
