"""Tests for the build-staleness check and the encoder readout.

Both exist because a deploy can land correctly on disk and still not be
what a user is running: a long-lived uvicorn keeps the modules it
imported at startup, so synced files change nothing until it restarts.
The app now detects that itself instead of leaving it to be diagnosed by
hand.

Run:
    python -m ffmpeg_web.test_version
"""

from __future__ import annotations

import os
import tempfile
import time

from .core.ffmpeg_handler import describe_codec
try:
    # The dev lineage has no auto-open-browser step, so this helper only
    # exists in the studio one. Skip rather than fail on that difference.
    from .main import detect_server_port
except ImportError:  # pragma: no cover - lineage difference
    detect_server_port = None
from .core.version import build_id_for_paths, staleness


# --- build_id_for_paths() ---------------------------------------------------

def _write(d: str, name: str, text: str) -> str:
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write(text)
    return p


def test_build_id_is_stable_for_unchanged_files() -> None:
    """A rebuild with no edits must not look like a new version."""
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, "a.py", "x = 1")
        assert build_id_for_paths([p]) == build_id_for_paths([p])


def test_build_id_changes_when_content_changes() -> None:
    """The whole point: an edited file must produce a different id."""
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, "a.py", "x = 1")
        before = build_id_for_paths([p])
        time.sleep(0.01)
        _write(d, "a.py", "x = 2")
        assert build_id_for_paths([p]) != before


def test_build_id_ignores_missing_files() -> None:
    """A partially synced tree must not crash the health check."""
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, "a.py", "x = 1")
        build_id_for_paths([p, os.path.join(d, "gone.py")])


def test_build_id_is_order_independent() -> None:
    """Directory walk order must not invent spurious version changes."""
    with tempfile.TemporaryDirectory() as d:
        a = _write(d, "a.py", "x = 1")
        b = _write(d, "b.py", "y = 2")
        assert build_id_for_paths([a, b]) == build_id_for_paths([b, a])


# --- staleness() ------------------------------------------------------------

def test_server_is_fresh_when_ids_match() -> None:
    assert staleness("abc", "abc")["stale"] is False


def test_server_is_stale_when_disk_moved_on() -> None:
    """Files synced under a running process: the exact bug we keep hitting."""
    result = staleness("loaded-at-startup", "newer-on-disk")
    assert result["stale"] is True
    assert "restart" in result["message"].lower()


def test_stale_message_names_the_remedy() -> None:
    """A warning nobody can act on is noise."""
    msg = staleness("old", "new")["message"]
    assert msg and len(msg) > 20


# --- describe_codec() -------------------------------------------------------

def test_describe_h264_h10_reports_level_61() -> None:
    """The UI readout must come from the command builder, not a copy.

    If these ever disagree the readout is worse than useless, so it is
    derived from build_bitrate_codec_params itself.
    """
    info = describe_codec("h264_h10")
    assert info["level"] == "6.1"
    assert info["profile"] == "high10"
    assert info["pix_fmt"] == "yuv420p10le"
    assert info["encoder"] == "libx264"


def test_describe_h264_reports_eight_bit_high() -> None:
    info = describe_codec("h264")
    assert info["profile"] == "high"
    assert info["pix_fmt"] == "yuv420p"
    assert info["level"] == "6.1"


def test_describe_h265_has_no_h264_profile() -> None:
    """H.265 takes a different path; it must not claim an H.264 profile."""
    info = describe_codec("h265")
    assert info["encoder"] == "libx265"
    assert info.get("profile") != "high10"


def test_describe_includes_the_output_transform() -> None:
    assert describe_codec("prores_422")["output_transform"] == "Output - Rec.709"
    assert describe_codec("h264")["output_transform"] == "Output - sRGB"


def test_describe_handles_non_bitrate_codecs() -> None:
    """ProRes and QTRLE have no level; the readout must not invent one."""
    for codec in ("prores_422", "qtrle"):
        info = describe_codec(codec)
        assert "level" not in info, codec
        assert info["encoder"], codec


def test_describe_never_raises_on_unknown_codec() -> None:
    """A readout must not be able to break the page."""
    describe_codec("something_new")



# --- detect_server_port() ---------------------------------------------------

def _with(argv=None, env=None):
    import sys as _sys
    old_argv, old_env = _sys.argv, os.environ.get("FFMPEG_WEB_PORT")
    _sys.argv = argv if argv is not None else ["uvicorn"]
    if env is None:
        os.environ.pop("FFMPEG_WEB_PORT", None)
    else:
        os.environ["FFMPEG_WEB_PORT"] = env
    try:
        return detect_server_port()
    finally:
        _sys.argv = old_argv
        if old_env is None:
            os.environ.pop("FFMPEG_WEB_PORT", None)
        else:
            os.environ["FFMPEG_WEB_PORT"] = old_env


def test_port_comes_from_the_environment() -> None:
    """run.sh knows the port it chose and exports it."""
    assert _with(env="8042") == 8042


def test_port_parsed_from_separate_argv_flag() -> None:
    assert _with(argv=["uvicorn", "app", "--port", "8001"]) == 8001


def test_port_parsed_from_joined_argv_flag() -> None:
    assert _with(argv=["uvicorn", "app", "--port=8003"]) == 8003


def test_port_defaults_to_8000_when_unknown() -> None:
    assert _with() == 8000


def test_nonsense_port_does_not_crash_startup() -> None:
    assert _with(env="not-a-port", argv=["uvicorn", "--port", "abc"]) == 8000


def main() -> None:
    tests = [
        ("build id stable", test_build_id_is_stable_for_unchanged_files),
        ("build id changes on edit", test_build_id_changes_when_content_changes),
        ("build id ignores missing", test_build_id_ignores_missing_files),
        ("build id order independent", test_build_id_is_order_independent),
        ("fresh when ids match", test_server_is_fresh_when_ids_match),
        ("stale when disk newer", test_server_is_stale_when_disk_moved_on),
        ("stale message actionable", test_stale_message_names_the_remedy),
        ("h264_h10 reports 6.1", test_describe_h264_h10_reports_level_61),
        ("h264 reports high/8bit", test_describe_h264_reports_eight_bit_high),
        ("h265 not h264 profile", test_describe_h265_has_no_h264_profile),
        ("describe has transform", test_describe_includes_the_output_transform),
        ("non-bitrate has no level", test_describe_handles_non_bitrate_codecs),
        ("unknown codec safe", test_describe_never_raises_on_unknown_codec),
    ]
    if detect_server_port is not None:
        tests += [
            ("port from env", test_port_comes_from_the_environment),
            ("port from --port N", test_port_parsed_from_separate_argv_flag),
            ("port from --port=N", test_port_parsed_from_joined_argv_flag),
            ("port defaults to 8000", test_port_defaults_to_8000_when_unknown),
            ("bad port is survivable", test_nonsense_port_does_not_crash_startup),
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
