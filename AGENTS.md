# FFmpeg GUI - Codebase Synopsis & Deployment Strategy

## 1. Codebase Synopsis

### Overview
This application is a Python-based Graphical User Interface (GUI) for **FFmpeg**, specifically tailored for studio production workflows. It handles complex tasks such as **ACES color space conversion**, image sequence processing, and professional codec encoding (ProRes, H.264, H.265).

### Key Components
- **`ffmpeg_ui.py`**: The primary entry point and GUI logic. It uses `tkinter` for the interface and manages external processes.
- **`convert_image_sequence.py` / `ffmpeg_converter.py`**: Logic for handling image sequences and constructing FFmpeg command lines.
- **`dark_theme.tcl` / `rounded_buttons.tcl`**: Custom TCL scripts to provide a premium dark-themed aesthetic to the Tkinter interface.
- **External Dependencies**:
  - **FFmpeg**: For video encoding.
  - **OpenImageIO (`oiiotool`)**: Used for EXR sequence processing and color space transformations.
  - **`clique`**: A Python library for parsing and assembling file sequences.
  - **OCIO**: OpenColorIO configuration (currently hardcoded to `/mnt/studio/config/ocio/aces_1.2/config.ocio`).

### Current Challenges
1. **Rez & SMB2 Symlink Limitation**: The current Rez-based setup relies on filesystem symbolic links for package resolution. SMB2 network shares (especially when configured for cross-platform compatibility) often do not support symlinks, causing Rez envs to fail.
2. **Dependency Complexity**: The app requires specific versions of FFmpeg and OpenImageIO libraries. Relying on "host" libraries across different machines (Rocky 9.4, Rocky 9.6, Ubuntu, etc.) leads to `libOpenImageIO.so` not found or GLIBC version mismatch errors.
3. **Apptainer Hybrid Failure**: Previous attempts to use Apptainer failed likely because they tried to mount host-specific Rez packages (built for Rocky 9) into an Ubuntu-based container environment.

---

## 2. Known Issues & Fixes

### TCL Theme Loading Errors (Fixed Dec 2025)

**Symptoms:**
- `_tkinter.TclError` when loading `rounded_buttons.tcl` or `dark_theme.tcl`
- Segmentation fault when launching via `launch_ffmpeg_UI.sh`
- Error: `no files matched glob pattern "*.png"`
- Error: `can't find package ttk::theme::dark`

**Root Cause:**
The original TCL theme files attempted to load PNG button images, but the Tk installation from the `tkinter_libs` Rez package does not include the `Img` extension needed for PNG support. Tk 8.6 only natively supports GIF and PPM/PGM formats.

The `dark_theme.tcl` had two issues:
1. Line 21: `LoadImages [file join [file dirname [info script]] dark]` tried to load PNGs from a non-existent `dark/` subdirectory
2. The theme creation referenced `$I(button-normal)` etc., but these image arrays were never populated

**Solution:**
Rewrote `dark_theme.tcl` to use Tk's native `clam` theme as a parent and style it with colors only (no custom images). This approach:
- Works with any Tk 8.6 installation
- Doesn't require the `Img` package or external image files
- Provides a clean dark theme appearance

**Files Modified:**
- `dark_theme.tcl`: Complete rewrite using color-based styling only
- `rounded_buttons.tcl`: Converted to no-op placeholder for compatibility

---

## 3. Proposed Deployment Solutions

### Option 1: Standalone Binary (PyInstaller / Nuitka) - *Recommended*
This approach bundles the Python interpreter, all required modules, and even the `ffmpeg`/`oiiotool` binaries into a single executable file.

- **How it works**: At runtime, the executable extracts its contents to a local temporary directory (e.g., `/tmp/_MEIxxxx`). Since `/tmp` is a local Linux filesystem, it supports symlinks and high-speed I/O.
- **Why it solves the problem**: 
    - No symlinks are stored on the SMB share.
    - All dependencies are bundled; the user doesn't need Python or Rez installed.
    - It works across any machine sharing the same base OS architecture (e.g., any Rocky 9 or RHEL-based workstation).
- **Implementation Note**: You would use a `spec` file to include the data files (`.tcl`) and binaries (`ffmpeg`, `oiiotool`, and their `.so` libraries).

### Option 2: Apptainer "Fat" Image (SIF)
Create a fully self-contained Apptainer image (`.sif`) that includes every dependency inside the container.

- **How it works**: Instead of binding `/mnt/studio/pipeline/packages` (Rez), the build process `apt-get` or `dnf` installs FFmpeg and OIIO directly into the image.
- **Why it solves the problem**:
    - A `.sif` file is a single flat file on the SMB share. 
    - The internal squashfs filesystem handles symlinks perfectly.
    - It provides a 100% predictable environment regardless of the host machine's library state.
- **Requirement**: Client machines must have `apptainer` installed.

### Option 3: Portable Environment "Bundle" (Conda-Pack / Venv-Pack)
Create a relocatable directory containing a full Python environment and all binaries, but with symlinks replaced by actual files.

- **How it works**: Use a tool like `conda-pack` with the `--no-pyc` and careful handling to ensure no symlinks exist in the final folder.
- **Why it solves the problem**: Allows running directly from the share without extraction.
- **Cons**: Extremely difficult to maintain, as many Python libraries and system `.so` files rely on symlink chains (e.g., `libfoo.so -> libfoo.so.1`). **Not recommended** for SMB2 shares due to this fragility.

---

## 4. Comparison Matrix

| Feature | PyInstaller (Binary) | Apptainer (Fat SIF) | Portable Folder |
| :--- | :--- | :--- | :--- |
| **SMB2 Compatible** | Yes (Single File) | Yes (Single File) | No (Symlink issues) |
| **Zero-Install** | Yes | No (Needs Apptainer) | Yes |
| **Isolation** | High | Very High | Medium |
| **Maintenance** | Re-build on update | Re-build on update | Manual File Sync |
| **Performance** | Slight extraction delay | Native Speed | Native Speed |

---

## 5. Final Recommendation

**Option 1 (PyInstaller One-File)** is the most versatile solution for a studio SMB share. It removes the need for Rez entirely and delivers a "click-and-run" experience for all users regardless of their local machine configuration.

**Alternative**: If the studio already relies heavily on Apptainer, **Option 2** is the most "correct" engineering approach, provided you stop referencing host-side Rez packages and move all logic *inside* the container build.

---

## 6. File Structure

```
ffmpeg_convert/
├── ffmpeg_ui.py           # Main application entry point
├── ffmpeg_converter.py    # FFmpeg command builder
├── dark_theme.tcl         # TTK dark theme (color-only, no images)
├── rounded_buttons.tcl    # Placeholder for compatibility
├── launch_ffmpeg_UI.sh    # Rez environment launcher
├── _internal_launcher.sh  # Internal launcher script (called by launch_ffmpeg_UI.sh)
├── ffmpeg_settings.json   # User settings persistence
└── tmp_files/             # Temporary conversion files
```
