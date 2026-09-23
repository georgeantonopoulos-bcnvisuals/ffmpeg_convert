"""Tests for frame-rate parsing and duration/retime planning.

The requirement these guard: a file reads *exactly* the requested
seconds.  At a whole-number output rate that is plain whole frames (10 s
at 30 fps is 300 frames and reads 10.000000 s).  At an NTSC rate a whole
number of seconds is never whole frames (15 s at 29.97 = 449.55), so the
duration is filled with whole frames (450) and only the LAST frame is
shortened (551/30000 s) so the file reads 15.000000 s; the file also
carries a SMPTE timecode track (drop-frame at 29.97/59.94), so 450 frames
is exactly 00:00:15;00.  Never a whole frame lost from the start, which
the old maths did.

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
    frames_to_timecode,
    trim_last_frame_bsf,
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


def test_ntsc_is_exact_by_shortening_only_the_last_frame():
    # The Liveboard case: 450 frames rendered for 15 s, delivered at 29.97.
    # 15 s is 449.55 frames: 450 frames, the last one 551 ticks, not 1001.
    plan = plan_timing(450, Fraction(30), NTSC_29, Fraction(15))
    assert plan.output_frames == 450
    assert plan.last_frame_ticks == 450000 - 449 * 1001 == 551
    assert plan.output_duration == 15
    assert plan.exact
    assert plan.timecode == "00:00:00;00"  # drop-frame

    plan = plan_timing(240, NTSC_23, NTSC_23, Fraction(10))
    assert plan.output_frames == 240  # 239.76 -> 240
    assert plan.last_frame_ticks == 240000 - 239 * 1001 == 761
    assert plan.output_duration == 10 and plan.exact
    assert plan.timecode == "00:00:00:00"  # 23.976 has no drop-frame

    plan = plan_timing(900, NTSC_59, NTSC_59, Fraction(15))
    assert plan.output_frames == 900 and plan.output_duration == 15
    assert plan.timecode == "00:00:00;00"


def test_ntsc_on_a_frame_boundary_needs_no_trim_but_keeps_timecode():
    plan = plan_timing(240, NTSC_23, NTSC_23, Fraction(1001, 100))
    assert plan.output_frames == 240
    assert plan.exact
    assert plan.last_frame_ticks is None
    assert plan.timecode == "00:00:00:00"


def test_whole_rates_get_no_trim_and_no_timecode():
    for rate in (24, 25, 30, 50, 60):
        plan = plan_timing(240, Fraction(24), Fraction(rate), Fraction(10))
        assert plan.last_frame_ticks is None and plan.timecode is None, rate
    # An off-frame duration at a whole rate still drops the partial frame.
    plan = plan_timing(240, Fraction(24), Fraction(25), Fraction(21, 2))
    assert plan.output_frames == 262 and not plan.exact and plan.last_frame_ticks is None


def test_frames_to_timecode():
    assert frames_to_timecode(450, NTSC_29) == "00:00:15;00"
    assert frames_to_timecode(1800, NTSC_29) == "00:01:00;02"  # drop-frame skip
    assert frames_to_timecode(17982, NTSC_29) == "00:10:00;00"
    assert frames_to_timecode(900, NTSC_59) == "00:00:15;00"
    assert frames_to_timecode(240, NTSC_23) == "00:00:10:00"


def test_trim_bsf_targets_the_last_frame_only():
    plan = plan_timing(450, Fraction(30), NTSC_29, Fraction(15))
    assert trim_last_frame_bsf(plan) == "setts=duration='if(eq(N,449),551,DURATION)'"


def test_retime_is_exactly_the_requested_seconds():
    # NTSC fills the duration with whole frames, so 240 frames at 23.976
    # asked for 10 s is a straight 1:1 copy (the last frame is trimmed).
    assert plan_timing(240, NTSC_23, NTSC_23, Fraction(10)).setpts_ratio == 1
    # 450 frames rendered at 30 for 15 s, out at 29.97: one frame per slot.
    assert plan_timing(450, Fraction(30), NTSC_29, Fraction(15)).setpts_ratio == Fraction(1001, 1000)
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

    # NTSC: exact by trimming the last frame, and says so.
    ntsc = describe(plan_timing(450, Fraction(30), NTSC_29, Fraction(15)))
    assert "450 frames" in ntsc and "15.000 s" in ntsc and "exact" in ntsc
    assert "00:00:15;00" in ntsc and "last frame" in ntsc
    assert "25 or 30 fps" not in ntsc

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
GREY_STEP = 5  # grey level = (N mod GREY_CYCLE) * 5, so 0..235
GREY_CYCLE = 48


def _make_sequence(folder: str, frames: int) -> None:
    """Frame N is solid grey (N mod GREY_CYCLE) * GREY_STEP, so any output
    frame can be traced back to its source frame whatever the codec does."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"nullsrc=s=64x36:r=24,format=gray,geq=lum='mod(N,{GREY_CYCLE})*{GREY_STEP}'",
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


