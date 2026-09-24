import os
import subprocess
import threading
import re
import asyncio
from typing import Dict, List, Optional, Callable, Tuple
from pydantic import BaseModel
from . import reformat, timing


def build_video_filter_chain(
    plan: timing.TimingPlan,
    size: Optional[Tuple[int, int]],
) -> str:
    """Build the ``-vf`` chain: retime, resample to CFR, then scale.

    The retime and CFR part comes from ``timing.timing_filters`` so the
    maths stays exact (see core/timing.py).

    When ``size`` is None the trailing ``scale`` filter carries only the
    colour matrix, exactly as it always has -- it tags BT.709 without
    resizing.  When a size is given the same filter gains the dimensions
    and the tuned resampler flags, so a reformat costs one swscale pass
    rather than adding a second one.

    A height of ``-2`` is ffmpeg's own "derive from the source aspect
    ratio and round to a multiple of two" sentinel, and passes through
    untouched.
    """
    scale_options = []
    if size is not None:
        width, height = size
        scale_options += [f"w={width}", f"h={height}", f"flags={reformat.SWS_FLAGS}"]
    scale_options += ["in_color_matrix=bt709", "out_color_matrix=bt709"]

    scale_filter = "scale=" + ":".join(scale_options)
    return f"{timing.timing_filters(plan)},{scale_filter}"


# Codecs that encode toward a target bitrate, as opposed to ProRes' qscale
# or QTRLE's lossless RLE.  ``h264_h10`` is H.264 High 10: the same encoder
# as ``h264`` but carrying a 10-bit picture.
BITRATE_CODECS = ("h264", "h265", "h264_h10")

# Codecs whose pipeline has to stay 10-bit from the source to the encoder.
TEN_BIT_CODECS = ("h264_h10",)

# H.264 levels the UI offers, as libx264's -level spells them (Annex A).
# H.265 is deliberately absent: see build_bitrate_codec_params.
H264_LEVELS = ("5", "5.1", "6.1")
DEFAULT_H264_LEVEL = "6.1"

# Codecs whose level the user may choose.
LEVEL_CODECS = ("h264", "h264_h10")

PIX_FMT_8BIT = "yuv420p"
PIX_FMT_10BIT = "yuv420p10le"


def exr_bit_depth_for_codec(codec: str) -> str:
    """Pick the oiiotool output depth for the EXR pre-pass.

    The pre-pass writes intermediate PNGs that FFmpeg then encodes, so an
    8-bit intermediate would quantise the picture before a 10-bit codec
    ever saw it -- leaving High 10 as pure file-size overhead on EXR
    sources.  16-bit costs roughly double the temp space, so only the
    codecs that can use the depth ask for it.
    """
    return "uint16" if codec in TEN_BIT_CODECS else "uint8"


def select_encoder(codec: str, gpu_caps: dict) -> Tuple[str, bool]:
    """Choose the encoder library, and report whether it is an NVENC one.

    ``h264_h10`` is deliberately absent from the NVENC branches: NVIDIA's
    H.264 encoder has no 10-bit mode, so handing it a 10-bit frame fails
    at runtime with an unsupported pixel format.  High 10 always encodes
    on the CPU, even on a machine advertising ``h264_nvenc``.
    """
    if codec == "h264" and gpu_caps.get("nvenc_h264"):
        return "h264_nvenc", True
    if codec == "h265" and gpu_caps.get("nvenc_hevc"):
        return "hevc_nvenc", True
    return ("libx265" if codec == "h265" else "libx264"), False


def normalize_level(requested: Optional[str]) -> str:
    """Return a level libx264 will accept, falling back to the default.

    The browser is not trusted to send a valid level: an unrecognised one
    makes libx264 fail to open the encoder, which would surface as a dead
    job rather than a bad setting.  Anything unknown becomes the default,
    which is the safest declaration rather than the lowest.
    """
    if requested is None:
        return DEFAULT_H264_LEVEL
    candidate = str(requested).strip()
    if candidate in H264_LEVELS:
        return candidate
    # "5.0" and "6.10" mean the same levels as "5" and "6.1".
    for known in H264_LEVELS:
        try:
            if float(candidate) == float(known):
                return known
        except ValueError:
            break
    return DEFAULT_H264_LEVEL


