import os
import subprocess
import threading
import re
import asyncio
from typing import Optional, Callable
from pydantic import BaseModel
from .utils import normalize_fps, calculate_duration_and_frames

class FFmpegJobConfig(BaseModel):
    input_folder: str
    filename_pattern: str
    output_folder: str
    output_filename: str
    frame_rate: str
    source_frame_rate: str
    desired_duration: str
    codec: str
    mp4_bitrate: Optional[str] = None
    prores_profile: Optional[str] = None
    prores_qscale: Optional[str] = None
    audio_option: str = "No Audio"
    start_frame: int
    end_frame: int

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
        
        setpts_filter = f"setpts={scale_factor:.10f}*PTS"
        ffmpeg_filters_str = f"{setpts_filter},fps={out_ffmpeg_fps_str},scale=in_color_matrix=bt709:out_color_matrix=bt709"
        cmd += ["-vf", ffmpeg_filters_str]

        # Codec & Pixel Format
        output_pix_fmt = "yuv420p"
        video_codec_params = []
        
        if config.codec in ["h264", "h265"]:
            if not config.mp4_bitrate:
                self.log_callback('error', "Bitrate required for H.264/H.265")
                return
            
            codec_lib = "libx264" if config.codec == "h264" else "libx265"
            cb = f"{float(config.mp4_bitrate):.0f}M"
            
            video_codec_params = [
                "-c:v", codec_lib,
                "-preset", "medium",
                "-b:v", cb,
                "-minrate", cb,
                "-maxrate", cb,
                "-bufsize", cb,
            ]
            if config.codec == "h264":
                video_codec_params.extend([
                    "-x264-params", "nal-hrd=cbr",
                    "-profile:v", "high",
                    "-level:v", "5.1",
                ])
            else:
                video_codec_params.extend(["-tag:v", "hvc1"])
                
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
