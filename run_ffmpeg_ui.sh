#!/bin/bash
# Wrapper script to launch FFmpeg UI reliably
# Ensures CWD is valid and environment is set up

# Resolve the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# cd to the script directory to ensure CWD is valid (fixes FileNotFoundError on import)
cd "$SCRIPT_DIR"

# Check if launching script exists
if [ ! -f "launch_ffmpeg_ui.py" ]; then
    echo "Error: launch_ffmpeg_ui.py not found in $SCRIPT_DIR"
    exit 1
fi

echo "Launching FFmpeg UI from $SCRIPT_DIR..."
# Run the python launcher
# We use the system python first to launch the Rez environment
python3 ./launch_ffmpeg_ui.py "$@"