def build_bitrate_codec_params(
    codec: str,
    codec_lib: str,
    use_nvenc: bool,
    mp4_bitrate: str,
    level: Optional[str] = None,
) -> Tuple[List[str], str]:
    """Build the encoder arguments and pixel format for a bitrate codec.

    Returns ``(params, pix_fmt)``.  Each codec states its own profile and
    tagging explicitly rather than letting a third codec fall through to
    an ``else`` written for H.265 -- an H.264 stream that inherited
    ``-tag:v hvc1`` would misdeclare itself as HEVC to players.
    """
    cb = f"{float(mp4_bitrate):.0f}M"
    pix_fmt = PIX_FMT_10BIT if codec in TEN_BIT_CODECS else PIX_FMT_8BIT

    if use_nvenc:
        # Hardware encoder, CBR rate control for predictable file sizes.
        params = [
            "-c:v", codec_lib,
            "-preset", "p4",  # NVENC preset: p1 (fastest) to p7 (best quality)
            "-tune", "hq",
            "-rc", "cbr",
            "-b:v", cb,
            "-maxrate", cb,
            "-bufsize", f"{float(mp4_bitrate) * 2:.0f}M",  # 2x bitrate buffer
        ]
    else:
        params = [
            "-c:v", codec_lib,
            "-preset", "medium",
            "-b:v", cb,
            "-minrate", cb,
            "-maxrate", cb,
            "-bufsize", cb,
        ]

    if codec == "h265":
        # No level is declared for HEVC: libx265 has no -level option (the
        # generic one is silently ignored) and would need
        # -x265-params level-idc.  Letting x265 derive the level from the
        # stream it actually produced is both the common practice and the
        # only way to be sure the declaration is not a lie.
        params += ["-tag:v", "hvc1"]
    else:
        if not use_nvenc:
            params += ["-x264-params", "nal-hrd=cbr"]
        # Over-declaring a level is legal; under-declaring fails
        # conformance.  6.1 is the safe delivery default -- 5.1 was in fact
        # too low, as 2752x1600 at 60fps needs 1,032,000 macroblocks/s
        # against 5.1's 983,040 ceiling.
        params += [
            "-profile:v", "high10" if codec in TEN_BIT_CODECS else "high",
            "-level:v", normalize_level(level),
        ]

    return params, pix_fmt


SRGB_ODT = "Output - sRGB"
REC709_ODT = "Output - Rec.709"

# The only ACES output transforms the UI offers.  Both share the RRT and
# Rec.709 primaries and differ only in the encoding function, so choosing
# between them is a tone-response decision, not a gamut one.
OUTPUT_TRANSFORMS = (SRGB_ODT, REC709_ODT)


def default_output_transform_for_codec(codec: str) -> str:
    """Pre-select the transform that suits where this codec usually goes.

    ProRes goes to editorial and grading, which expect the broadcast
    Rec.709 ODT.  H.264/H.265 review files are watched on computer
    screens, so they default to sRGB.  Anything unrecognised gets sRGB,
    which is the historical behaviour.
    """
    return REC709_ODT if codec.startswith("prores") else SRGB_ODT


def resolve_output_transform(requested: Optional[str], codec: str) -> str:
    """Validate an explicit choice, else fall back to the codec default.

    Rejecting an unknown name here turns a typo into an immediate error
    rather than an oiiotool failure partway through a sequence.
    """
    if not requested:
        return default_output_transform_for_codec(codec)
    if requested not in OUTPUT_TRANSFORMS:
        raise ValueError(
            f"Unsupported output transform {requested!r}; expected one of "
            + ", ".join(OUTPUT_TRANSFORMS)
        )
    return requested


