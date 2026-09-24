"""Unit tests for output reformat (resolution) support.

Like ``test_api.py`` these are deliberately framework-free, but unlike
that module they need no running server -- everything here is pure
function testing plus one optional probe test that shells out to
``oiiotool`` when it happens to be available.

Run:
    python -m ffmpeg_web.test_reformat
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .core import reformat
from .core.exr_handler import build_frame_command
from fractions import Fraction

from .core.ffmpeg_handler import build_video_filter_chain
from .core.timing import plan_timing

# 24 frames at 24 fps kept at 1 s: no retime, so the chain is just the
# timing prefix plus the scale under test.
NO_RETIME = plan_timing(24, Fraction(24), Fraction(24), Fraction(1))


# --- even() -----------------------------------------------------------------

def test_even_leaves_even_numbers_alone() -> None:
    """An already-even dimension must pass through untouched."""
    assert reformat.even(1920) == 1920
    assert reformat.even(804) == 804


def test_even_rounds_odd_numbers_up() -> None:
    """Odd dimensions round up so we never shrink below the request."""
    assert reformat.even(1921) == 1922
    assert reformat.even(803) == 804


def test_even_never_returns_less_than_two() -> None:
    """A degenerate dimension still has to be a legal video size."""
    assert reformat.even(1) == 2


# --- resolve_dimensions() ---------------------------------------------------

def test_width_only_derives_height_from_source_aspect() -> None:
    """Typing just a width keeps the source aspect ratio."""
    # 2048x858 is a common 2.39:1 scope plate.
    assert reformat.resolve_dimensions(1920, None, 2048, 858) == (1920, 804)


def test_height_only_derives_width_from_source_aspect() -> None:
    """Typing just a height keeps the source aspect ratio."""
    assert reformat.resolve_dimensions(None, 1080, 1920, 1080) == (1920, 1080)
    assert reformat.resolve_dimensions(None, 540, 1920, 1080) == (960, 540)


def test_both_dimensions_are_used_verbatim() -> None:
    """Supplying both values stretches; we do not letterbox or crop."""
    assert reformat.resolve_dimensions(1920, 1080, 2048, 858) == (1920, 1080)


def test_derived_dimension_is_snapped_to_even() -> None:
    """A derived odd height must be snapped, or yuv420p encoding fails."""
    # 1920 * (1000/1999) = 960.48 -> 960 is even already, so pick a case
    # that genuinely lands on an odd number: 1000x999 at width 1000.
    width, height = reformat.resolve_dimensions(1000, None, 1000, 999)
    assert (width, height) == (1000, 1000), (width, height)


def test_requested_odd_dimensions_are_snapped_to_even() -> None:
    """Odd values typed by the user are snapped rather than rejected."""
    assert reformat.resolve_dimensions(1921, 1081, 2048, 858) == (1922, 1082)


def test_no_dimensions_is_an_error() -> None:
    """Enabling reformat without any dimension is a user error."""
    try:
        reformat.resolve_dimensions(None, None, 2048, 858)
    except reformat.ReformatError as exc:
        assert "width" in str(exc).lower()
    else:
        raise AssertionError("expected ReformatError for no dimensions")


def test_non_positive_dimension_is_an_error() -> None:
    """Zero or negative dimensions are rejected before reaching ffmpeg."""
    for bad in (0, -100):
        try:
            reformat.resolve_dimensions(bad, None, 2048, 858)
        except reformat.ReformatError:
            continue
        raise AssertionError(f"expected ReformatError for width={bad}")


def test_single_dimension_without_source_resolution_is_an_error() -> None:
    """Deriving the other side needs a known source resolution."""
    try:
        reformat.resolve_dimensions(1920, None, None, None)
    except reformat.ReformatError as exc:
        assert "source resolution" in str(exc).lower()
    else:
        raise AssertionError("expected ReformatError without source resolution")


# --- probe parsing ----------------------------------------------------------

def test_parse_oiiotool_info_reads_dimensions() -> None:
    """Parse the padded ``W x  H`` form oiiotool --info actually emits."""
    line = "probe.exr            : 2048 x  858, 3 channel, half openexr"
    assert reformat.parse_oiiotool_info(line) == (2048, 858)


def test_parse_oiiotool_info_prefers_display_window() -> None:
    """A cropped data window must not be reported as the frame size.

    EXRs rendered with a bounding box store only the pixels that hold
    data; the headline ``W x H`` is that data window.  The frame the
    user delivers is the full/display window, printed only by ``-v``.
    """
    text = (
        "Reading dw.1001.exr\n"
        "dw.1001.exr          : 7680 x 1635, 3 channel, half openexr\n"
        "    channel list: R, G, B\n"
        "    pixel data origin: x=0, y=262\n"
        "    full/display size: 7680 x 2160\n"
        "    full/display origin: 0, 0\n"
    )
    assert reformat.parse_oiiotool_info(text) == (7680, 2160)


def test_parse_oiiotool_info_ignores_unrelated_output() -> None:
    """Garbage in must not produce a bogus resolution."""
    assert reformat.parse_oiiotool_info("oiiotool ERROR: could not open") is None


def test_parse_ffmpeg_stderr_reads_dimensions() -> None:
    """Fall back to ffmpeg's stream line when oiiotool is unavailable."""
    text = (
        "Input #0, image2, from 'shot_%04d.png':\n"
        "  Duration: 00:00:04.00, start: 0.000000, bitrate: N/A\n"
        "    Stream #0:0: Video: png, rgb24(pc), 2048x858, 25 fps, 25 tbr\n"
    )
    assert reformat.parse_ffmpeg_stderr(text) == (2048, 858)


