"""Output file-size estimate.

How honest an estimate can be depends on the encoder's rate control, so
every estimate says which kind it is:

``exact``
    libx264 (H.264 and High 10).  It runs strict CBR with ``nal-hrd=cbr``,
    which pads easy pictures with filler, so the size does not depend on
    the picture at all -- flat grey and full-frame noise measure the same
    to the byte.  The stream carries ``bitrate x encoded duration`` less
    one thing: x264 starts its VBV buffer 90% full, so the first 10% of
    one buffer (``-bufsize``, one second here) is never sent.

``upper_bound``
    libx265 and NVENC.  libx265 ignores ``-minrate``, so simple pictures
    come out far smaller (flat grey: 44 KB against 37.5 MB); NVENC is not
    padded either.  Neither overshoots the target by more than rate-control
    noise, so ``bitrate x duration`` is the ceiling.

``measured``
    ProRes (constant quality, ``-qscale``) and QTRLE (lossless RLE).  Bytes
    per frame depend on the picture, so no formula exists.  A few windows
    spread across the sequence are encoded with the job's own command (see
    ``ffmpeg_handler.build_video_args``) and their mean bytes per frame is
    scaled up.  ``low``/``high`` are a ~95% interval (two standard errors)
    from the successive-difference variance estimator, the standard one
    for evenly spaced samples: it measures how much neighbouring windows
    disagree, so a plate that changes along its length gets a wider range.

Durations come from ``timing.plan_timing``: the bytes follow the frames
actually encoded, which at NTSC rates is the whole last frame -- the trim
that shortens it afterwards is a stream copy and removes nothing.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from . import reformat, timing
from .exr_handler import OCIO_CONFIG, EXR_COLOR_SPACE, build_frame_command
from .ffmpeg_handler import (
    BITRATE_CODECS,
    FFmpegJobConfig,
    build_video_args,
    exr_bit_depth_for_codec,
    resolve_output_transform,
    resolve_reformat_size,
    select_encoder,
)

# x264's default --vbv-init: the buffer starts 90% full, so 10% of one
# buffer's worth of bits is never delivered.  The app sets -bufsize equal
# to the bitrate for libx264 (see build_bitrate_codec_params).
X264_VBV_INIT = Fraction(9, 10)

# MP4/MOV index (stsz/stts/stco/stss entries) and headers, measured from
# real encodes: 3-7 KB on 250-450 frames.
MUX_FIXED_BYTES = 2048
MUX_BYTES_PER_FRAME = 12

# "Blank Audio Track" is anullsrc through ffmpeg's AAC encoder, which spends
# 6 bytes on a silent 1024-sample frame whatever -b:a says, plus about 10
# bytes of index per packet.  One extra packet is the encoder's priming.
AAC_SAMPLE_RATE = 48000
AAC_FRAME_SAMPLES = 1024
SILENT_AAC_PACKET_BYTES = 6
AAC_MUX_BYTES_PER_PACKET = 10

# Sampling: ProRes is intra-only, so single frames are exact samples of
# themselves and more of them buys coverage.  QTRLE codes each frame
# against the previous one with a keyframe every 12 (ffmpeg's default
# gop), so each window is one whole GOP.
PRORES_WINDOWS, PRORES_FRAMES_PER_WINDOW = 24, 1
QTRLE_WINDOWS, QTRLE_FRAMES_PER_WINDOW = 6, 12

SUBPROCESS_TIMEOUT = 300


def encoded_duration(plan: timing.TimingPlan) -> Fraction:
    """Seconds of pictures the encoder produces (whole frames, pre-trim)."""
    return Fraction(plan.output_frames) / plan.output_fps


def _audio_bytes(audio_option: str, seconds: Fraction) -> int:
    if audio_option != "Blank Audio Track":
        return 0
    packets = math.ceil(seconds * AAC_SAMPLE_RATE / AAC_FRAME_SAMPLES) + 1
    return packets * (SILENT_AAC_PACKET_BYTES + AAC_MUX_BYTES_PER_PACKET)


def _container_bytes(frames: int) -> int:
    return MUX_FIXED_BYTES + MUX_BYTES_PER_FRAME * frames


def _result(kind: str, video: int, plan: timing.TimingPlan, audio_option: str,
            method: str, **extra) -> Dict[str, object]:
    seconds = encoded_duration(plan)
    breakdown = {
        "video": video,
        "audio": _audio_bytes(audio_option, seconds),
        "container": _container_bytes(plan.output_frames),
    }
    result = {
        "kind": kind,
        "bytes": sum(breakdown.values()),
        "breakdown": breakdown,
        "frames": plan.output_frames,
        "seconds": float(plan.output_duration),
        "method": method,
    }
    result.update(extra)
    return result


def _fmt_seconds(seconds: Fraction) -> str:
    return f"{float(seconds):.3f} s"


def estimate_bitrate_codec(codec: str, mp4_bitrate: str, plan: timing.TimingPlan,
                           audio_option: str, gpu_caps: dict) -> Dict[str, object]:
    """Closed-form size for H.264 / High 10 / H.265 (see the module docstring)."""
    rate = Fraction(str(mp4_bitrate)) * 1_000_000  # ffmpeg's "30M" is SI
    # build_bitrate_codec_params rounds the rate to whole Mb/s.
    rate = Fraction(round(rate / 1_000_000) * 1_000_000)
    seconds = encoded_duration(plan)
    nominal = rate * seconds / 8
    encoder, nvenc = select_encoder(codec, gpu_caps)
    mbps = f"{float(rate / 1_000_000):g} Mb/s"

    if encoder == "libx264":
        vbv_unsent = (1 - X264_VBV_INIT) * rate / 8  # bufsize == bitrate
        video = round(nominal - vbv_unsent)
        return _result(
            "exact", video, plan, audio_option,
            f"{mbps} CBR x {_fmt_seconds(seconds)} ({plan.output_frames} frames), "
            f"less x264's unsent VBV start (10% of a {mbps} buffer)",
        )
    return _result(
        "upper_bound", round(nominal), plan, audio_option,
        f"{mbps} x {_fmt_seconds(seconds)} ({plan.output_frames} frames); "
        f"{encoder} spends less on simple pictures",
    )


@dataclass(frozen=True)
class Window:
    """A run of the sequence to sample-encode (indices are 0-based)."""
    first_source: int
    source_count: int
    output_frames: int


def sample_windows(source_frames: int, output_frames: int, count: int,
                   frames_per_window: int) -> List[Window]:
    """Spread ``count`` windows evenly (stratified) across the output.

    Each window sits at the middle of its own equal slice of the output,
    so a sequence that changes along its length is sampled along its
    length.  Output frame ``j`` shows source frame ``j * S / O`` (the
    retime spreads the source over the output), so a window of ``k``
    output frames needs ``k * S / O`` source frames, plus one because the
    fps filter holds each frame until the next arrives.
    """
    k = max(1, min(frames_per_window, output_frames))
    count = max(1, min(count, output_frames // k))
    ratio = Fraction(source_frames, output_frames)
    need = 1 if k == 1 else min(source_frames, math.ceil(k * ratio) + 1)

    windows = []
    for i in range(count):
        centre = (Fraction(2 * i + 1, 2 * count)) * output_frames
        first_out = min(max(0, math.floor(centre - Fraction(k - 1, 2))), output_frames - k)
        first_src = min(math.floor(first_out * ratio), source_frames - need)
        windows.append(Window(first_src, need, k))
    return windows


def extrapolate(samples: List[Tuple[int, int]], plan: timing.TimingPlan,
                audio_option: str) -> Dict[str, object]:
    """Scale sampled ``(bytes, frames)`` windows up to the whole output.

    ``samples`` must be in sequence order: the variance estimate compares
    each window with its neighbour.
    """
    total_bytes = sum(b for b, _ in samples)
    total_frames = sum(f for _, f in samples)
    mean = Fraction(total_bytes, total_frames)
    frames = plan.output_frames

    result = _result(
        "measured", round(mean * frames), plan, audio_option,
        f"{total_frames} sampled frame{'s' * (total_frames != 1)} averaging "
        f"{float(mean) / 1e6:.2f} MB, x {frames} frames",
    )
    n = len(samples)
    if n > 1:
        per_frame = [Fraction(b, f) for b, f in samples]
        variance = sum((b - a) ** 2 for a, b in zip(per_frame, per_frame[1:])) \
            / (2 * n * (n - 1))
        margin = 2 * math.sqrt(variance) * frames
        overhead = result["bytes"] - result["breakdown"]["video"]
        video = float(mean * frames)
        result["low"] = round(max(0.0, video - margin)) + overhead
        result["high"] = round(video + margin) + overhead
    return result


def _video_packet_bytes(path: str) -> Tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=size", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True, timeout=SUBPROCESS_TIMEOUT,
    ).stdout.split()
    sizes = [int(s.strip(",")) for s in out if s.strip(",")]
    return sum(sizes), len(sizes)


def _convert_exr_frames(config: FFmpegJobConfig, frames: List[int], work: str,
                        size: Optional[Tuple[int, int]]) -> str:
    """Run the job's own oiiotool pre-pass on just these frames."""
    prefix = config.filename_pattern.split("%")[0]
    depth = exr_bit_depth_for_codec(config.codec)
    odt = resolve_output_transform(config.output_transform, config.codec)
    cmds = [
        build_frame_command(
            reformat.first_frame_path(config.input_folder, config.filename_pattern, f),
            os.path.join(work, f"{prefix}{f:04d}.png"),
            OCIO_CONFIG, EXR_COLOR_SPACE, size, bit_depth=depth, output_transform=odt,
        )
        for f in frames
    ]
    workers = max(1, min(len(cmds), (os.cpu_count() or 4) // 2))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(
            lambda c: subprocess.run(c, capture_output=True, text=True,
                                     timeout=SUBPROCESS_TIMEOUT), cmds))
    for result in results:
        if result.returncode != 0:
            raise RuntimeError(f"oiiotool failed: {result.stderr.strip()[-300:]}")
    return f"{prefix}%04d.png"


