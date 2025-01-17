# FFmpeg GUI

A user-friendly graphical interface for FFmpeg, designed to simplify video conversion tasks with a modern dark theme.

## Features

- Convert image sequences to video with precise control
- Support for multiple codecs (H.264, H.265, ProRes, Animation)
- Adjustable frame rate and duration
- Professional-grade encoding settings
- Real-time conversion progress tracking
- Dark theme UI for comfortable use
- Settings persistence between sessions

## Requirements

- Python 3.x
- FFmpeg
- Tkinter (Python GUI library)
- Clique (for image sequence handling)

## Installation

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install clique
   ```
   For Linux users, you may need to install Tkinter:
   ```bash
   # Debian/Ubuntu
   sudo apt-get install python3-tk
   
   # Fedora/RHEL
   sudo dnf install python3-tkinter
   ```

## Usage

1. Run the application:
   ```bash
   python ffmpeg_ui.py
   ```
2. Select your input image sequence folder
3. Choose your desired codec and settings
4. Set the output location
5. Click "Run FFmpeg" to start the conversion

## Supported Codecs

- H.264 (High Profile)
- H.265/HEVC
- ProRes (422, 422 LT, 444)
- Animation (QTRLE) 