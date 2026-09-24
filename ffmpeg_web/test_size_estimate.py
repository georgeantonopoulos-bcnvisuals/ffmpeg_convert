"""Tests for the output file-size estimate (``core/size_estimate.py``).

The bitrate-codec maths is pinned to sizes measured from real encodes
made by ``FFmpegHandler.run_ffmpeg`` with the bundled ffmpeg (Sep 2026):

    H.264 30 Mb/s, 25 fps, 250 frames, no audio      37,130,401 bytes
    H.264 10 Mb/s, 25 fps, 250 frames, no audio      12,380,185 bytes
    H.264 30 Mb/s, 15 s at 29.97 (450 fr, trimmed)   55,936,254 bytes

libx264 in ``nal-hrd=cbr`` mode pads with filler, so those sizes do not
depend on the picture: flat grey and full-frame noise measured the same.

Framework-free like ``test_timing.py``.  The end-to-end test encodes
real files and is skipped when ``ffmpeg``/``ffprobe`` are not on PATH.

Run:
    python -m ffmpeg_web.test_size_estimate
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from fractions import Fraction

from .core import size_estimate, timing
from .core.ffmpeg_handler import FFmpegHandler, FFmpegJobConfig

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _plan(frames, fps, seconds, source_fps=None):
    fps = timing.parse_fps(fps)
    return timing.plan_timing(
        frames, timing.parse_fps(source_fps) if source_fps else fps,
        fps, Fraction(seconds),
    )


def _close(estimate, measured, tolerance=Fraction(1, 2000)):
    """Within 0.05% -- far tighter than any encoder's rate control."""
    error = abs(Fraction(estimate - measured, measured))
    assert error <= tolerance, f"{estimate:,} vs measured {measured:,} ({float(error):.4%})"


# --- bitrate codecs: closed-form maths ----------------------------------------

def test_x264_matches_measured_encode_at_30mbps():
    est = size_estimate.estimate_bitrate_codec(
        "h264", "30", _plan(250, "25", "10"), "No Audio", {})
    assert est["kind"] == "exact"
    _close(est["bytes"], 37_130_401)


def test_x264_matches_measured_encode_at_10mbps():
    est = size_estimate.estimate_bitrate_codec(
        "h264", "10", _plan(250, "25", "10"), "No Audio", {})
    _close(est["bytes"], 12_380_185)


def test_x264_ntsc_counts_the_encoded_frames_not_the_trimmed_seconds():
    """15 s at 29.97 encodes 450 whole frames (15.015 s) before the trim
    remux shortens the last one; the trim is a stream copy, so the bytes
    are those of 450 full frames."""
    est = size_estimate.estimate_bitrate_codec(
        "h264", "30", _plan(250, "30000/1001", "15", source_fps="25"),
        "No Audio", {})
    _close(est["bytes"], 55_936_254)


def test_x264_vbv_start_is_ten_percent_of_one_buffer():
    est = size_estimate.estimate_bitrate_codec(
        "h264", "30", _plan(250, "25", "10"), "No Audio", {})
    # 30 Mb/s x 10 s / 8, less 10% of a one-second 30 Mb buffer.
    assert est["breakdown"]["video"] == 37_500_000 - 375_000


def test_high10_uses_the_x264_model():
    est = size_estimate.estimate_bitrate_codec(
        "h264_h10", "30", _plan(250, "25", "10"), "No Audio", {})
    assert est["kind"] == "exact"


def test_x265_is_only_an_upper_bound():
    """libx265 ignores -minrate: flat grey measured 44 KB against 37.5 MB."""
    est = size_estimate.estimate_bitrate_codec(
        "h265", "30", _plan(250, "25", "10"), "No Audio", {})
    assert est["kind"] == "upper_bound"
    assert est["breakdown"]["video"] == 37_500_000


def test_nvenc_is_only_an_upper_bound():
    est = size_estimate.estimate_bitrate_codec(
        "h264", "30", _plan(250, "25", "10"), "No Audio", {"nvenc_h264": True})
    assert est["kind"] == "upper_bound"


def test_blank_audio_adds_silent_aac_packets():
    """ffmpeg's AAC encodes silence as 6-byte packets, far below 128k;
    10 s at 48 kHz is 470 packets (469 frames of 1024 samples + priming)."""
    quiet = size_estimate.estimate_bitrate_codec(
        "h264", "30", _plan(250, "25", "10"), "No Audio", {})
    audio = size_estimate.estimate_bitrate_codec(
        "h264", "30", _plan(250, "25", "10"), "Blank Audio Track", {})
    assert quiet["breakdown"]["audio"] == 0
    assert audio["breakdown"]["audio"] == 470 * 16
    # Measured with blank audio: 37,138,008 bytes.
    _close(audio["bytes"], 37_138_008)


