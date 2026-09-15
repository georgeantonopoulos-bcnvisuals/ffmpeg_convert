"""Build identity, so the app can tell when it is running stale code.

A uvicorn process keeps whatever modules it imported at startup.  Syncing
new files onto the share therefore changes nothing for anyone already
running the tool, and the only symptom is output that silently disagrees
with the code on disk.  Hashing the files lets the server notice that
itself and say so.
"""

from __future__ import annotations

import hashlib
import os
from typing import Dict, Iterable, List

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Everything whose contents can change what an encode produces or what the
# browser renders.  Keep this list honest: a file that affects output but
# is not hashed here makes the check lie.
TRACKED_SUFFIXES = (".py", ".html", ".js", ".css")


def tracked_paths(root: str = PACKAGE_DIR) -> List[str]:
    """Every file whose content should count towards the build id."""
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(TRACKED_SUFFIXES):
                found.append(os.path.join(dirpath, name))
    return found


def build_id_for_paths(paths: Iterable[str]) -> str:
    """Hash file contents into a short, stable build identifier.

    Sorted so the walk order cannot invent a version change, and missing
    files are skipped so a half-finished rsync degrades to a different id
    rather than an exception.
    """
    digest = hashlib.sha256()
    for path in sorted(paths):
        try:
            with open(path, "rb") as handle:
                digest.update(path.encode("utf-8", "replace"))
                digest.update(handle.read())
        except OSError:
            continue
    return digest.hexdigest()[:12]


def current_build_id() -> str:
    """The build id of what is on disk right now."""
    return build_id_for_paths(tracked_paths())


def staleness(loaded: str, current: str) -> Dict[str, object]:
    """Compare the running build against the one on disk."""
    stale = loaded != current
    message = ""
    if stale:
        message = (
            "This app is running code from before the last update. "
            "Restart it to pick up the current version."
        )
    return {"loaded": loaded, "current": current, "stale": stale, "message": message}


# Captured once, at import time: this is the build the process actually runs.
LOADED_BUILD_ID = current_build_id()
