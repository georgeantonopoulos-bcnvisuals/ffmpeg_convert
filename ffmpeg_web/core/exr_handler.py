import os
import subprocess
import shutil
import time
from typing import Callable, List, Tuple
from concurrent.futures import ThreadPoolExecutor

class ExrHandler:
    def __init__(self, log_callback: Callable[[str, str], None]):
        self.log_callback = log_callback
        self.is_cancelled = False
        self.temp_dir = ""
        self.active_processes = []
        
        # Hardcoded from original script
        self.ocio_config = "/mnt/studio/config/ocio/aces_1.2/config.ocio"

    def convert_exr_sequence(self, 
                           input_folder: str, 
                           pattern: str, 
                           start_frame: int, 
                           end_frame: int, 
                           color_space: str = "ACES - ACEScg") -> str:
        """
        Convert EXR sequence to PNGs in a temp directory.
        Returns the path to the temp directory on success, or empty string on failure.
        """
        self.is_cancelled = False
        self.active_processes = []

        # 1. Setup Temp Dir
        prefix = pattern.split('%')[0]
        self.temp_dir = os.path.join(input_folder, f"ffmpeg_web_tmp_{int(time.time())}")
        
        try:
            os.makedirs(self.temp_dir, exist_ok=True)
            self.log_callback('output', f"Created temp directory: {self.temp_dir}\n")
        except Exception as e:
            # Fallback to /tmp
            self.temp_dir = os.path.join("/tmp", f"ffmpeg_web_tmp_{int(time.time())}")
            try:
                os.makedirs(self.temp_dir, exist_ok=True)
                self.log_callback('output', f"Created fallback temp directory: {self.temp_dir}\n")
            except Exception as e2:
                self.log_callback('error', f"Failed to create temp directory: {e2}")
                return ""

        # 2. Identify missing frames
        missing_frames = []
        # pattern e.g. "shot_010_%04d.exr"
        # We need to construct input/output filenames
        
        # Determine strict "before" part for output naming (e.g. "shot_010_")
        # Assuming pattern is standard printf style
        before = pattern.split('%')[0] 

        cmds: List[Tuple[List[str], int]] = []
        
        for frame in range(start_frame, end_frame + 1):
            # Construct input filename
            # Note: This simple replacement assumes %04d style. 
            # Ideally use formatting, but we need to match the exact placeholder logic
            # from the UI which replaces %04d with {frame:04d}
            
            # Simple substitution strategy (robust enough for standard %04d)
            if "%04d" in pattern:
                input_file_name = pattern.replace("%04d", f"{frame:04d}")
            elif "%03d" in pattern:
                input_file_name = pattern.replace("%03d", f"{frame:03d}")
            else:
                 # fallback for other patterns if needed, or error
                 input_file_name = pattern % frame 
                 
            input_file = os.path.join(input_folder, input_file_name)
            output_file = os.path.join(self.temp_dir, f"{before}{frame:04d}.png")

            if os.path.exists(output_file):
                continue
            
            if not os.path.exists(input_file):
                self.log_callback('error', f"Input frame missing: {input_file}")
                return ""

            cmd = [
                "oiiotool",
                "-v",
                "--colorconfig", self.ocio_config,
                "--threads", "1",
                input_file,
                "--ch", "R,G,B",
                "--colorconvert", color_space, "Output - sRGB",
                "-d", "uint8",
                "--compression", "none",
                "--no-clobber",
                "-o", output_file
            ]
            cmds.append((cmd, frame))

        if not cmds:
            self.log_callback('output', "All frames already converted/exist.\n")
            return self.temp_dir

        total_files = len(cmds)
        completed_files = 0
        
        self.log_callback('output', f"Starting conversion of {total_files} EXR frames...\n")

        # 3. Execute in ThreadPool
        max_workers = min(os.cpu_count() or 4, 8)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for cmd_info in cmds:
                if self.is_cancelled:
                    break
                future = executor.submit(self._process_single_frame, cmd_info)
                futures.append(future)
            
            # Monitor progress
            for future in futures:
                if self.is_cancelled:
                    break
                
                result = future.result() # (frame, return_code, error)
                if result[1] != 0:
                    self.log_callback('error', f"Frame {result[0]} failed: {result[2]}")
                    self.cancel()
                    return ""
                
                completed_files += 1
                progress = (completed_files / total_files) * 100
                self.log_callback('progress', str(progress))
        
        if self.is_cancelled:
            self.log_callback('cancelled', "EXR conversion cancelled.")
            return ""
            
        return self.temp_dir

    def _process_single_frame(self, cmd_info):
        """Run ``oiiotool`` for a single frame and return its result tuple."""
        cmd, frame_num = cmd_info
        if self.is_cancelled:
            return (frame_num, -1, "Cancelled")
            
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            self.active_processes.append(process)
            stdout, stderr = process.communicate()
            
            if process in self.active_processes:
                self.active_processes.remove(process)
                
            return (frame_num, process.returncode, stderr)
        except Exception as e:
            return (frame_num, -1, str(e))

    def cancel(self):
        """Signal all active EXR conversion processes to terminate."""
        self.is_cancelled = True
        for p in self.active_processes:
            try:
                p.terminate()
            except Exception:
                # Best-effort termination; ignore individual failures.
                continue
        self.active_processes = []
        
    def cleanup(self):
        """Remove the temporary directory created for EXR conversion, if any."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                self.log_callback('output', f"Cleaned up temp dir: {self.temp_dir}\n")
            except Exception as e:
                self.log_callback('output', f"Warning: Failed to cleanup temp dir: {e}\n")
