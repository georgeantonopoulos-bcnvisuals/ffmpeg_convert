name = "ffmpeg_ui"
version = "1.0.0"

description = "FFmpeg UI - A user-friendly graphical interface for FFmpeg"

authors = ["BCN Visuals"]

requires = [
    "tkinter",
    "openimageio",
    "opencolorio",
    "clique"  # From the launch script, we see this dependency
]

def commands():
    """Configure runtime environment for the Rez package.

    - Prepend the package's `bin` directory to `PATH` so the `ffmpeg-ui` entry
      point is available.
    - Prepend the package's `python` directory to `PYTHONPATH` so Python modules
      bundled with the package can be imported when running `ffmpeg_ui.py`.
    - Create a convenient `ffmpeg-ui` alias that invokes the launcher script.
    """
    import os.path
    
    # Add the package root to PATH
    env.PATH.prepend("{root}/bin")
    
    # Add the package's Python modules to PYTHONPATH
    env.PYTHONPATH.prepend("{root}/python")
    
    # Create alias to run the executable
    alias("ffmpeg-ui", "{root}/bin/ffmpeg-ui")

def pre_build_commands():
    """Ensure build-time Python dependencies are present.

    Currently we install `clique` which is used by the UI for sequence
    detection. This is a convenience for developers performing `rez build`.
    """
    # Make sure clique is installed
    import subprocess
    subprocess.check_call(["pip", "install", "clique"])

def post_install():
    """Copy required assets to the install area and create launcher.

    - Copies Python modules and theme assets into the package's `python`
      directory in the install root.
    - Writes a small launcher script `bin/ffmpeg-ui` that executes the UI from
      the installed package location.
    """
    import os
    import shutil
    
    # Source and destination paths
    root = os.environ["REZ_BUILD_SOURCE_PATH"]
    project_root = os.path.dirname(root)  # Go up one level to the main project directory
    install_root = os.environ["REZ_BUILD_INSTALL_PATH"]
    
    # Create target directories
    bin_dir = os.path.join(install_root, "bin")
    python_dir = os.path.join(install_root, "python")
    os.makedirs(bin_dir, exist_ok=True)
    os.makedirs(python_dir, exist_ok=True)
    
    # Copy Python files to the python directory
    for py_file in ["ffmpeg_ui.py", "convert_image_sequence.py", "ffmpeg_converter.py"]:
        src = os.path.join(project_root, py_file)
        dst = os.path.join(python_dir, py_file)
        if os.path.exists(src):
            print(f"Copying {src} to {dst}")
            shutil.copy2(src, dst)
    
    # Copy themes to the python directory
    for tcl_file in ["dark_theme.tcl", "rounded_buttons.tcl"]:
        src = os.path.join(project_root, tcl_file)
        dst = os.path.join(python_dir, tcl_file)
        if os.path.exists(src):
            print(f"Copying {src} to {dst}")
            shutil.copy2(src, dst)
    
    # Create a launcher script in bin directory
    launcher_path = os.path.join(bin_dir, "ffmpeg-ui")
    with open(launcher_path, "w") as f:
        f.write("""#!/bin/bash
python $REZ_FFMPEG_UI_ROOT/python/ffmpeg_ui.py "$@"
""")
    
    # Make the launcher executable
    os.chmod(launcher_path, 0o755) 
