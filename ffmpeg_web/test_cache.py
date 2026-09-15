"""Tests that a deploy actually reaches the browser.

Framework-free like the other suites. Unlike ``test_api.py`` this one
starts its own server on a free port, so it needs no running instance.

These exist because a deploy that lands correctly on disk can still be
invisible to users: without ``Cache-Control`` a browser applies heuristic
freshness (roughly 10% of the document's age), so a months-old page can
be served from cache for weeks after it changed on the share.

Run:
    python -m ffmpeg_web.test_cache
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """Run the real app so the assertions see real response headers."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "Server":
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "ffmpeg_web.main:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                urllib.request.urlopen(self.url("/"), timeout=1).read()
                return self
            except Exception:  # noqa: BLE001 - server not up yet
                if self.proc.poll() is not None:
                    raise RuntimeError("server exited during startup")
                time.sleep(0.25)
        raise RuntimeError("server did not start in time")

    def __exit__(self, *exc: object) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str):
        return urllib.request.urlopen(self.url(path), timeout=10)


def test_index_document_must_be_revalidated() -> None:
    """The page holding the codec dropdown must not be heuristically cached.

    ``index.html`` is served from ``/`` by FileResponse, which the
    ``/static`` middleware never matched. A browser that loaded the old
    page keeps showing an outdated codec list long after the deploy.
    """
    with Server() as s:
        cc = s.get("/").headers.get("Cache-Control")
    assert cc is not None, "GET / sent no Cache-Control: browsers will cache it heuristically"
    assert "no-cache" in cc, f"GET / Cache-Control was {cc!r}"


def test_static_assets_must_be_revalidated() -> None:
    """The existing /static guarantee must not regress."""
    with Server() as s:
        cc = s.get("/static/js/ui.js").headers.get("Cache-Control")
    assert cc is not None and "no-cache" in cc, f"ui.js Cache-Control was {cc!r}"


def test_index_still_carries_a_validator() -> None:
    """no-cache means revalidate, not re-download -- keep the ETag.

    Without a validator every reload would ship the whole document
    instead of a 304.
    """
    with Server() as s:
        headers = s.get("/").headers
    assert headers.get("ETag") or headers.get("Last-Modified"), \
        "no validator on /, so revalidation cannot return 304"


def test_deployed_index_offers_the_ten_bit_codec() -> None:
    """Guard the deploy itself, not just the caching policy."""
    with Server() as s:
        body = s.get("/").read().decode("utf-8", "replace")
    assert 'value="h264_h10"' in body, "the served page is missing the High 10 option"


def main() -> None:
    tests = [
        ("index revalidates", test_index_document_must_be_revalidated),
        ("static revalidates", test_static_assets_must_be_revalidated),
        ("index keeps validator", test_index_still_carries_a_validator),
        ("served page has h264_h10", test_deployed_index_offers_the_ten_bit_codec),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"[OK]   {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[FAIL] {name}: {exc}")

    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