# --- sampled codecs: window selection and extrapolation ------------------------

def test_windows_are_spread_across_the_whole_sequence():
    windows = size_estimate.sample_windows(100, 100, count=4, frames_per_window=1)
    assert [w.first_source for w in windows] == [12, 37, 62, 87]
    assert all(w.source_count == 1 and w.output_frames == 1 for w in windows)


def test_windows_follow_the_retime():
    """Stretching 50 source frames over 100 output frames: an output window
    of 12 frames needs 6 source frames, plus one for the fps filter."""
    windows = size_estimate.sample_windows(50, 100, count=3, frames_per_window=12)
    assert all(w.output_frames == 12 and w.source_count == 7 for w in windows)
    assert all(w.first_source + w.source_count <= 50 for w in windows)


def test_windows_never_exceed_a_short_sequence():
    windows = size_estimate.sample_windows(3, 3, count=8, frames_per_window=1)
    assert [w.first_source for w in windows] == [0, 1, 2]


def test_extrapolation_scales_the_mean_and_reports_the_spread():
    est = size_estimate.extrapolate(
        [(1000, 1), (3000, 1)], _plan(100, "25", "4"), "No Audio")
    assert est["kind"] == "measured"
    assert est["breakdown"]["video"] == 200_000  # mean 2000 B x 100 frames
    # Successive-difference SE: sqrt(2000^2 / (2*2*1)) = 1000 B per frame;
    # the interval is two of them either side of the mean, floored at 0.
    overhead = est["bytes"] - est["breakdown"]["video"]
    assert est["low"] == overhead
    assert est["high"] == overhead + 400_000


def test_extrapolation_interval_tightens_when_windows_agree():
    est = size_estimate.extrapolate(
        [(2000, 1), (2010, 1), (1990, 1), (2000, 1)], _plan(100, "25", "4"), "No Audio")
    assert est["high"] - est["low"] < 0.02 * est["breakdown"]["video"]


# --- end to end: a sampled ProRes estimate against the real encode ------------

def _make_mixed_sequence(folder, frames):
    """First 40% flat grey, the rest noise: a sequence whose frames cost
    very different amounts, so sampling has something to get wrong."""
    flat = int(frames * 0.4)
    for src, count, start in (
        ("color=c=gray:size=640x360:rate=25", flat, 1),
        ("testsrc2=size=640x360:rate=25,noise=alls=30:allf=t", frames - flat, flat + 1),
    ):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src,
             "-frames:v", str(count), "-start_number", str(start),
             os.path.join(folder, "f.%04d.png")],
            check=True,
        )


def test_e2e_sampled_prores_brackets_the_real_file():
    if not HAVE_FFMPEG:
        print("  (skipped: ffmpeg not on PATH)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        _make_mixed_sequence(src, 50)
        config = FFmpegJobConfig(
            input_folder=src, filename_pattern="f.%04d.png",
            output_folder=tmp, output_filename="real.mov",
            frame_rate="25", source_frame_rate="25", desired_duration="2",
            codec="prores_422", prores_profile="2", prores_qscale="9",
            start_frame=1, end_frame=50,
        )
        errors = []
        FFmpegHandler(lambda kind, msg: errors.append(msg) if kind == "error" else None
                      ).run_ffmpeg(config)
        assert not errors, errors
        real = os.path.getsize(os.path.join(tmp, "real.mov"))

        est = size_estimate.estimate(config, sample=True)
        assert est["kind"] == "measured", est
        assert est["low"] <= real <= est["high"], (est, real)
        _close(est["bytes"], real, tolerance=Fraction(1, 10))


def test_prores_without_sampling_asks_for_it():
    config = FFmpegJobConfig(
        input_folder="/nonexistent", filename_pattern="f.%04d.png",
        output_folder="/tmp", output_filename="x.mov",
        frame_rate="25", source_frame_rate="25", desired_duration="2",
        codec="prores_422", prores_profile="2", prores_qscale="9",
        start_frame=1, end_frame=50,
    )
    est = size_estimate.estimate(config, sample=False)
    assert est["kind"] == "needs_sample"
    assert est["frames"] == 50


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
