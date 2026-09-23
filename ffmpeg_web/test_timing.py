"""Tests for frame-rate parsing and duration/retime planning.

The requirement these guard: the retime is always to *exactly* the
requested seconds.  At a whole-number output rate the file is exact too
(10 s at 30 fps is 300 frames and reads 10.000000 s).  At an NTSC rate
the content still spans exactly 10 s, and the partial frame that does not
fit is dropped (299 frames = 9.977 s at 29.97) -- but never a whole frame
from the start, which the old maths lost.

Framework-free like ``test_reformat.py``.  The end-to-end tests at the
bottom encode real files through ``FFmpegHandler.run_ffmpeg`` and are
skipped when ``ffmpeg``/``ffprobe`` are not on PATH.

Run:
    python -m ffmpeg_web.test_timing
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction

from .core.ffmpeg_handler import FFmpegHandler, FFmpegJobConfig
from .core.timing import (
    FRAME_RATES,
    describe,
    fps_arg,
    parse_duration,
    parse_fps,
    plan_timing,
    timing_filters,
    track_timescale,
)

NTSC_23 = Fraction(24000, 1001)
NTSC_29 = Fraction(30000, 1001)
NTSC_59 = Fraction(60000, 1001)

EXPECTED_RATES = ["24000/1001", "24", "25", "30000/1001", "30", "50", "60000/1001", "60"]


# --- parse_fps ---------------------------------------------------------------

def test_frame_rates_are_the_dropdown_set():
    assert [value for value, _label in FRAME_RATES] == EXPECTED_RATES


def test_parse_fps_accepts_every_dropdown_value_exactly():
    for value, _label in FRAME_RATES:
        num, _, den = value.partition("/")
        assert parse_fps(value) == Fraction(int(num), int(den or 1)), value


def test_parse_fps_maps_legacy_decimals_to_exact_ntsc():
    # Older saved settings hold typed decimals; "23.98" is the common
    # editorial shorthand that the old +/-0.001 match rejected.
    assert parse_fps("23.976") == NTSC_23
    assert parse_fps("23.98") == NTSC_23
    assert parse_fps("29.97") == NTSC_29
    assert parse_fps("59.94") == NTSC_59
    assert parse_fps(" 25 ") == 25
    assert parse_fps("30.0") == 30


def test_parse_fps_rejects_unsupported_rates():
    for bad in ["", "abc", "0", "-24", "12", "48", "1/0"]:
        try:
            parse_fps(bad)
        except ValueError:
            continue
        raise AssertionError(f"parse_fps({bad!r}) should have raised")


# --- parse_duration ------------------------------------------------------------

def test_parse_duration_is_exact_decimal():
    assert parse_duration("10") == 10
    assert parse_duration("10.01") == Fraction(1001, 100)
    assert parse_duration("0.1") == Fraction(1, 10)


def test_parse_duration_rejects_non_positive():
    for bad in ["", "x", "0", "-5", "nan", "inf"]:
        try:
            parse_duration(bad)
        except ValueError:
            continue
        raise AssertionError(f"parse_duration({bad!r}) should have raised")


# --- plan_timing ---------------------------------------------------------------

def test_whole_rates_hit_the_requested_duration_exactly():
    for rate in (24, 25, 30, 50, 60):
        for seconds in ("5", "6", "10", "15", "20", "30"):
            plan = plan_timing(240, Fraction(24), Fraction(rate), parse_duration(seconds))
            assert plan.exact, (rate, seconds)
            assert plan.output_duration == parse_duration(seconds), (rate, seconds)
            assert plan.output_frames == parse_duration(seconds) * rate, (rate, seconds)


def test_ntsc_drops_the_partial_last_frame_and_says_so():
    # 10 s at 29.97 is 299.7 frames: keep 299, drop the 0.7.
    plan = plan_timing(300, NTSC_29, NTSC_29, Fraction(10))
    assert plan.output_frames == 299
    assert plan.output_duration == Fraction(299 * 1001, 30000)  # 9.977 s
    assert not plan.exact

    plan = plan_timing(240, NTSC_23, NTSC_23, Fraction(10))
    assert plan.output_frames == 239  # 239.76 frames


def test_ntsc_exact_when_duration_is_whole_frames():
    plan = plan_timing(240, NTSC_23, NTSC_23, Fraction(1001, 100))
    assert plan.output_frames == 240
    assert plan.exact


def test_retime_is_exactly_the_requested_seconds():
    # 240 frames at 23.976 last 10.01 s; asking for 10 s squeezes by 1000/1001.
    assert plan_timing(240, NTSC_23, NTSC_23, Fraction(10)).setpts_ratio == Fraction(1000, 1001)
    # Native length at the same rate: no retime at all.
    assert plan_timing(240, Fraction(24), Fraction(24), Fraction(10)).setpts_ratio == 1
    assert plan_timing(240, NTSC_23, NTSC_23, Fraction(1001, 100)).setpts_ratio == 1
    # 240 frames at 24 fps (10 s) played out over 15 s.
    assert plan_timing(240, Fraction(24), Fraction(30), Fraction(15)).setpts_ratio == Fraction(3, 2)


def test_plan_rejects_empty_sequence():
    try:
        plan_timing(0, Fraction(24), Fraction(24), Fraction(10))
    except ValueError:
        return
    raise AssertionError("plan_timing with no source frames should raise")


def test_describe_gives_advice_that_fits_the_cause():
    exact = describe(plan_timing(240, Fraction(24), Fraction(30), Fraction(10)))
    assert "300 frames" in exact and "10.000 s" in exact and "exact" in exact

    # NTSC: no duration in whole seconds can be exact, so suggest a whole rate.
    ntsc = describe(plan_timing(240, Fraction(24), NTSC_29, Fraction(10)))
    assert "299 frames" in ntsc and "9.977 s" in ntsc
    assert "25 or 30 fps" in ntsc and "exactly 10.000 s" in ntsc

    # Whole rate, off-frame duration: already on 25 fps, so the advice is
    # about the duration, not the rate.
    off = describe(plan_timing(240, Fraction(24), Fraction(25), Fraction(21, 2)))
    assert "262 frames" in off and "25 or 30 fps" not in off
    assert "1/25 s" in off and "10.5.000" not in off


# --- ffmpeg argument helpers ------------------------------------------------------

def test_fps_arg_is_an_exact_rational():
    assert fps_arg(NTSC_23) == "24000/1001"
    assert fps_arg(Fraction(25)) == "25"


def test_track_timescale_gives_every_frame_a_whole_tick_count():
    for value, _label in FRAME_RATES:
        rate = parse_fps(value)
        ticks_per_frame = Fraction(track_timescale(rate)) / rate
        assert ticks_per_frame.denominator == 1, value
    assert track_timescale(NTSC_23) == 24000
    assert track_timescale(Fraction(30)) == 30000


def test_timing_filters_use_exact_integer_ratios():
    plan = plan_timing(240, Fraction(24), NTSC_29, Fraction(15))
    ratio = plan.setpts_ratio
    # settb first: setpts rounds to the stream's timebase, which for an
    # image sequence is one source frame -- far too coarse for a retime.
    assert timing_filters(plan) == (
        f"settb=AVTB,setpts=PTS*{ratio.numerator}/{ratio.denominator},fps=30000/1001"
    )


# --- UI stays in step with the backend ------------------------------------------

def test_both_dropdowns_offer_exactly_the_backend_rates():
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path, encoding="utf-8") as fh:
        html = fh.read()
    for select_id in ("source_frame_rate", "frame_rate"):
        match = re.search(rf'<select id="{select_id}"[^>]*>(.*?)</select>', html, re.S)
        assert match, f"#{select_id} should be a <select>"
        values = re.findall(r'<option value="([^"]+)"', match.group(1))
        assert values == EXPECTED_RATES, (select_id, values)


# --- End to end: real encodes through run_ffmpeg ----------------------------------

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
GREY_STEP = 5  # 48 frames -> grey 0..235


def _make_sequence(folder: str, frames: int) -> None:
    """Frame N is solid grey level N * GREY_STEP, so any output frame can be
    traced back to its source frame whatever the codec does to the pixels."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"nullsrc=s=64x36:r=24,format=gray,geq=lum='N*{GREY_STEP}'",
         "-frames:v", str(frames), "-start_number", "1001",
         os.path.join(folder, "src.%04d.png")],
        check=True,
    )