def _timecode(path: str) -> str:
    """The SMPTE start timecode tag, or '' when the file has none."""
    tags = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream_tags=timecode",
         "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout.split()
    return tags[0] if tags else ""


def _mediainfo(path: str, section: str, fields: str) -> str:
    return subprocess.run(["mediainfo", f"--Inform={section};{fields}", path],
                          capture_output=True, text=True, check=True).stdout.strip()


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


def test_e2e_every_output_rate_reads_exactly_the_requested_seconds():
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
            rate = parse_fps(value)
            plan = plan_timing(48, Fraction(24), rate, Fraction(2))
            assert frames == plan.output_frames, (label, frames, plan.output_frames)
            assert duration == "2.000000", (label, duration)
            if rate.denominator == 1:
                assert _timecode(path) == "", (label, _timecode(path))
            else:
                assert _timecode(path) == plan.timecode, (label, _timecode(path))


def test_e2e_blank_audio_does_not_lengthen_an_exact_file():
    if not HAVE_FFMPEG:
        print("  (skipped: ffmpeg not on PATH)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        _make_sequence(src, 48)
        for value in ("25", "30", "30000/1001", "24000/1001"):
            path = _encode(src, tmp, f"audio_{value.replace('/', '_')}.mp4", "24", value, "2", 48,
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


def test_e2e_ntsc_round_seconds_keeps_every_frame():
    # 48 frames at 23.976 asked for exactly 2 s: all 48 frames, in order,
    # the last one shortened.  The old maths dropped frame 0 here.
    if not HAVE_FFMPEG:
        print("  (skipped: ffmpeg not on PATH)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        _make_sequence(src, 48)
        path = _encode(src, tmp, "ntsc.mov", "24000/1001", "24000/1001", "2", 48,
                       codec="qtrle")
        assert _source_frames(path) == list(range(48)), _source_frames(path)
        assert _probe(path) == ("2.000000", 48)


def test_e2e_liveboard_15s_at_2997_from_a_30fps_render():
    # The delivery that motivated this: 450 frames rendered for 15 s at 30,
    # spec'd as 15 s at 29.97.  Must read 15.000 s everywhere, keep all 450
    # frames once each in order, and carry SMPTE timecode 00:00:00;00.
    if not HAVE_FFMPEG:
        print("  (skipped: ffmpeg not on PATH)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        _make_sequence(src, 450)
        for codec, name in (("h264", "live.mp4"), ("h265", "live_hevc.mp4"),
                            ("prores", "live_prores.mov")):
            path = _encode(src, tmp, name, "30", "30000/1001", "15", 450, codec=codec)
            assert _probe(path) == ("15.000000", 450), (codec, _probe(path))
            expected = [n % GREY_CYCLE for n in range(450)]
            assert _source_frames(path) == expected, codec
            assert _timecode(path) == "00:00:00;00", (codec, _timecode(path))
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=r_frame_rate,color_transfer,color_primaries", "-of", "default=nw=1",
                 path], capture_output=True, text=True, check=True).stdout
            tags = dict(line.split("=", 1) for line in out.split())
            assert tags["r_frame_rate"] == "30000/1001", (codec, tags)
            # The trim is a stream-copy remux; it must not lose colour tags.
            # (ProRes from this app carries none even untrimmed -- a
            # separate, older gap -- so there is nothing to preserve.)
            if codec != "prores":
                assert tags["color_transfer"] == "bt709", (codec, tags)
                assert tags["color_primaries"] == "bt709", (codec, tags)
            if shutil.which("mediainfo"):
                general = _mediainfo(path, "General", "%Duration/String3%")
                video = _mediainfo(path, "Video", "%FrameRate_Mode% %FrameRate% %FrameCount%")
                assert general == "00:00:15.000", (codec, general)
                assert video == "CFR 29.970 450", (codec, video)
        leftovers = [f for f in os.listdir(tmp) if "untrimmed" in f]
        assert not leftovers, leftovers


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
