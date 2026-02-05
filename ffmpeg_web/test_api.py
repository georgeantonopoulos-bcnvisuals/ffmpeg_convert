"""Minimal API smoke tests for the FFmpeg Web UI.

This script is intentionally lightweight and does not rely on a test
framework. It assumes the FastAPI app is already running locally,
typically via uvicorn, for example:

    uvicorn ffmpeg_web.main:app --reload

Run:
    python -m ffmpeg_web.test_api
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import urllib.error
import urllib.request


BASE_URL = os.environ.get("FFMPEG_WEB_BASE_URL", "http://127.0.0.1:8000")


def _http_get(path: str) -> Dict[str, Any]:
    """Perform a basic HTTP GET and parse JSON."""
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=5) as resp:  # noqa: S310
        data = resp.read().decode("utf-8")
        return json.loads(data)


def _http_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Perform a basic HTTP POST with a JSON body and parse JSON."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        data = resp.read().decode("utf-8")
        return json.loads(data)


def test_settings_roundtrip() -> None:
    """Verify that settings endpoints respond and roughly round-trip."""
    original = _http_get("/api/settings")
    assert isinstance(original, dict), "Settings response must be a JSON object"

    updated = {**original, "frame_rate": "42"}
    _http_post("/api/settings", updated)

    reloaded = _http_get("/api/settings")
    assert reloaded.get("frame_rate") == "42", "Updated frame_rate did not persist"


def test_browse_root() -> None:
    """Check that the browse endpoint returns a reasonable structure."""
    data = _http_get("/api/browse")
    assert "current_path" in data and "items" in data, "Browse response missing keys"


def test_deps_endpoint() -> None:
    """Ensure the dependency status endpoint returns a well-formed payload."""
    status = _http_get("/api/deps")
    assert "ok" in status and "issues" in status and "details" in status


def main() -> None:
    """Run all simple tests and print results."""
    tests = [
        ("settings roundtrip", test_settings_roundtrip),
        ("browse root", test_browse_root),
        ("deps endpoint", test_deps_endpoint),
    ]
    for name, fn in tests:
        try:
            fn()
            print(f"[OK] {name}")
        except (AssertionError, urllib.error.URLError, TimeoutError) as exc:
            print(f"[FAIL] {name}: {exc}")


if __name__ == "__main__":
    main()

