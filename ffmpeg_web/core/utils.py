import math
from typing import Tuple, Optional

def normalize_fps(fps_value_str: str) -> Tuple[float, str, Optional[int], Optional[int]]:
    """Return normalized FPS representations for FFmpeg and numeric math.

    Returns:
    - numeric_fps (float): high-precision numeric value for math
    - ffmpeg_fps_str (str): value to pass to FFmpeg (rational or decimal)
    - num (int|None), den (int|None): numerator/denominator if NTSC match, else None
    """
    try:
        value = float(str(fps_value_str).strip())
    except Exception:
        return 0.0, str(fps_value_str), None, None

    # Known NTSC-like rates mapping
    ntsc_map = {
        23.976: (24000, 1001),
        29.97: (30000, 1001),
        47.952: (48000, 1001),
        59.94: (60000, 1001),
        119.88: (120000, 1001),
        14.985: (15000, 1001),
    }
    tol = 1e-3
    for approx, (n, d) in ntsc_map.items():
        if abs(value - approx) < tol:
            return n / d, f"{n}/{d}", n, d

    # No match: use decimal
    return value, f"{value}", None, None

def calculate_duration_and_frames(source_fps: str, output_fps: str, desired_duration: str) -> Tuple[Optional[float], Optional[int]]:
    """Calculate scale factor and total frames needed based on duration.
    
    Returns:
        scale_factor (float | None): Time scaling factor
        total_frames_needed (int | None): Number of output frames
    """
    try:
        src_fps_val = float(source_fps)
        out_fps_val = float(output_fps)
        duration_val = float(desired_duration)

        if src_fps_val <= 0 or out_fps_val <= 0 or duration_val <= 0:
            return None, None

        # Total frames required for the requested duration
        total_frames_needed = int(math.ceil(out_fps_val * duration_val))
        
        # We can't calculate exact scale factor here without knowing total source frames
        # This will be done in the FFmpeg handler where total source frames are known
        return None, total_frames_needed

    except ValueError:
        return None, None
