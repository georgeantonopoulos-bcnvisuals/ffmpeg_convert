#!/usr/bin/env python3
"""Launcher for the FastAPI-based FFmpeg Web UI inside a Rez environment.

This script mirrors the behavior of ``launch_ffmpeg_ui.py`` for the Tkinter
application but targets the web stack defined in ``ffmpeg_web/``. It:

- Spawns a Rez environment with the required runtime packages.
- Runs ``uvicorn ffmpeg_web.main:app`` bound to the configured host/port.
- Prints the exact command being executed so that it is easy to debug or
  adjust the Rez package list if needed.

Environment variables:
    FFMPEG_WEB_HOST: Optional override for the bind host (default: "0.0.0.0").
    FFMPEG_WEB_PORT: Optional override for the port (default: "8000").
"""

import os
import subprocess
import sys
import webbrowser
from typing import List


def _build_rez_command(host: str, port: str) -> List[str]:
    """Construct the Rez command used to launch the web UI.

    Notes:
        - Rez is used here only for DCC / system-level deps (OIIO, OCIO,
          Tk, clique, etc.).
        - FastAPI / Uvicorn / websockets / python-multipart are expected
          to be installed in the Python environment running this script
          (e.g. via pip in your user or virtualenv).
    """
    rez_packages = [
        "openimageio",
        "opencolorio",
        "tkinter_libs",
        "clique",
    ]

    return [
        "rez",
        "env",
        *rez_packages,
        "--",
        sys.executable,
        "-m",
        "uvicorn",
        "ffmpeg_web.main:app",
        "--host",
        host,
        "--port",
        port,
    ]


def launch_web_ui() -> None:
    """Launch the FastAPI FFmpeg Web UI within a Rez environment."""
    host = os.environ.get("FFMPEG_WEB_HOST", "0.0.0.0")
    port = os.environ.get("FFMPEG_WEB_PORT", "8000")

    cmd = _build_rez_command(host, port)
    printable_cmd = " ".join(cmd)
    print(f"Running FFmpeg Web UI via Rez:\n  {printable_cmd}\n")

    try:
        process = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        print("FFmpeg Web UI server started with PID:", process.pid)

        # Best-effort attempt to open the browser pointing at localhost.
        try:
            browser_url = f"http://127.0.0.1:{port}"
            print(f"Opening browser at {browser_url}")
            webbrowser.open(browser_url, new=2, autoraise=True)
        except Exception as browser_exc:  # noqa: BLE001
            print(f"Warning: failed to open browser automatically: {browser_exc}")

        process.wait()
        print(f"\nServer exited with code {process.returncode}")
        sys.exit(process.returncode)

    except KeyboardInterrupt:
        print("\nWeb UI launch interrupted by user.", file=sys.stderr)
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"Unexpected error while launching web UI: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    launch_web_ui()

