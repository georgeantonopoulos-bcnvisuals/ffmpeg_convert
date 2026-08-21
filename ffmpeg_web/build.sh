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

# 4. Bundle binaries and an isolated oiiotool runtime.
echo "Bundling binaries and the complete oiiotool runtime..."
BIN_DIR="$REZ_BUILD_INSTALL_PATH/bin"
LIB_DIR="$REZ_BUILD_INSTALL_PATH/lib"
mkdir -p "$BIN_DIR"
mkdir -p "$LIB_DIR"

FFMPEG_SRC="/mnt/studio/pipeline/packages/ffmpeg/4.2.2+local.1.0.0/platform-linux/arch-x86_64/ffmpeg"
OIIO_ROOT="/mnt/studio/pipeline/packages/openimageio/2.4.15.0"
OIIOTOOL_SRC="$OIIO_ROOT/bin/oiiotool"
OIIO_LIBS="$OIIO_ROOT/lib64"
OCIO_LIBS="/mnt/studio/pipeline/packages/opencolorio/2.3.1/lib64"
RUNTIME_LIB_ROOT="${OIIO_RUNTIME_LIB_ROOT:-/lib64}"
RUNTIME_BUNDLER="$REZ_BUILD_SOURCE_PATH/../scripts/bundle_oiio_runtime.py"

if [ -f "$FFMPEG_SRC" ]; then
    cp "$FFMPEG_SRC" "$BIN_DIR/ffmpeg"
    chmod +x "$BIN_DIR/ffmpeg"
fi

if [ -f "$OIIOTOOL_SRC" ]; then
    cp "$OIIOTOOL_SRC" "$BIN_DIR/oiiotool.real"
    chmod +x "$BIN_DIR/oiiotool.real"

    "$PYTHON_EXE" "$RUNTIME_BUNDLER" \
        --executable "$BIN_DIR/oiiotool.real" \
        --output-dir "$LIB_DIR" \
        --search-dir "$OIIO_LIBS" \
        --search-dir "$OCIO_LIBS" \
        --search-dir "$RUNTIME_LIB_ROOT" \
        --search-dir /lib64 \
        --search-dir /usr/lib64 \
        --manifest "$REZ_BUILD_INSTALL_PATH/oiio-runtime-manifest.txt"

    cat > "$BIN_DIR/oiiotool" << 'EOF'
#!/bin/bash
set -e
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_LIBRARY_PATH="$BIN_DIR/../lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$BIN_DIR/oiiotool.real" "$@"
EOF
    chmod +x "$BIN_DIR/oiiotool"
else
    echo "ERROR: oiiotool was not found at $OIIOTOOL_SRC" >&2
    exit 1
fi

# This must execute the binary, not merely find it on PATH.  It catches
# missing transitive libraries before a package is distributed.
env -i PATH=/usr/bin:/bin HOME=/tmp "$BIN_DIR/oiiotool" --version

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
