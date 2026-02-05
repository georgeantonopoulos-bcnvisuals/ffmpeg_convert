#!/bin/bash
# make_bundle.sh - Script to build and bundle the ffmpeg_web Rez package

set -e

# 1. Build the Rez package
echo "Building Rez package..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
# Use a temporary local repository to avoid issues with @ in home path
LOCAL_REZ_PACKAGES="/tmp/george_rez_packages"
mkdir -p "$LOCAL_REZ_PACKAGES"

cd "$SCRIPT_DIR/ffmpeg_web"
rez build --install --prefix "$LOCAL_REZ_PACKAGES"

# 2. Create the bundle
BUNDLE_NAME="ffmpeg_web_bundle"
CONTEXT_FILE="ffmpeg_web.rxt"

export REZ_PACKAGES_PATH="$LOCAL_REZ_PACKAGES:/mnt/studio/pipeline/packages"

echo "Creating Rez context..."
rez env ffmpeg_web --output "$CONTEXT_FILE"

if [ -d "../$BUNDLE_NAME" ]; then
    echo "Removing existing bundle directory..."
    rm -rf "../$BUNDLE_NAME"
fi

echo "Bundling into $BUNDLE_NAME..."
rez-bundle -n "$CONTEXT_FILE" "../$BUNDLE_NAME"

# 3. Add a top-level run script to the bundle
# This script is designed to run even on machines WITHOUT Rez,
# assuming python3 is available in the system path.
cat << 'EOF' > "../$BUNDLE_NAME/run.sh"
#!/bin/bash
# run.sh - Standalone launcher for the bundled ffmpeg_web app
BUNDLE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# 1. Setup environment paths using the bundled packages
# ffmpeg_web-1.0.0 is the main package
PKG_ROOT="$BUNDLE_DIR/packages/ffmpeg_web/1.0.0"

export PATH="$PKG_ROOT/bin:$PATH"
export PYTHONPATH="$PKG_ROOT/python:$PYTHONPATH"

echo "Launching FFmpeg Web UI from bundle..."
echo "Uvicorn logs will follow:"
exec python3 -m uvicorn ffmpeg_web.main:app --host "0.0.0.0" --port "8000" "$@"
EOF

chmod +x "../$BUNDLE_NAME/run.sh"

echo "--------------------------------------------------"
echo "Bundle created successfully in $BUNDLE_NAME"
echo "To run on any machine with python3:"
echo "  1. Copy the directory $BUNDLE_NAME"
echo "  2. Run ./run.sh inside it"
echo "--------------------------------------------------"