def describe_codec(
    codec: str,
    gpu_caps: Optional[dict] = None,
    level: Optional[str] = None,
) -> Dict[str, str]:
    """Summarise what this codec will actually encode with.

    Built from the very functions that assemble the FFmpeg command, so
    the readout in the UI cannot drift from what the encoder is told.
    A readout that is allowed to disagree with the command is worse than
    having none at all.
    """
    info: Dict[str, str] = {
        "codec": codec,
        "output_transform": default_output_transform_for_codec(codec),
    }
    if codec in BITRATE_CODECS:
        codec_lib, use_nvenc = select_encoder(codec, gpu_caps or {})
        params, pix_fmt = build_bitrate_codec_params(
            codec, codec_lib, use_nvenc, "30", level
        )
        info["encoder"] = codec_lib
        info["pix_fmt"] = pix_fmt
        for flag, key in (("-profile:v", "profile"), ("-level:v", "level")):
            if flag in params:
                info[key] = params[params.index(flag) + 1]
    elif codec.startswith("prores"):
        info["encoder"] = "prores_ks"
    elif codec == "qtrle":
        info["encoder"] = "qtrle"
        info["pix_fmt"] = "rgb24"
    else:
        info["encoder"] = "unknown"
    return info


class FFmpegJobConfig(BaseModel):
    input_folder: str
    filename_pattern: str
    output_folder: str
    output_filename: str
    frame_rate: str
    source_frame_rate: str
    desired_duration: str
    codec: str
    output_transform: Optional[str] = None
    mp4_bitrate: Optional[str] = None
    # H.264 level (see H264_LEVELS).  None means the default; the value is
    # validated server-side, never trusted as sent.
    level: Optional[str] = None
    prores_profile: Optional[str] = None
    prores_qscale: Optional[str] = None
    audio_option: str = "No Audio"
    start_frame: int
    end_frame: int
    reformat_enabled: bool = False
    reformat_width: Optional[int] = None
    reformat_height: Optional[int] = None

def resolve_reformat_size(
    config: "FFmpegJobConfig",
    log: Optional[Callable[[str, str], None]] = None,
) -> Optional[Tuple[int, int]]:
    """Work out the target pixel size for a job, or None if disabled.

    The source resolution is probed from the job's own first frame --
    never taken from the client -- so the size the encoder gets is
    always derived from the pixels it is about to read.

    If probing fails but only one dimension was requested, ffmpeg's
    own ``-2`` sentinel handles the aspect ratio for us, so a probe
    failure degrades instead of aborting the job.

    Raises:
        reformat.ReformatError: if the request cannot be satisfied.
    """
    log = log or (lambda _kind, _msg: None)
    if not config.reformat_enabled:
        return None

    first_frame = reformat.first_frame_path(
        config.input_folder, config.filename_pattern, config.start_frame
    )
    source = reformat.probe_resolution(first_frame)

    if source is None:
        if config.reformat_width and not config.reformat_height:
            log('output', "Could not probe the source resolution; letting FFmpeg "
                "derive the height from the source aspect ratio.\n")
            return reformat.even(config.reformat_width), -2
        if config.reformat_height and not config.reformat_width:
            log('output', "Could not probe the source resolution; letting FFmpeg "
                "derive the width from the source aspect ratio.\n")
            return -2, reformat.even(config.reformat_height)

    source_width, source_height = source if source else (None, None)
    size = reformat.resolve_dimensions(
        config.reformat_width,
        config.reformat_height,
        source_width,
        source_height,
    )
    if source:
        log('output', f"Reformatting {source_width}x{source_height} -> "
            f"{size[0]}x{size[1]} (lanczos).\n")
    return size


