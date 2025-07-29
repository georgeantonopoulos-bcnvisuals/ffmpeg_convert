#!/usr/bin/env python3

import subprocess
import sys
import os

def launch_ui():
    try:
        cmd = ["rez", "env", "openimageio", "opencolorio", "tkinter", "clique", "--", "python", os.path.abspath("ffmpeg_ui.py")]
        print(f"Running: {' '.join(cmd)}")
        
        # Remove PIPE capture and let output flow through directly
        process = subprocess.Popen(
            cmd,
            stdout=sys.stdout,  # Direct to current stdout
            stderr=sys.stderr   # Direct to current stderr
        )
        
        print("FFmpeg UI process started with PID:", process.pid)
        process.wait()  # Wait for process to complete
        
        print(f"\nProcess exited with code {process.returncode}")
        sys.exit(process.returncode)
            
    except KeyboardInterrupt:
        print("\nUI terminated by user", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    launch_ui() 