"""Frame rates, durations and retime planning, in exact arithmetic.

Everything here uses ``Fraction`` so NTSC rates stay exact (23.976 is
24000/1001, not a float) and a requested duration is never nudged by
float rounding.

The retime is always to exactly the requested seconds: the sequence's
content is stretched or squeezed to span precisely that long.

The one thing exact arithmetic cannot change: a file holds whole frames,
so its duration is always ``frames / fps``.  At a whole-number rate any
duration on a frame boundary is hit exactly (10 s at 30 fps = 300
frames = 10.000 s).  At an NTSC rate a whole number of seconds is never a
whole number of frames (10 s at 29.97 = 299.7 frames), so the partial
last frame is dropped (299 frames = 9.977 s) and the plan reports
``exact=False``.  Out-of-home players that demand an exact duration need
a whole rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

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


@dataclass(frozen=True)
class TimingPlan:
    output_fps: Fraction
    requested_duration: Fraction
    output_frames: int
    # frames / fps: what the file will actually measure.
    output_duration: Fraction
    # True when output_duration is exactly the requested duration.
    exact: bool
    # Multiplier on source timestamps so the sequence spans exactly the
    # requested duration.
    setpts_ratio: Fraction


def plan_timing(source_frames: int, source_fps: Fraction, output_fps: Fraction,
                duration: Fraction) -> TimingPlan:
    """Work out frame count, real duration and retime for a conversion.

    The content is retimed to span exactly ``duration``; the file keeps
    the whole output frames that fit in it, dropping any partial frame at
    the end.
    """
    if source_frames < 1:
        raise ValueError("The sequence has no frames")
    output_frames = max(1, math.floor(duration * output_fps))
    output_duration = Fraction(output_frames) / output_fps
    native_duration = Fraction(source_frames) / source_fps
    return TimingPlan(
        output_fps=output_fps,
        requested_duration=duration,
        output_frames=output_frames,
        output_duration=output_duration,
        exact=output_duration == duration,
        setpts_ratio=duration / native_duration,
    )


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
        return f"Timing: {summary} (exact)"
    asked = f"{float(plan.requested_duration):.3f} s"
    if plan.output_fps.denominator != 1:
        advice = f"Use 25 or 30 fps if the player needs exactly {asked}."
    else:
        advice = (f"For an exact length, use a duration in whole frames "
                  f"(a multiple of 1/{plan.output_fps.numerator} s).")
    return (f"Timing: retimed to exactly {asked}; {summary}. {asked} is not a whole "
            f"number of frames at {label} fps, so the partial last frame is dropped. "
            f"{advice}")
