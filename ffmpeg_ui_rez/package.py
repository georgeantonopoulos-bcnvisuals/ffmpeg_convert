name = "ffmpeg_ui"
version = "1.0.0"

description = "FFmpeg UI - A user-friendly graphical interface for FFmpeg"

authors = ["BCN Visuals"]

requires = [
    "tkinter",
    "openimageio"  # From the launch script, we see this dependency
]

def commands():
    import os.path
    
    # Add the package root to PATH
    env.PATH.prepend("{root}/bin")
    
    # Add the package's Python modules to PYTHONPATH
    env.PYTHONPATH.prepend("{root}/python")
    
    # Create alias to run the executable
    alias("ffmpeg-ui", "{root}/bin/ffmpeg-ui")

def pre_build_commands():
    # Make sure clique is installed
    import subprocess
    subprocess.check_call(["pip", "install", "clique"])

def post_install():
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