import os
import subprocess
import threading
import re
import asyncio
from typing import Dict, List, Optional, Callable, Tuple
from pydantic import BaseModel
from . import reformat
from .utils import normalize_fps, calculate_duration_and_frames


def build_video_filter_chain(
    scale_factor: float,
    out_ffmpeg_fps_str: str,
    size: Optional[Tuple[int, int]],
) -> str:
    """Build the ``-vf`` chain: retime, resample to CFR, then scale.

    When ``size`` is None the trailing ``scale`` filter carries only the
    colour matrix, exactly as it always has -- it tags BT.709 without
    resizing.  When a size is given the same filter gains the dimensions
    and the tuned resampler flags, so a reformat costs one swscale pass
    rather than adding a second one.

    A height of ``-2`` is ffmpeg's own "derive from the source aspect
    ratio and round to a multiple of two" sentinel, and passes through
    untouched.
    """
    setpts_filter = f"setpts={scale_factor:.10f}*PTS"

    scale_options = []
    if size is not None:
        width, height = size
        scale_options += [f"w={width}", f"h={height}", f"flags={reformat.SWS_FLAGS}"]
    scale_options += ["in_color_matrix=bt709", "out_color_matrix=bt709"]

    scale_filter = "scale=" + ":".join(scale_options)
    return f"{setpts_filter},fps={out_ffmpeg_fps_str},{scale_filter}"


# Codecs that encode toward a target bitrate, as opposed to ProRes' qscale
# or QTRLE's lossless RLE.  ``h264_h10`` is H.264 High 10: the same encoder
# as ``h264`` but carrying a 10-bit picture.
BITRATE_CODECS = ("h264", "h265", "h264_h10")

# Codecs whose pipeline has to stay 10-bit from the source to the encoder.
TEN_BIT_CODECS = ("h264_h10",)

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


