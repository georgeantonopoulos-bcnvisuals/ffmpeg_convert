#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Source file in the same directory as the script
SOURCE_FILE="$SCRIPT_DIR/ffmpeg_ui.py"

# Destination path
DESTINATION_FILE="/mnt/studio/pipeline/packages/ffmpeg_UI/1.0.0/python/ffmpeg_ui.py"
DESTINATION_DIR="$(dirname "$DESTINATION_FILE")"

# Check if source file exists
if [ ! -f "$SOURCE_FILE" ]; then
    echo "Error: Source file not found at $SOURCE_FILE"
    exit 1
fi

# Create destination directory if it doesn't exist
mkdir -p "$DESTINATION_DIR"

# Copy the file, overwriting the destination
cp -f "$SOURCE_FILE" "$DESTINATION_FILE"

if [ $? -eq 0 ]; then
    echo "Successfully copied $SOURCE_FILE to $DESTINATION_FILE"
else
    echo "Error: Failed to copy $SOURCE_FILE to $DESTINATION_FILE"
    exit 1
fi

# Make the destination script executable (optional, but good practice if it's a tool)
chmod +x "$DESTINATION_FILE"

if [ $? -eq 0 ]; then
    echo "Successfully made $DESTINATION_FILE executable."
else
    echo "Warning: Failed to make $DESTINATION_FILE executable."
fi

echo "Update process complete." 