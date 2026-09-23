"""Frame rates, durations and retime planning, in exact arithmetic.

Everything here uses ``Fraction`` so NTSC rates stay exact (23.976 is
24000/1001, not a float) and a requested duration is never nudged by
float rounding.

A file must read exactly the requested seconds.

At a whole-number rate that is plain whole frames: 10 s at 30 fps is 300
frames = 10.000 s.  (An off-frame duration there, e.g. 10.5 s at 25 fps,
drops the partial last frame and reports ``exact=False``.)

At an NTSC rate a whole number of seconds is never whole frames (15 s at
29.97 = 449.55), and delivery specs still demand exactly 15 s.  So the
duration is filled with whole frames (450) and only the LAST frame is
shortened -- 551/30000 s instead of 1001/30000 -- so the file reads
15.000000 s while staying constant-frame-rate for every other frame.  NTSC
files also carry a SMPTE timecode track (drop-frame at 29.97 and 59.94),
in which 450 frames is exactly 00:00:15;00.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

# The rates the UI offers, as (value sent by the UI, label).  The values
# are what FFmpeg receives, so NTSC stays an exact rational end to end.
# static/index.html must list the same values; test_timing checks it.
FRAME_RATES = (
    ("24000/1001", "23.976"),
    ("24", "24"),
    ("25", "25"),
    ("30000/1001", "29.97"),
    ("30", "30"),
    ("50", "50"),
    ("60000/1001", "59.94"),
    ("60", "60"),
)

_SUPPORTED = tuple(Fraction(value) for value, _label in FRAME_RATES)
_LABELS = {Fraction(value): label for value, label in FRAME_RATES}

# How close a typed decimal must be to snap onto a supported rate.  Wide
# enough for editorial shorthand (23.98 is 0.017% off 23.976), and well
# inside the 0.1% that separates each NTSC rate from its whole neighbour.
_SNAP_TOLERANCE = Fraction(1, 2000)


def parse_fps(value: str) -> Fraction:
    """Parse a frame rate and return it as one of the supported rates.

    Accepts the dropdown values ("24000/1001", "25") and the decimals
    older saved settings hold ("23.976", "23.98", "29.97").  Anything that
    is not one of ``FRAME_RATES`` raises ``ValueError``.
    """
    try:
        rate = Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"Not a frame rate: {value!r}") from None
    for supported in _SUPPORTED:
        if abs(rate - supported) <= supported * _SNAP_TOLERANCE:
            return supported
    labels = ", ".join(label for _value, label in FRAME_RATES)
    raise ValueError(f"Unsupported frame rate {value!r}; choose one of {labels}")


def parse_duration(value: str) -> Fraction:
    """Parse a duration in seconds exactly ("10.01" is 1001/100, not a float)."""
    try:
        seconds = Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"Not a duration: {value!r}") from None
    if seconds <= 0:
        raise ValueError(f"Duration must be positive, got {value!r}")
    return seconds


def fps_label(rate: Fraction) -> str:
    """Human label for a rate: '29.97' rather than '30000/1001'."""
    return _LABELS.get(rate, str(rate))


def fps_arg(rate: Fraction) -> str:
    """The rate as FFmpeg wants it: an exact rational, '25' when whole."""
    return str(rate.numerator) if rate.denominator == 1 else f"{rate.numerator}/{rate.denominator}"


def track_timescale(rate: Fraction) -> int:
    """MP4/MOV ticks per second, chosen so every frame is a whole number of ticks.

    NTSC 24000/1001 gets 24000 (each frame is exactly 1001 ticks).  Whole
    rates get rate * 1000 (e.g. 30000 at 30 fps, 1000 ticks a frame).
    Without this the muxer rounds each frame's length, e.g. 33 ms at 29.97.
    """
    return rate.numerator if rate.denominator != 1 else rate.numerator * 1000


def is_ntsc(rate: Fraction) -> bool:
    return rate.denominator == 1001


def _drop_frame(rate: Fraction) -> bool:
    # SMPTE drop-frame exists for 29.97 and 59.94; 23.976 has none.
    return is_ntsc(rate) and round(rate) in (30, 60)


def frames_to_timecode(frames: int, rate: Fraction) -> str:
    """SMPTE timecode for a frame count ('00:00:15;00' for 450 at 29.97).

    Drop-frame skips frame numbers 0-1 (0-3 at 59.94) at the start of each
    minute except every tenth, keeping timecode in step with the clock.
    """
    nominal = round(rate)
    drop = _drop_frame(rate)
    if drop:
        skip = 2 if nominal == 30 else 4
        per_ten = nominal * 600 - skip * 9
        per_minute = nominal * 60 - skip
        tens, rem = divmod(frames, per_ten)
        frames += skip * 9 * tens
        if rem > skip:
            frames += skip * ((rem - skip) // per_minute)
    ff = frames % nominal
    ss = frames // nominal % 60
    mm = frames // (nominal * 60) % 60
    hh = frames // (nominal * 3600)
    return f"{hh:02d}:{mm:02d}:{ss:02d}{';' if drop else ':'}{ff:02d}"


@dataclass(frozen=True)
class TimingPlan:
    output_fps: Fraction
    requested_duration: Fraction
    output_frames: int
    # frames / fps: what the file will actually measure.
    output_duration: Fraction
    # True when output_duration is exactly the requested duration.
    exact: bool
    # Multiplier on source timestamps: the sequence spans the output frames.
    setpts_ratio: Fraction
    # NTSC only: the shortened length of the final frame, in track ticks,
    # or None when the duration already lands on a frame boundary.
    last_frame_ticks: Optional[int] = None
    # NTSC only: SMPTE start timecode for the file's timecode track.
    timecode: Optional[str] = None


def plan_timing(source_frames: int, source_fps: Fraction, output_fps: Fraction,
                duration: Fraction) -> TimingPlan:
    """Work out frame count, real duration and retime for a conversion.

    Whole rates keep the whole frames that fit in ``duration``.  NTSC rates
    fill ``duration`` with whole frames and shorten the last one so the
    file is exactly ``duration`` long (see the module docstring).  Either
    way the source is spread across the output frames' time slots.
    """
    if source_frames < 1:
        raise ValueError("The sequence has no frames")
    native_duration = Fraction(source_frames) / source_fps
    last_frame_ticks = None
    timecode = None

    if is_ntsc(output_fps):
        output_frames = max(1, math.ceil(duration * output_fps))
        timescale = track_timescale(output_fps)
        ticks_per_frame = Fraction(timescale) / output_fps  # 1001
        full_ticks = output_frames * ticks_per_frame
        wanted_ticks = round(duration * timescale)
        if wanted_ticks < full_ticks:
            last_frame_ticks = int(wanted_ticks - (output_frames - 1) * ticks_per_frame)
        output_duration = Fraction(min(wanted_ticks, full_ticks), timescale)
        timecode = frames_to_timecode(0, output_fps)
    else:
        output_frames = max(1, math.floor(duration * output_fps))
        output_duration = Fraction(output_frames) / output_fps

    return TimingPlan(
        output_fps=output_fps,
        requested_duration=duration,
        output_frames=output_frames,
        output_duration=output_duration,
        exact=output_duration == duration,
        setpts_ratio=(Fraction(output_frames) / output_fps) / native_duration,
        last_frame_ticks=last_frame_ticks,
        timecode=timecode,
    )


def trim_last_frame_bsf(plan: TimingPlan) -> str:
    """Bitstream filter that shortens the final frame to ``last_frame_ticks``.

    Applied in a stream-copy remux (the MP4/MOV track timebase is then
    1/timescale, so the value is in ticks).  ``N`` counts packets in
    decode order, which only equals display order without B-frames -- the
    encode for a trimmed file therefore runs with ``-bf 0``.
    """
    return (f"setts=duration='if(eq(N,{plan.output_frames - 1}),"
            f"{plan.last_frame_ticks},DURATION)'")


def timing_filters(plan: TimingPlan) -> str:
    """The retime + constant-frame-rate part of the ``-vf`` chain.

    ``settb=AVTB`` comes first because ``setpts`` rounds its result to the
    stream's timebase, which for an image sequence is one source frame --
    a retime would otherwise snap every frame to the source grid and judder.
    """
    ratio = plan.setpts_ratio
    return (
        f"settb=AVTB,setpts=PTS*{ratio.numerator}/{ratio.denominator},"
        f"fps={fps_arg(plan.output_fps)}"
    )


def describe(plan: TimingPlan) -> str:
    """One log line saying what the file will measure, and whether that is exact."""
    label = fps_label(plan.output_fps)
    summary = (f"{plan.output_frames} frames @ {label} fps = "
               f"{float(plan.output_duration):.3f} s")
    if plan.exact:
        line = f"Timing: {summary} (exact)"
        if plan.timecode:
            end = frames_to_timecode(plan.output_frames, plan.output_fps)
            line += f", SMPTE timecode {plan.timecode} -> {end}"
        if plan.last_frame_ticks:
            ms = plan.last_frame_ticks * 1000 / track_timescale(plan.output_fps)
            line += f"; last frame shortened to {ms:.1f} ms to land on exactly {float(plan.requested_duration):.3f} s"
        return line
    asked = f"{float(plan.requested_duration):.3f} s"
    return (f"Timing: retimed to exactly {asked}; {summary}. {asked} is not a whole "
            f"number of frames at {label} fps, so the partial last frame is dropped. "
            f"For an exact length, use a duration in whole frames "
            f"(a multiple of 1/{plan.output_fps.numerator} s).")