def build_bitrate_codec_params(
    codec: str,
    codec_lib: str,
    use_nvenc: bool,
    mp4_bitrate: str,
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
        params += ["-tag:v", "hvc1"]
    else:
        if not use_nvenc:
            params += ["-x264-params", "nal-hrd=cbr"]
        # Level 6.1 is what delivery asks for, and 5.1 was in fact too low:
        # 2752x1600 at 60fps needs 1,032,000 macroblocks/s against 5.1's
        # 983,040 ceiling, so the file declared a level it exceeded.
        # Over-declaring is legal; under-declaring fails conformance.
        params += [
            "-profile:v", "high10" if codec in TEN_BIT_CODECS else "high",
            "-level:v", "6.1",
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


def describe_codec(codec: str, gpu_caps: Optional[dict] = None) -> Dict[str, str]:
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
        params, pix_fmt = build_bitrate_codec_params(codec, codec_lib, use_nvenc, "30")
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
    prores_profile: Optional[str] = None
    prores_qscale: Optional[str] = None
    audio_option: str = "No Audio"
    start_frame: int
    end_frame: int
    reformat_enabled: bool = False
    reformat_width: Optional[int] = None
    reformat_height: Optional[int] = None

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
        """Work out the target pixel size for this job, or None if disabled.

        The source resolution is probed from the job's own first frame --
        never taken from the client -- so the size the encoder gets is
        always derived from the pixels it is about to read.

        If probing fails but only one dimension was requested, ffmpeg's
        own ``-2`` sentinel handles the aspect ratio for us, so a probe
        failure degrades instead of aborting the job.
        """
        if not config.reformat_enabled:
            return None

        first_frame = reformat.first_frame_path(
            config.input_folder, config.filename_pattern, config.start_frame
        )
        source = reformat.probe_resolution(first_frame)

        if source is None:
            if config.reformat_width and not config.reformat_height:
                self.log_callback(
                    'output',
                    "Could not probe the source resolution; letting FFmpeg "
                    "derive the height from the source aspect ratio.\n",
                )
                return reformat.even(config.reformat_width), -2
            if config.reformat_height and not config.reformat_width:
                self.log_callback(
                    'output',
                    "Could not probe the source resolution; letting FFmpeg "
                    "derive the width from the source aspect ratio.\n",
                )
                return -2, reformat.even(config.reformat_height)

        source_width, source_height = source if source else (None, None)
        size = reformat.resolve_dimensions(
            config.reformat_width,
            config.reformat_height,
            source_width,
            source_height,
        )

        if source:
            self.log_callback(
                'output',
                f"Reformatting {source_width}x{source_height} -> "
                f"{size[0]}x{size[1]} (lanczos).\n",
            )
        return size

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
        
        # Basic FPS normalization
        src_num_fps, src_ffmpeg_fps_str, src_num, src_den = normalize_fps(config.source_frame_rate)
        out_num_fps, out_ffmpeg_fps_str, out_num, out_den = normalize_fps(config.frame_rate)
        
        try:
            desired_duration = float(config.desired_duration)
            if src_num_fps <= 0 or desired_duration <= 0:
                raise ValueError
        except ValueError:
             self.log_callback('error', "Invalid duration or frame rate.")
             return

        # Calculate frames
        total_input_frames = config.end_frame - config.start_frame + 1
        original_duration = total_input_frames / src_num_fps
        scale_factor = desired_duration / original_duration
        actual_duration = desired_duration
        
        # Calculate expected output frames
        total_frames_needed = int(round(out_num_fps * actual_duration))

        # --- Build Command ---
        cmd = ["ffmpeg", "-y", "-accurate_seek"]

        # Input Args
        input_path = os.path.join(config.input_folder, config.filename_pattern)
        image_sequence_input_args = [
            "-start_number", str(config.start_frame),
            "-framerate", src_ffmpeg_fps_str,
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

        # Filters
        cmd += ["-fps_mode", "cfr"]

        try:
            reformat_size = self._resolve_reformat_size(config)
        except reformat.ReformatError as exc:
            self.log_callback('error', str(exc))
            return

        ffmpeg_filters_str = build_video_filter_chain(
            scale_factor, out_ffmpeg_fps_str, reformat_size
        )
        cmd += ["-vf", ffmpeg_filters_str]

        # Codec & Pixel Format
        output_pix_fmt = "yuv420p"
        video_codec_params = []
        
        if config.codec in BITRATE_CODECS:
            if not config.mp4_bitrate:
                self.log_callback('error', "Bitrate required for H.264/H.265/High 10")
                return

            # This lineage has no NVENC path; High 10 is CPU-only regardless.
            codec_lib, _ = select_encoder(config.codec, {})
            video_codec_params, output_pix_fmt = build_bitrate_codec_params(
                config.codec, codec_lib, False, config.mp4_bitrate
            )

        elif config.codec.startswith("prores"):
            if not config.prores_profile or not config.prores_qscale:
                 self.log_callback('error', "ProRes profile and quality required")
                 return
            
            video_codec_params = [
                "-c:v", "prores_ks",
                "-profile:v", config.prores_profile,
                "-qscale:v", config.prores_qscale
            ]
        elif config.codec == "qtrle":
             output_pix_fmt = "rgb24"
             video_codec_params = ["-c:v", "qtrle"]
        
        # Timescale
        if out_num is not None:
            track_timescale = str(out_num)
        else:
             track_timescale = str(int(round(out_num_fps * 1000)))

        cmd += [
            "-pix_fmt", output_pix_fmt,
            "-video_track_timescale", track_timescale
        ]
        
        cmd += output_audio_handling_args
        cmd += video_codec_params
        
        cmd += [
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-colorspace", "bt709"
        ]

        if total_frames_needed:
            cmd += ["-frames:v", str(total_frames_needed)]
            
        cmd.append(output_path)

        self.log_callback('output', f"FFmpeg Command: {' '.join(cmd)}\n")
        
        # Execute
        self._execute_process(cmd, total_frames_needed)

    def _execute_process(self, cmd, total_frames_needed):
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
                self.log_callback('success', "Conversion complete!")
            else:
                 # Read remaining stderr if any
                remaining = self.process.stderr.read()
                self.log_callback('error', f"FFmpeg failed with code {self.process.returncode}.\n{remaining}")

        except Exception as e:
            self.log_callback('error', f"Execution error: {e}")
        finally:
            self.process = None

    def cancel(self):
        self.is_cancelled = True
        if self.process:
            self.process.terminate()