def test_parse_ffmpeg_stderr_ignores_non_dimension_numbers() -> None:
    """The frame-rate and bitrate numbers must not be mistaken for a size."""
    text = "  Duration: 00:00:04.00, start: 0.000000, bitrate: 1000 kb/s\n"
    assert reformat.parse_ffmpeg_stderr(text) is None


def test_probe_resolution_reads_a_real_image() -> None:
    """End-to-end probe against a real file, when oiiotool is on PATH."""
    if not shutil.which("oiiotool"):
        print("      (skipped: oiiotool not on PATH)")
        return

    tmp_dir = tempfile.mkdtemp(prefix="ffmpeg_web_probe_")
    try:
        path = os.path.join(tmp_dir, "probe.exr")
        subprocess.run(
            ["oiiotool", "--create", "2048x858", "3", "-d", "half", "-o", path],
            check=True,
            capture_output=True,
        )
        assert reformat.probe_resolution(path) == (2048, 858)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_probe_resolution_uses_display_window_of_cropped_exr() -> None:
    """A real EXR whose data window is smaller than its display window."""
    if not shutil.which("oiiotool"):
        print("      (skipped: oiiotool not on PATH)")
        return

    tmp_dir = tempfile.mkdtemp(prefix="ffmpeg_web_probe_")
    try:
        path = os.path.join(tmp_dir, "cropped.exr")
        subprocess.run(
            ["oiiotool", "--create", "7680x2160", "3",
             "--crop", "7680x1635+0+262", "-d", "half", "-o", path],
            check=True,
            capture_output=True,
        )
        assert reformat.probe_resolution(path) == (7680, 2160)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_probe_resolution_returns_none_for_missing_file() -> None:
    """A missing frame degrades to None rather than raising."""
    assert reformat.probe_resolution("/nonexistent/definitely/not/here.exr") is None


# --- ffmpeg filter chain ----------------------------------------------------

def test_filter_chain_without_reformat_keeps_colour_matrix_only() -> None:
    """With reformat off the scale filter stays a pure colour-matrix tag."""
    chain = build_video_filter_chain(NO_RETIME, None)
    assert chain == (
        "settb=AVTB,setpts=PTS*1/1,fps=24,"
        "scale=in_color_matrix=bt709:out_color_matrix=bt709"
    ), chain


def test_filter_chain_with_reformat_adds_size_and_lanczos() -> None:
    """Reformat extends the existing scale rather than adding a second one."""
    chain = build_video_filter_chain(NO_RETIME, (1920, 804))
    assert chain.count("scale=") == 1, chain
    assert "w=1920:h=804" in chain, chain
    assert "flags=lanczos+accurate_rnd+full_chroma_int" in chain, chain
    assert "in_color_matrix=bt709:out_color_matrix=bt709" in chain, chain