def _encode(src: str, out_dir: str, name: str, source_fps: str, output_fps: str,
            seconds: str, frames: int, codec: str = "h264", audio: str = "No Audio") -> str:
    messages = []
    config = FFmpegJobConfig(
        input_folder=src, filename_pattern="src.%04d.png",
        output_folder=out_dir, output_filename=name,
        frame_rate=output_fps, source_frame_rate=source_fps, desired_duration=seconds,
        codec=codec, mp4_bitrate="2", prores_profile="3", prores_qscale="9",
        audio_option=audio, start_frame=1001, end_frame=1000 + frames,
    )
    FFmpegHandler(lambda kind, text: messages.append((kind, text))).run_ffmpeg(config)
    kinds = [kind for kind, _ in messages]
    assert "success" in kinds, [t for k, t in messages if k == "error"] or messages[-3:]
    return os.path.join(out_dir, name)


def _probe(path: str) -> tuple[str, int]:
    """Container duration as ffprobe prints it, and the decoded frame count."""
    duration = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout.strip()
    frames = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return duration, int(frames)


def _source_frames(path: str) -> list:
    """Which source frame each output frame shows, from its grey level."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=1:1:flags=area,format=gray",
         "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return [round(level / GREY_STEP) for level in out]


def test_e2e_every_output_rate_gives_the_planned_duration():
    if not HAVE_FFMPEG:
        print("  (skipped: ffmpeg not on PATH)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        _make_sequence(src, 48)
        for value, label in FRAME_RATES:
            path = _encode(src, tmp, f"out_{label}.mp4", "24", value, "2", 48)
            duration, frames = _probe(path)
            plan = plan_timing(48, Fraction(24), parse_fps(value), Fraction(2))
            assert frames == plan.output_frames, (label, frames, plan.output_frames)
            if plan.exact:
                assert duration == "2.000000", (label, duration)
            else:
                # The MP4 movie header counts whole milliseconds, so an NTSC
                # length like 1.960292 s is reported rounded up to 1.961.
                assert abs(float(duration) - float(plan.output_duration)) <= 0.001, (label, duration)


def test_e2e_blank_audio_does_not_lengthen_an_exact_file():
    if not HAVE_FFMPEG:
        print("  (skipped: ffmpeg not on PATH)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        _make_sequence(src, 48)
        for value in ("25", "30"):
            path = _encode(src, tmp, f"audio_{value}.mp4", "24", value, "2", 48,
                           audio="Blank Audio Track")
            duration, _ = _probe(path)
            assert duration == "2.000000", (value, duration)


def test_e2e_native_length_keeps_every_source_frame_in_order():
    # Same rate in and out at the sequence's own length: a straight copy.
    if not HAVE_FFMPEG:
        print("  (skipped: ffmpeg not on PATH)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        _make_sequence(src, 48)
        for value, seconds in (("24000/1001", "2.002"), ("24", "2"), ("30000/1001", "1.6016")):
            path = _encode(src, tmp, f"copy_{value.replace('/', '_')}.mov",
                           value, value, seconds, 48, codec="qtrle")
            assert _source_frames(path) == list(range(48)), (value, _source_frames(path))


def test_e2e_ntsc_round_seconds_keeps_the_first_frame():
    # 48 frames at 23.976 (2.002 s) retimed to exactly 2 s is 47.95 frames:
    # keep 47, drop the partial one at the END.  The old maths dropped
    # frame 0 instead.
    if not HAVE_FFMPEG:
        print("  (skipped: ffmpeg not on PATH)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        _make_sequence(src, 48)
        path = _encode(src, tmp, "ntsc.mov", "24000/1001", "24000/1001", "2", 48,
                       codec="qtrle")
        assert _source_frames(path) == list(range(47)), _source_frames(path)


def test_e2e_prores_mov_is_exact_at_whole_rates():
    if not HAVE_FFMPEG:
        print("  (skipped: ffmpeg not on PATH)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        _make_sequence(src, 48)
        path = _encode(src, tmp, "prores.mov", "24", "25", "2", 48, codec="prores")
        assert _probe(path) == ("2.000000", 50)


def main() -> None:
    tests = [(name, fn) for name, fn in globals().items()
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001 - report every failure
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