def build_video_args(
    config: "FFmpegJobConfig",
    plan: timing.TimingPlan,
    reformat_size: Optional[Tuple[int, int]],
    gpu_caps: dict,
) -> Tuple[List[str], Dict[str, object]]:
    """Build the video half of the encode command, from ``-fps_mode`` on.

    Covers the filter chain, pixel format, codec and colour tags -- all of
    the command that decides what the pictures cost in bytes.  The job and
    the size estimate's sample encode both build from here, so an estimate
    cannot measure a different encode from the one the job runs.

    ``gpu_caps`` is accepted for parity with the studio lineage; this
    lineage has no NVENC path, so every codec encodes on the CPU.
    """
    output_pix_fmt = PIX_FMT_8BIT
    video_codec_params: List[str] = []
    codec_lib = "unknown"

    if config.codec in BITRATE_CODECS:
        codec_lib, _ = select_encoder(config.codec, {})
        video_codec_params, output_pix_fmt = build_bitrate_codec_params(
            config.codec, codec_lib, False, config.mp4_bitrate, config.level
        )
    elif config.codec.startswith("prores"):
        codec_lib = "prores_ks"
        video_codec_params = [
            "-c:v", "prores_ks",
            "-profile:v", str(config.prores_profile),
            "-qscale:v", str(config.prores_qscale),
        ]
    elif config.codec == "qtrle":
        codec_lib = "qtrle"
        output_pix_fmt = "rgb24"
        video_codec_params = ["-c:v", "qtrle"]

    # NTSC exact length: the last frame is shortened in a stream-copy
    # remux after the encode (see timing.trim_last_frame_bsf), which
    # needs display order == decode order, i.e. no B-frames.
    if plan.last_frame_ticks is not None and config.codec in BITRATE_CODECS:
        video_codec_params += ["-bf", "0"]

    args = [
        "-fps_mode", "cfr",
        "-vf", build_video_filter_chain(plan, reformat_size),
        "-pix_fmt", output_pix_fmt,
        "-video_track_timescale", str(timing.track_timescale(plan.output_fps)),
        *video_codec_params,
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-colorspace", "bt709",
    ]
    return args, {"encoder": codec_lib, "nvenc": False, "cuda_filters": False}


