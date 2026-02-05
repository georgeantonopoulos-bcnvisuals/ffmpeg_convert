#!/bin/bash
# build.sh - Build script for ffmpeg_web Rez package

set -e

# Use python3 as default if REZ_BUILD_PYTHON_EXECUTABLE is not set
PYTHON_EXE=${REZ_BUILD_PYTHON_EXECUTABLE:-python3}

echo "Starting build for ffmpeg_web..."
echo "Using Python: $PYTHON_EXE"

# 1. Create target directories
BIN_DIR="$REZ_BUILD_INSTALL_PATH/bin"
PYTHON_DIR="$REZ_BUILD_INSTALL_PATH/python"

mkdir -p "$BIN_DIR"
mkdir -p "$PYTHON_DIR"

# 2. Copy the ffmpeg_web source code
# Note: REZ_BUILD_SOURCE_PATH is ffmpeg_convert/ffmpeg_web
echo "Copying source from $REZ_BUILD_SOURCE_PATH to $PYTHON_DIR/ffmpeg_web"
# We use -L to follow symlinks if any, and -p to preserve permissions
cp -rL "$REZ_BUILD_SOURCE_PATH" "$PYTHON_DIR/ffmpeg_web"

# Clean up any build artifacts if they were copied
rm -rf "$PYTHON_DIR/ffmpeg_web/build"
rm -f "$PYTHON_DIR/ffmpeg_web/package.py"
rm -f "$PYTHON_DIR/ffmpeg_web/build.sh"

# 3. Bundle additional pip dependencies into the package's python directory
echo "Bundling pip dependencies to $PYTHON_DIR..."
"$PYTHON_EXE" -m pip install \
    fastapi \
    uvicorn \
    pydantic \
    websockets \
    python-multipart \
    clique \
    --target "$PYTHON_DIR"

# 4. Bundle ffmpeg binary manually since Rez package is broken
echo "Bundling ffmpeg binary..."
FFMPEG_SRC="/mnt/studio/pipeline/packages/ffmpeg/4.2.2+local.1.0.0/platform-linux/arch-x86_64/ffmpeg"
if [ -f "$FFMPEG_SRC" ]; then
    cp "$FFMPEG_SRC" "$BIN_DIR/ffmpeg"
    chmod +x "$BIN_DIR/ffmpeg"
else
    echo "Warning: Could not find ffmpeg binary at $FFMPEG_SRC, falling back to system ffmpeg"
    cp "$(which ffmpeg)" "$BIN_DIR/ffmpeg"
fi

# 5. Create a launcher script in bin directory
LAUNCHER_PATH="$BIN_DIR/ffmpeg-web-ui"
echo "Creating launcher at $LAUNCHER_PATH"

cat << 'EOF' > "$LAUNCHER_PATH"
#!/bin/bash
# Ensure the bundled python deps are in the path
export PYTHONPATH="$REZ_FFMPEG_WEB_ROOT/python:$PYTHONPATH"
# Launch the FastAPI app using uvicorn
# We use the python from the environment to run uvicorn
exec python3 -m uvicorn ffmpeg_web.main:app --host "0.0.0.0" --port "8000" "$@"
EOF

chmod +x "$LAUNCHER_PATH"

echo "Build complete."
