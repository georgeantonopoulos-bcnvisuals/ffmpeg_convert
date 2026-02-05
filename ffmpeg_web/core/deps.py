"""Dependency checks for the FFmpeg Web UI backend.

This module is a web-friendly counterpart to the original
``check_and_install_dependencies`` logic in ``ffmpeg_ui.py``. It is used by
the FastAPI app to report health and to gate EXR-specific operations.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any, Dict


def _check_oiiotool() -> Dict[str, Any]:
    """Check if ``oiiotool`` is available on the current PATH."""
    path = shutil.which("oiiotool")
    return {
        "available": path is not None,
        "path": path,
    }


def _ensure_clique_import() -> Dict[str, Any]:
    """Try to import ``clique`` and verify it exposes the expected API."""
    info: Dict[str, Any] = {
        "available": False,
        "imported": False,
        "has_assemble": False,
        "module_path": None,
    }

    try:
        import clique  # type: ignore[import-not-found]  # pylint: disable=import-error,import-outside-toplevel

        info["available"] = True
        info["imported"] = True
        info["module_path"] = getattr(clique, "__file__", None)
        if hasattr(clique, "assemble"):
            info["has_assemble"] = True
        else:
            try:
                # Some environments expose assemble as a top-level function.
                from clique import assemble as _assemble  # type: ignore[import-not-found]  # pylint: disable=import-error,import-outside-toplevel

                setattr(clique, "assemble", _assemble)  # type: ignore[attr-defined]
                info["has_assemble"] = True
            except Exception:  # noqa: BLE001
                info["has_assemble"] = False
    except Exception:  # noqa: BLE001
        # Import failed; callers can decide whether to try installation.
        info["available"] = False
        info["imported"] = False

    return info


def _maybe_install_clique() -> bool:
    """Attempt to install ``clique`` via pip, returning True on success."""
    try:
        subprocess.check_call(  # noqa: S603,S607
            [sys.executable, "-m", "pip", "install", "clique"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def check_dependencies(install_missing: bool = False) -> Dict[str, Any]:
    """Check external/runtime dependencies required by the FFmpeg web UI.

    Validates:

    - ``oiiotool`` availability on PATH (for EXR conversion).
    - The Python ``clique`` package used for image sequence detection.

    Args:
        install_missing: If True, attempt to install missing Python packages
            such as ``clique`` using ``pip``. This flag is kept False by
            default for server safety.

    Returns:
        A structured status dictionary with at least:

        - ``ok`` (bool): overall health flag.
        - ``issues`` (list[str]): human-readable issues, if any.
        - ``details`` (dict): per-dependency diagnostic information.
    """
    issues = []

    # --- oiiotool ---
    oiiotool_info = _check_oiiotool()
    if not oiiotool_info["available"]:
        issues.append("oiiotool not found on PATH; EXR conversion is unavailable.")

    # --- clique ---
    clique_info = _ensure_clique_import()

    if (not clique_info["imported"] or not clique_info["has_assemble"]) and install_missing:
        if _maybe_install_clique():
            clique_info = _ensure_clique_import()

    if not clique_info["imported"]:
        issues.append(
            "Python package 'clique' is not importable; sequence detection may be limited."
        )
    elif not clique_info["has_assemble"]:
        issues.append(
            "Imported 'clique' package does not expose 'assemble'; please ensure the "
            "VFX file-sequence library 'clique' is installed."
        )

    status: Dict[str, Any] = {
        "ok": not issues,
        "issues": issues,
        "details": {
            "oiiotool": oiiotool_info,
            "clique": clique_info,
        },
    }
    return status