class FFmpegHandler:
    def __init__(self, log_callback: Callable[[str, str], None]):
        """
        Args:
            log_callback: Function to call with (msg_type, content)
                          msg_type: 'output', 'progress', 'error', 'success', 'cancelled'
        """
        self.log_callback = log_callback
        self.process: Optional[subprocess.Popen] = None
        self.is_cancelled = False

    def _resolve_reformat_size(
        self, config: FFmpegJobConfig
    ) -> Optional[Tuple[int, int]]:
        """Work out the target pixel size for this job, logging the choice."""
        return resolve_reformat_size(config, self.log_callback)

    def run_ffmpeg(self, config: FFmpegJobConfig):
        """Build and execute FFmpeg command."""
        self.is_cancelled = False
        
        # --- Validation & Setup ---
        if not os.path.exists(config.input_folder):
            self.log_callback('error', f"Input folder does not exist: {config.input_folder}")
            return

        if not os.path.exists(config.output_folder):
            try:
                os.makedirs(config.output_folder)
            except Exception as e:
                self.log_callback('error', f"Cannot create output directory: {e}")
                return

        output_path = os.path.join(config.output_folder, config.output_filename)
        
        # Frame rates and duration, in exact arithmetic (see core/timing.py).
        try:
            source_fps = timing.parse_fps(config.source_frame_rate)
            output_fps = timing.parse_fps(config.frame_rate)
            plan = timing.plan_timing(
                config.end_frame - config.start_frame + 1,
                source_fps, output_fps,
                timing.parse_duration(config.desired_duration),
            )
        except ValueError as exc:
            self.log_callback('error', f"Invalid duration or frame rate: {exc}")
            return
        self.log_callback('output', timing.describe(plan) + "\n")
        total_frames_needed = plan.output_frames

        # --- Build Command ---
        cmd = ["ffmpeg", "-y", "-accurate_seek"]

        # Input Args
        input_path = os.path.join(config.input_folder, config.filename_pattern)
        image_sequence_input_args = [
            "-start_number", str(config.start_frame),
            "-framerate", timing.fps_arg(source_fps),
            "-i", input_path
        ]
        
        cmd += ["-ss", "0"] + image_sequence_input_args

        # Audio Args
        blank_audio_input_args = []
        output_audio_handling_args = []
        
        if config.audio_option == "Blank Audio Track":
            blank_audio_input_args = [
                "-f", "lavfi",
                "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-shortest"
            ]
            output_audio_handling_args.extend(["-c:a", "aac", "-b:a", "128k"])
        elif config.audio_option == "No Audio":
            output_audio_handling_args = ["-an"]

        cmd += blank_audio_input_args

        # Resolve the reformat target before any encoding starts, so a bad
        # request aborts early.
        try:
            reformat_size = self._resolve_reformat_size(config)
        except reformat.ReformatError as exc:
            self.log_callback('error', str(exc))
            return

        # Video: codec, filter chain and colour tags (shared with the size
        # estimate, so a sample encode is the job's own command).
        if config.codec in BITRATE_CODECS and not config.mp4_bitrate:
            self.log_callback('error', "Bitrate required for H.264/H.265/High 10")
            return
        if config.codec.startswith("prores") and not (
            config.prores_profile and config.prores_qscale
        ):
            self.log_callback('error', "ProRes profile and quality required")
            return

        video_args, _info = build_video_args(config, plan, reformat_size, {})
        trim = plan.last_frame_ticks is not None
        cmd += output_audio_handling_args
        cmd += video_args

        if total_frames_needed:
            cmd += ["-frames:v", str(total_frames_needed)]

        if trim:
            root, ext = os.path.splitext(output_path)
            encode_path = f"{root}.untrimmed{ext}"
        else:
            encode_path = output_path
            if plan.timecode:
                cmd += ["-timecode", plan.timecode]
        cmd.append(encode_path)

        self.log_callback('output', f"FFmpeg Command: {' '.join(cmd)}\n")

        # Execute
        if not trim:
            self._execute_process(cmd, total_frames_needed)
            return
        try:
            if not self._execute_process(cmd, total_frames_needed, announce_success=False):
                return
            remux = [
                "ffmpeg", "-y", "-i", encode_path, "-map", "0", "-c", "copy",
                "-video_track_timescale", str(timing.track_timescale(output_fps)),
                "-timecode", plan.timecode,
                "-bsf:v", timing.trim_last_frame_bsf(plan),
                output_path,
            ]
            self.log_callback('output', "Shortening the last frame to land on the exact duration.\n")
            self.log_callback('output', f"FFmpeg Command: {' '.join(remux)}\n")
            self._execute_process(remux, total_frames_needed)
        finally:
            if os.path.exists(encode_path):
                os.remove(encode_path)

    def _execute_process(self, cmd, total_frames_needed, announce_success=True) -> bool:
        """Run one FFmpeg command, streaming its log; True if it succeeded.

        ``announce_success=False`` is for a first pass that another command
        follows, so the UI does not report the job done too early.
        """
        ok = False
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            self.log_callback('output', f"Process started with PID: {self.process.pid}\n")
            
            # We need to read stdout and stderr. For simplicity in this synchronous
            # wrapper (which will be run in a thread), we'll read stderr linewise
            # as that's where ffmpeg stats are.
            
            # NOTE: FFmpeg puts progress on stderr.
            for line in iter(self.process.stderr.readline, ''):
                if self.is_cancelled:
                    self.process.terminate()
                    break
                    
                self.log_callback('output', line)
                
                # Parse progress
                if "frame=" in line:
                    frame_match = re.search(r'frame=\s*(\d+)', line)
                    if frame_match:
                        current = int(frame_match.group(1))
                        pct = (current / total_frames_needed) * 100 if total_frames_needed else 0
                        self.log_callback('progress', str(pct))

            self.process.wait()
            
            if self.is_cancelled:
                self.log_callback('cancelled', "Conversion cancelled.")
            elif self.process.returncode == 0:
                ok = True
                if announce_success:
                    self.log_callback('success', "Conversion complete!")
            else:
                 # Read remaining stderr if any
                remaining = self.process.stderr.read()
                self.log_callback('error', f"FFmpeg failed with code {self.process.returncode}.\n{remaining}")

        except Exception as e:
            self.log_callback('error', f"Execution error: {e}")
        finally:
            self.process = None
        return ok

    def cancel(self):
        self.is_cancelled = True
        if self.process:
            self.process.terminate()
