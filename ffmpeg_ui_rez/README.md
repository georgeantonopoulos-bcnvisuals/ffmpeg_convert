# FFmpeg UI Rez Package

A Rez package for deploying the FFmpeg UI application.

## Overview

This package provides a convenient GUI for FFmpeg operations, packaged for deployment in a Rez environment.

## Dependencies

- Python 3.9+
- FFmpeg
- Tkinter
- Clique
- OpenImageIO

## Installation

1. First, ensure you have the tkinter rez package installed:
   ```bash
   cd /path/to/tkinter
   rez build
   rez install
   ```

2. Then build and install this package:
   ```bash
   cd /path/to/ffmpeg_ui_rez
   rez build
   rez install
   ```

## Usage

To use the FFmpeg UI:

```bash
rez env ffmpeg_ui -- ffmpeg-ui
```

Or, to start a shell with the package resolved:

```bash
rez env ffmpeg_ui
> ffmpeg-ui
```

## Deployment Instructions

1. System administrators should install Python's tkinter module on Rocky Linux 9 systems:
   ```bash
   sudo dnf install -y python3-tkinter
   ```

2. Set up both rez packages (tkinter and ffmpeg_ui) in a central location
   ```bash
   # For tkinter package
   cd /path/to/tkinter
   rez build
   rez install --prefix=/path/to/rez/packages
   
   # For ffmpeg_ui package
   cd /path/to/ffmpeg_ui_rez
   rez build
   rez install --prefix=/path/to/rez/packages
   ```

3. Users can then launch the application with:
   ```bash
   rez env ffmpeg_ui -- ffmpeg-ui
   ```

## Customization

The package installs the application to `$REZ_FFMPEG_UI_ROOT/python/` and creates a launcher script at `$REZ_FFMPEG_UI_ROOT/bin/ffmpeg-ui`. 