def test_filter_chain_passes_negative_two_through() -> None:
    """-2 is ffmpeg's own keep-aspect-and-round-to-even sentinel."""
    chain = build_video_filter_chain(NO_RETIME, (1920, -2))
    assert "w=1920:h=-2" in chain, chain


# --- oiiotool frame command -------------------------------------------------

def test_exr_command_without_reformat_has_no_resize() -> None:
    """Reformat off must leave the existing EXR command untouched."""
    cmd = build_frame_command(
        "/in/shot.0001.exr", "/out/shot.0001.png", "/cfg.ocio", "ACES - ACEScg", None
    )
    assert "--resize" not in " ".join(cmd), cmd


def test_exr_command_resizes_in_linear_before_colour_convert() -> None:
    """The resize must precede --colorconvert so it happens in linear float."""
    cmd = build_frame_command(
        "/in/shot.0001.exr", "/out/shot.0001.png", "/cfg.ocio", "ACES - ACEScg", (1920, 804)
    )
    resize_flag = "--resize:filter=lanczos3:highlightcomp=1"
    assert resize_flag in cmd, cmd
    assert cmd[cmd.index(resize_flag) + 1] == "1920x804", cmd
    assert cmd.index(resize_flag) < cmd.index("--colorconvert"), cmd


def test_exr_command_resizes_after_channel_selection() -> None:
    """Resizing after --ch means we filter 3 channels, not the full EXR."""
    cmd = build_frame_command(
        "/in/shot.0001.exr", "/out/shot.0001.png", "/cfg.ocio", "ACES - ACEScg", (1920, 804)
    )
    assert cmd.index("--ch") < cmd.index("--resize:filter=lanczos3:highlightcomp=1"), cmd


def main() -> None:
    """Run every test and print a pass/fail line for each."""
    tests = [
        ("even leaves even alone", test_even_leaves_even_numbers_alone),
        ("even rounds odd up", test_even_rounds_odd_numbers_up),
        ("even floors at 2", test_even_never_returns_less_than_two),
        ("width only derives height", test_width_only_derives_height_from_source_aspect),
        ("height only derives width", test_height_only_derives_width_from_source_aspect),
        ("both dimensions verbatim", test_both_dimensions_are_used_verbatim),
        ("derived dimension snapped even", test_derived_dimension_is_snapped_to_even),
        ("requested odd snapped even", test_requested_odd_dimensions_are_snapped_to_even),
        ("no dimensions errors", test_no_dimensions_is_an_error),
        ("non-positive dimension errors", test_non_positive_dimension_is_an_error),
        ("single dimension needs source", test_single_dimension_without_source_resolution_is_an_error),
        ("parse oiiotool --info", test_parse_oiiotool_info_reads_dimensions),
        ("parse oiiotool display window", test_parse_oiiotool_info_prefers_display_window),
        ("parse oiiotool garbage", test_parse_oiiotool_info_ignores_unrelated_output),
        ("parse ffmpeg stderr", test_parse_ffmpeg_stderr_reads_dimensions),
        ("parse ffmpeg non-dimensions", test_parse_ffmpeg_stderr_ignores_non_dimension_numbers),
        ("probe a real image", test_probe_resolution_reads_a_real_image),
        ("probe cropped EXR", test_probe_resolution_uses_display_window_of_cropped_exr),
        ("probe missing file", test_probe_resolution_returns_none_for_missing_file),
        ("filter chain no reformat", test_filter_chain_without_reformat_keeps_colour_matrix_only),
        ("filter chain with reformat", test_filter_chain_with_reformat_adds_size_and_lanczos),
        ("filter chain -2 passthrough", test_filter_chain_passes_negative_two_through),
        ("exr command no resize", test_exr_command_without_reformat_has_no_resize),
        ("exr resize before colorconvert", test_exr_command_resizes_in_linear_before_colour_convert),
        ("exr resize after --ch", test_exr_command_resizes_after_channel_selection),
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
