name = "ffmpeg_web"
version = "1.0.0"

description = "FFmpeg Web UI - A modern web-based interface for FFmpeg"

authors = ["BCN Visuals"]

requires = [
    "python-3.9+"
]

relocatable = True

build_system = "bash"

build_command = "bash {root}/build.sh"

def commands():
    """Configure runtime environment for the Rez package."""
    import os.path
    
    # Add the package root to PATH for the 'ffmpeg-web-ui' launcher
    env.PATH.prepend("{root}/bin")
    
    # Add the internal python directory to PYTHONPATH for bundled dependencies
    env.PYTHONPATH.prepend("{root}/python")
    
    # Create alias to run the launcher
    alias("ffmpeg-web-ui", "{root}/bin/ffmpeg-web-ui")
