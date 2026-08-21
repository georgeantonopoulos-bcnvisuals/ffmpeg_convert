"""Output resolution (reformat) support.

This module owns three things so that the EXR pre-pass, the FFmpeg pass
and the API all agree on exactly one set of rules:

1. The tuned resampling settings for each backend (``SWS_FLAGS`` and
   ``OIIO_RESIZE_ARG``).
2. How a partially specified request (width only, or height only) becomes
   a concrete even-numbered pixel size (:func:`resolve_dimensions`).
3. How the source resolution is discovered (:func:`probe_resolution`).

Dimensions are always snapped to even numbers.  ``yuv420p`` subsamples
chroma 2:1 in both axes, so an odd dimension is not merely untidy -- it
is a hard encoder failure, and it is better to snap and say so than to
die halfway through a sequence.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Optional, Tuple

# libswscale flags for the FFmpeg path.
#
# ``lanczos`` is a windowed-sinc filter; swscale widens its kernel in
# proportion to the downscale ratio, so it low-passes correctly and does
# not alias.  ``accurate_rnd`` disables the fast-but-lossy rounding in
# the scaler's integer path, and ``full_chroma_int`` interpolates chroma
# at full resolution instead of reusing subsampled samples.
SWS_FLAGS = "lanczos+accurate_rnd+full_chroma_int"

# oiiotool arguments for the EXR path.
#
# ``lanczos3`` is oiiotool's 3-lobe Lanczos.  ``highlightcomp=1`` rolls
# HDR values off before filtering and restores them afterwards, which is
# what stops a bright specular from ringing into a dark halo when scene-
# linear ACEScg data is resized.
OIIO_RESIZE_ARG = "--resize:filter=lanczos3:highlightcomp=1"

# oiiotool --info prints e.g. "plate.exr : 2048 x  858, 3 channel, half openexr"
_OIIO_INFO_RE = re.compile(r":\s*(\d+)\s*x\s*(\d+)\b")

# ffmpeg -i prints e.g. "Stream #0:0: Video: png, rgb24(pc), 2048x858, 25 fps"
_FFMPEG_SIZE_RE = re.compile(r"\b(\d{2,})x(\d{2,})\b")


class ReformatError(ValueError):
    """Raised when a reformat request cannot be turned into a pixel size."""


def even(value: int) -> int:
    """Round ``value`` up to the nearest even number, with a floor of 2.

    Rounding up rather than to nearest means the result is never smaller
    than what the user asked for.
    """
    value = int(value)
    if value < 2:
        return 2
    return value + (value % 2)


def resolve_dimensions(
    requested_width: Optional[int],
    requested_height: Optional[int],
    source_width: Optional[int],
    source_height: Optional[int],
) -> Tuple[int, int]:
    """Turn a reformat request into a concrete, even ``(width, height)``.

    Supplying only one of the two dimensions derives the other from the
    source aspect ratio.  Supplying both uses them verbatim, which may
    stretch the image -- that is deliberate: the request wins.

    Raises:
        ReformatError: if nothing was requested, a requested value is not
            positive, or a single dimension was given but the source
            resolution is unknown.
    """
    for label, value in (("width", requested_width), ("height", requested_height)):
        if value is not None and int(value) <= 0:
            raise ReformatError(f"Reformat {label} must be a positive number.")

    if requested_width is None and requested_height is None:
        raise ReformatError(
            "Reformat is enabled but no size was given. "
            "Enter a width, a height, or both."
        )

    if requested_width is not None and requested_height is not None:
        return even(requested_width), even(requested_height)

    if not source_width or not source_height:
        raise ReformatError(
            "Could not determine the source resolution, so the missing "
            "dimension cannot be derived. Enter both a width and a height."
        )

    if requested_width is not None:
        width = int(requested_width)
        height = round(width * source_height / source_width)
    else:
        height = int(requested_height)
        width = round(height * source_width / source_height)

    return even(width), even(height)


def parse_oiiotool_info(text: str) -> Optional[Tuple[int, int]]:
    """Extract ``(width, height)`` from ``oiiotool --info`` output."""
    match = _OIIO_INFO_RE.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def parse_ffmpeg_stderr(text: str) -> Optional[Tuple[int, int]]:
    """Extract ``(width, height)`` from ``ffmpeg -i`` stderr output.

    Only video stream lines are considered, so timecodes, bitrates and
    frame rates elsewhere in the banner cannot be misread as a size.
    """
    for line in text.splitlines():
        if "Video:" not in line:
            continue
        match = _FFMPEG_SIZE_RE.search(line)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def probe_resolution(path: str) -> Optional[Tuple[int, int]]:
    """Read the pixel dimensions of a single image file.

    Prefers ``oiiotool --info`` (a header-only read that understands EXR,
    PNG, TIFF and JPEG alike) and falls back to ``ffmpeg -i``.  Returns
    ``None`` rather than raising if the file is missing or neither tool
    can read it -- callers treat an unknown source size as "cannot derive
    the other dimension", which is a user-facing message, not a crash.
    """
    if not path or not os.path.isfile(path):
        return None

    try:
        result = subprocess.run(
            ["oiiotool", "--info", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        size = parse_oiiotool_info(result.stdout)
        if size:
            return size
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        # ffmpeg -i with no output exits non-zero by design; the banner we
        # want is on stderr regardless.
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return parse_ffmpeg_stderr(result.stderr)
    except (OSError, subprocess.SubprocessError):
        return None


def first_frame_path(input_folder: str, pattern: str, frame: int) -> str:
    """Build the path of a single frame from a printf-style sequence pattern.

    Mirrors the substitution the EXR handler performs so that probing and
    conversion always look at the same file.
    """
    try:
        filename = pattern % frame
    except (TypeError, ValueError):
        filename = pattern
    return os.path.join(input_folder, filename)
