import json
import os
from typing import Dict, Any

SETTINGS_FILE = 'ffmpeg_settings.json'

DEFAULT_SETTINGS = {
    "last_input_folder": "",
    "last_output_folder": "",
    "frame_rate": "60",
    "source_frame_rate": "60",
    "desired_duration": "15",
    "codec": "h265",
    "mp4_bitrate": "30",
    "prores_profile": "2",  # 422
    "prores_qscale": "9"
}

def load_settings() -> Dict[str, Any]:
    """Load settings from JSON file, or create with defaults if not exists"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # Update with any missing default settings
                for key, value in DEFAULT_SETTINGS.items():
                    if key not in settings:
                        settings[key] = value
                return settings
        return DEFAULT_SETTINGS.copy()
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_SETTINGS.copy()

def save_settings(new_settings: Dict[str, Any]) -> None:
    """Save settings to JSON file"""
    # Load existing to preserve keys not in new_settings if any (merge strategy)
    current_settings = load_settings()
    current_settings.update(new_settings)
    
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(current_settings, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")