def _encode_window(config: FFmpegJobConfig, plan: timing.TimingPlan, window: Window,
                   size: Optional[Tuple[int, int]], work: str) -> Tuple[int, int]:
    """Encode one window with the job's own video command; (bytes, frames)."""
    first = config.start_frame + window.first_source
    folder, pattern, ffmpeg_size = config.input_folder, config.filename_pattern, size
    if config.filename_pattern.lower().endswith(".exr"):
        # The resize happens in oiiotool, as in the job, never twice.
        pattern = _convert_exr_frames(
            config, list(range(first, first + window.source_count)), work, size)
        folder, ffmpeg_size = work, None

    video_args, _info = build_video_args(config, plan, ffmpeg_size, {})
    out = os.path.join(work, "sample.mov")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-threads", "2",
         "-start_number", str(first),
         "-framerate", timing.fps_arg(timing.parse_fps(config.source_frame_rate)),
         "-i", os.path.join(folder, pattern),
         "-an", *video_args, "-frames:v", str(window.output_frames), out],
        capture_output=True, text=True, check=True, timeout=SUBPROCESS_TIMEOUT,
    )
    return _video_packet_bytes(out)


def sample_encode(config: FFmpegJobConfig, plan: timing.TimingPlan) -> List[Tuple[int, int]]:
    """Encode the sample windows, in parallel, returned in sequence order.

    Each window works in its own folder, emptied as soon as it is done,
    so at most one window's frames per worker sit on disk (8K frames are
    50-100 MB apiece).
    """
    if config.codec == "qtrle":
        count, per_window = QTRLE_WINDOWS, QTRLE_FRAMES_PER_WINDOW
    else:
        count, per_window = PRORES_WINDOWS, PRORES_FRAMES_PER_WINDOW
    source_frames = config.end_frame - config.start_frame + 1
    windows = sample_windows(source_frames, plan.output_frames, count, per_window)

    size = resolve_reformat_size(config)
    if config.filename_pattern.lower().endswith(".exr") and size and -2 in size:
        # oiiotool has no "-2"; the EXR job refuses this case too.
        raise reformat.ReformatError(
            "Could not probe the source resolution to derive the other dimension.")

    root = tempfile.mkdtemp(prefix="ffmpeg_web_estimate_")

    def run(indexed):
        index, window = indexed
        work = os.path.join(root, str(index))
        os.makedirs(work)
        try:
            return _encode_window(config, plan, window, size, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    try:
        workers = max(1, min(len(windows), (os.cpu_count() or 4) // 4))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(run, enumerate(windows)))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def estimate(config: FFmpegJobConfig, sample: bool = False) -> Dict[str, object]:
    """Estimate the finished file's size for this job.

    Bitrate codecs are answered from the maths straight away.  ProRes and
    QTRLE return ``needs_sample`` unless ``sample`` is set, since sampling
    runs real encodes (and, for EXR, oiiotool) and takes seconds.
    """
    plan = timing.plan_timing(
        config.end_frame - config.start_frame + 1,
        timing.parse_fps(config.source_frame_rate),
        timing.parse_fps(config.frame_rate),
        timing.parse_duration(config.desired_duration),
    )
    if config.codec in BITRATE_CODECS:
        if not config.mp4_bitrate:
            raise ValueError("A target bitrate is required")
        # This lineage has no NVENC path: every bitrate codec is CPU.
        return estimate_bitrate_codec(
            config.codec, config.mp4_bitrate, plan, config.audio_option, {})
    if not sample:
        return {
            "kind": "needs_sample",
            "frames": plan.output_frames,
            "seconds": float(plan.output_duration),
            "method": "Size depends on the picture; sample-encode to measure it",
        }
    try:
        samples = sample_encode(config, plan)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Sample encode failed: {exc.stderr.strip()[-300:]}") from None
    return extrapolate(samples, plan, config.audio_option)
