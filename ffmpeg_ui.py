print("Debug: ffmpeg_ui.py script started")  # <-- ADD THIS LINE at the VERY TOP of the file

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import re
import clique
import json
import threading
from tkinter.font import Font
import queue
import sys
import glob  # Added for globbing converted files
import select, fcntl, time
import signal  # Add at the top with other imports
import shutil  # Add import for directory operations

# Add at top with other imports
try:
    from ttkthemes import ThemedStyle  # pip install ttkthemes
except ImportError:
    ThemedStyle = None

# Create a custom logger class to duplicate output
class TeeLogger:
    def __init__(self, filename, mode='a', stream=None):
        self.file = open(filename, mode)
        self.stream = stream if stream else sys.stdout
        
    def write(self, data):
        self.file.write(data)
        self.file.flush()
        self.stream.write(data)
        self.stream.flush()
        
    def flush(self):
        self.file.flush()
        self.stream.flush()

# Redirect stdout/stderr to both log files and console
sys.stdout = TeeLogger('ffmpeg_ui.log', 'a', sys.stdout)
sys.stderr = TeeLogger('ffmpeg_ui.error.log', 'a', sys.stderr)

# Default settings
DEFAULT_SETTINGS = {
    "last_input_folder": "",
    "last_output_folder": "",
    "frame_rate": "60",
    "source_frame_rate": "60",  # Added source frame rate
    "desired_duration": "15",
    "codec": "h265",
    "mp4_bitrate": "30",
    "mp4_crf": "23",
    "prores_profile": "2",  # 422
    "prores_qscale": "9"
}

def check_and_install_dependencies():
    def install_package(package):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            return True
        except subprocess.CalledProcessError:
            return False

    # Check for oiiotool
    try:
        oiiotool_result = subprocess.run(['which', 'oiiotool'], capture_output=True, text=True)
        if oiiotool_result.returncode != 0:
            print("ERROR: oiiotool not found in system path!")
            print("Please install OpenImageIO tools using your package manager:")
            print("For CentOS/RHEL: sudo dnf install OpenImageIO-tools")
            print("For Ubuntu/Debian: sudo apt-get install openimageio-tools")
            sys.exit(1)
        else:
            print(f"Found oiiotool at: {oiiotool_result.stdout.strip()}")
    except Exception as e:
        print(f"Error checking for oiiotool: {e}")
        print("Please ensure OpenImageIO tools are installed.")
        sys.exit(1)

    # Check for tkinter
    try:
        import tkinter
    except ImportError:
        print("Tkinter not found. Installing tkinter...")
        if sys.platform.startswith('linux'):
            print("On Linux systems, tkinter needs to be installed via system package manager.")
            print("Please run: sudo apt-get install python3-tk (for Debian/Ubuntu)")
            print("Or: sudo dnf install python3-tkinter (for Fedora/RHEL)")
            sys.exit(1)
        else:
            if not install_package('tk'):
                print("Failed to install tkinter. Please install it manually.")
                sys.exit(1)

    # Check for clique
    try:
        import clique
    except ImportError:
        print("Clique not found. Installing clique...")
        if not install_package('clique'):
            print("Failed to install clique. Please install it manually.")
            sys.exit(1)

    print("All dependencies are installed successfully!")


class FFmpegUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FFmpeg GUI")
        self.root.configure(bg='#2b2b2b')
        self.root.geometry("850x950") # Adjusted geometry for new layout
        self.root.minsize(700, 600)    # Set minimum window size

        # Create tmp_files directory in script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_temp_dir = os.path.join(script_dir, "tmp_files")
        if not os.path.exists(self.base_temp_dir):
            os.makedirs(self.base_temp_dir)

        # Store active processes and their reader threads
        self.active_processes = []
        self.active_threads = []
        self.is_shutting_down = False  # Add flag to prevent multiple cleanup attempts
        self.last_successful_output_dir = None # For "Open Output Folder" button
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Add cleanup handler for window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Load settings
        self.settings = self.load_settings()
        
        self.original_exr_path = None # Initialize placeholder for original EXR path

        # Initialize the queue for thread-safe communication
        self.queue = queue.Queue()

        # Custom font
        self.custom_font = Font(family="Roboto", size=10)
        self.title_font = Font(family="Roboto", size=11, weight="bold") # Slightly smaller title for LabelFrames

        # Set up dark theme
        self.style = ttk.Style()
        #self.style.theme_use("clam")

        # Load the custom TCL files
        script_dir = os.path.dirname(os.path.abspath(__file__))
        rounded_buttons_path = os.path.join(script_dir, "rounded_buttons.tcl")
        dark_theme_path = os.path.join(script_dir, "dark_theme.tcl")

        try:
            self.root.tk.call("source", rounded_buttons_path)
            self.root.tk.call("source", dark_theme_path)
            self.style.theme_use("dark")  # Use the dark theme after loading
        except tk.TclError as e:
            print(f"Error loading TCL files: {e}")
            # Fallback to basic styling if TCL files fail to load
            self.style.configure(".",
                                 background="#2b2b2b",
                                 foreground="#ffffff",
                                 fieldbackground="#3c3f41",
                                 font=self.custom_font)
        
        # General widget styling enhancements
        self.style.configure("TEntry", 
                             relief="flat", 
                             borderwidth=1, 
                             bordercolor="#555555", # Subtle border for entries
                             fieldbackground="#3c3f41",
                             foreground="#ffffff",
                             insertbackground="#ffffff") # Cursor color
        self.style.map("TEntry",
                       bordercolor=[('focus', '#777777')]) # Border color on focus

        self.style.configure("TCombobox", 
                             relief="flat", 
                             borderwidth=1,
                             bordercolor="#555555",
                             arrowcolor="#ffffff",
                             foreground="#ffffff")
        self.style.map("TCombobox",
                       bordercolor=[('focus', '#777777')],
                       selectbackground=[('readonly', '#4a4a4a')], # Slightly lighter selection
                       selectforeground=[('readonly', '#ffffff')],
                       fieldbackground=[('readonly', '#3c3f41')],
                       background=[('readonly', '#3c3f41')])

        # Additional modern styling for common widgets
        self.style.configure("TLabel",    background="#2b2b2b", foreground="#ffffff")
        self.style.configure("TFrame",    background="#2b2b2b")
        self.style.configure("TCheckbutton", background="#2b2b2b", foreground="#ffffff")
        self.style.configure("TRadiobutton", background="#2b2b2b", foreground="#ffffff")
        self.style.configure("TMenubutton",  relief="flat", borderwidth=1, background="#3c3f41", foreground="#ffffff")

        # Button style with outline and round edges (complementing TCL)
        self.style.configure("TButton",
                             padding=6,
                             relief="flat",
                             background="#4a4a4a", # Slightly lighter button background
                             foreground="#ffffff",
                             borderwidth=1,
                             bordercolor="#666666", # Subtle border for buttons
                             focusthickness=0) # Remove focus ring if TCL handles it
        self.style.map("TButton",
                       background=[('active', '#5c5c5c'), ('pressed', '#5c5c5c')],
                       bordercolor=[('active', '#888888')])
        
        # Configure grid
        # self.root.grid_columnconfigure(1, weight=1) # Old configuration
        # for i in range(12):  # Increased range to accommodate new widgets # Old configuration
        #     self.root.grid_rowconfigure(i, weight=1) # Old configuration

        # Configure progress bar style
        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor='#2b2b2b',
            background='#00ff00',
            darkcolor='#00cc00',
            lightcolor='#00ee00',
            bordercolor='#2b2b2b'
        )

        # Configure Combobox style for dark selection
        self.style.map('TCombobox',
            selectbackground=[('readonly', '#404040')],
            selectforeground=[('readonly', '#ffffff')],
            fieldbackground=[('readonly', '#2b2b2b')],
            background=[('readonly', '#2b2b2b')]
        )
        
        # ttk.LabelFrame style
        self.style.configure("TLabelframe", 
                             padding=10, 
                             relief="solid", # Cleaner relief
                             borderwidth=1,
                             bordercolor="#444444", # Darker border for labelframe
                             background="#2b2b2b")
        self.style.configure("TLabelframe.Label", 
                             font=self.title_font, 
                             foreground="#dddddd", # Brighter label text
                             background="#2b2b2b",
                             padding=(0,0,0,5)) # Add some bottom padding to label title


        # --- Main Layout ---
        # Configure root grid for the main LabelFrames
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=0) # Input Settings
        self.root.grid_rowconfigure(1, weight=0) # Output & Codec Settings
        self.root.grid_rowconfigure(2, weight=1) # Process & Log

        # --- Input Settings Frame ---
        input_settings_frame = ttk.LabelFrame(self.root, text="Input Settings")
        input_settings_frame.grid(row=0, column=0, sticky="nsew", padx=15, pady=(15,10)) # Increased padding
        input_settings_frame.grid_columnconfigure(1, weight=1) # Allow entry fields to expand

        current_row_input = 0
        self.input_type_var, self.input_type_dropdown = self._create_labeled_combobox(
            input_settings_frame, "Input Type:", row=current_row_input,
            default_value="Image Sequence", values=["Image Sequence"], state="readonly",
            columnspan_combo=2 # Span 2 columns including potential browse button space
        )
        current_row_input += 1

        self.img_seq_folder_var, self.img_seq_folder_entry, _ = self._create_labeled_entry(
            input_settings_frame, "Image Sequence Folder:", row=current_row_input,
            default_value=self.settings.get("last_input_folder", ""), 
            browse_command=self.browse_img_seq,
            columnspan_entry=1 # Entry spans 1, browse button takes the next
        )
        # Manually assign to self.img_seq_folder for compatibility with existing code
        self.img_seq_folder = self.img_seq_folder_entry 
        current_row_input += 1

        self.filename_pattern_var, self.filename_pattern_entry = self._create_labeled_entry(
            input_settings_frame, "Filename Pattern:", row=current_row_input,
            columnspan_entry=2 # Span 2 columns as there's no browse button
        )
        self.filename_pattern = self.filename_pattern_entry # Compatibility
        current_row_input += 1

        self.source_frame_rate_var, self.source_frame_rate_entry = self._create_labeled_entry(
            input_settings_frame, "Source Frame Rate (fps):", row=current_row_input,
            default_value=self.settings.get("source_frame_rate", "60"),
            bind_event="<KeyRelease>", bind_callback=self.update_duration,
            columnspan_entry=2
        )
        self.source_frame_rate = self.source_frame_rate_entry # Compatibility
        current_row_input += 1
        
        # ACES Frame (conditionally shown)
        self.aces_frame = ttk.Frame(input_settings_frame) # Parent is input_settings_frame
        self.aces_frame.grid(row=current_row_input, column=0, columnspan=3, sticky="ew", padx=0, pady=0) 
        self.aces_frame.grid_columnconfigure(1, weight=1)
        self.color_spaces = [
            "ACES - ACEScg", "ACES - ACES2065-1", "Input - ARRI - Linear - ALEXA Wide Gamut",
            "Input - RED - Linear - REDWideGamutRGB", "Input - Sony - Linear - S-Gamut3",
            "Input - Sony - Linear - S-Gamut3.Cine", "Input - Canon - Linear - Canon Cinema Gamut Daylight",
            "Utility - Linear - Rec.709", "Utility - Linear - sRGB"
        ]
        self.color_space_var, self.color_space_dropdown = self._create_labeled_combobox(
            self.aces_frame, "EXR Color Space:", row=0, # Relative row within aces_frame
            default_value="ACES - ACEScg", values=self.color_spaces, state="readonly",
            columnspan_combo=1, width=38 
        )
        self.color_space_dropdown['values'] = self.color_spaces # Ensure values are set
        self.aces_frame.grid_remove() # Initially hidden
        current_row_input += 1 # Increment row for input_settings_frame

        # Temp Directory Frame (conditionally shown)
        self.temp_dir_frame = ttk.Frame(input_settings_frame) # Parent is input_settings_frame
        self.temp_dir_frame.grid(row=current_row_input, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        self.temp_dir_frame.grid_columnconfigure(1, weight=1)
        self.temp_dir_var, self.temp_dir_dropdown = self._create_labeled_combobox(
            self.temp_dir_frame, "Temp Directory Location:", row=0, # Relative row
            default_value="source folder", values=["source folder", "temporal drive", "tmp dir"],
            state="readonly", columnspan_combo=1, width=38 
        )
        self.temp_dir_frame.grid_remove() # Initially hidden
        current_row_input += 1


        # --- Output & Codec Settings Frame ---
        output_codec_settings_frame = ttk.LabelFrame(self.root, text="Output & Codec Settings")
        output_codec_settings_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=10) # Increased padding
        output_codec_settings_frame.grid_columnconfigure(1, weight=1) # Allow entry fields to expand

        current_row_output = 0
        self.frame_rate_var, self.frame_rate_entry = self._create_labeled_entry(
            output_codec_settings_frame, "Output Frame Rate (fps):", row=current_row_output,
            default_value=self.settings.get("frame_rate", "60"),
            bind_event="<KeyRelease>", bind_callback=self.update_duration,
            columnspan_entry=2
        )
        self.frame_rate = self.frame_rate_entry # Compatibility
        current_row_output += 1

        self.desired_duration_var, self.desired_duration_entry = self._create_labeled_entry(
            output_codec_settings_frame, "Desired Duration (seconds):", row=current_row_output,
            default_value=self.settings.get("desired_duration", "15"),
            bind_event="<KeyRelease>", bind_callback=self.update_duration,
            columnspan_entry=2
        )
        self.desired_duration = self.desired_duration_entry # Compatibility
        current_row_output += 1

        self.output_filename_var, self.output_filename_entry = self._create_labeled_entry(
            output_codec_settings_frame, "Output Filename:", row=current_row_output,
            default_value="output.mp4",
            columnspan_entry=2
        )
        self.output_filename = self.output_filename_entry # Compatibility
        current_row_output += 1

        self.output_folder_var, self.output_folder_entry, _ = self._create_labeled_entry(
            output_codec_settings_frame, "Output Folder:", row=current_row_output,
            default_value=self.settings.get("last_output_folder", ""),
            browse_command=self.browse_output_folder,
            columnspan_entry=1
        )
        self.output_folder = self.output_folder_entry # Compatibility
        current_row_output += 1

        self.codec_var, self.codec_dropdown = self._create_labeled_combobox(
            output_codec_settings_frame, "Codec:", row=current_row_output,
            default_value=self.settings.get("codec", "h265"),
            values=["h264", "h265", "prores_422", "prores_422_lt", "prores_444", "qtrle"],
            state="readonly", bind_event="<<ComboboxSelected>>", bind_callback=self.update_codec,
            columnspan_combo=2
        )
        current_row_output += 1

        self.audio_option_var, self.audio_option_dropdown = self._create_labeled_combobox(
            output_codec_settings_frame, "Audio Options:", row=current_row_output,
            default_value="No Audio", values=["No Audio", "Blank Audio Track"], state="readonly",
            columnspan_combo=2
        )
        current_row_output += 1
        
        # Initialize codec-specific variables (must be done before creating frames that use them)
        self.prores_profile = tk.StringVar(value=self.settings.get("prores_profile", DEFAULT_SETTINGS["prores_profile"]))
        self.prores_qscale = tk.StringVar(value=self.settings.get("prores_qscale", DEFAULT_SETTINGS["prores_qscale"]))
        self.mp4_bitrate = tk.StringVar(value=self.settings.get("mp4_bitrate", DEFAULT_SETTINGS["mp4_bitrate"]))
        self.mp4_crf = tk.StringVar(value=self.settings.get("mp4_crf", DEFAULT_SETTINGS["mp4_crf"]))

        # Codec-specific options frames (parent is output_codec_settings_frame)
        # H.264/H.265 Frame
        self.h264_h265_frame = ttk.Frame(output_codec_settings_frame)
        self.h264_h265_frame.grid(row=current_row_output, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        self.h264_h265_frame.grid_columnconfigure(1, weight=1) # Ensure entry column expands
        
        _, self.bitrate_entry = self._create_labeled_entry(self.h264_h265_frame, "Bitrate (Mbps):", row=0, entry_var=self.mp4_bitrate, default_value=self.settings.get("mp4_bitrate", DEFAULT_SETTINGS["mp4_bitrate"]), entry_width=10, bind_event="<FocusOut>", bind_callback=lambda e: self.save_settings())
        _, self.crf_entry = self._create_labeled_entry(self.h264_h265_frame, "CRF:", row=1, entry_var=self.mp4_crf, default_value=self.settings.get("mp4_crf", DEFAULT_SETTINGS["mp4_crf"]), entry_width=10, bind_event="<FocusOut>", bind_callback=lambda e: self.save_settings())
        
        # ProRes Frame
        self.prores_frame = ttk.Frame(output_codec_settings_frame)
        # Grid it on the same row as h264_h265_frame; update_codec will manage visibility
        self.prores_frame.grid(row=current_row_output, column=0, columnspan=3, sticky="ew", padx=5, pady=5) 
        self.prores_frame.grid_columnconfigure(1, weight=1) # Ensure entry column expands

        # ProRes Profile Label (not an entry, just text updated by update_codec)
        ttk.Label(self.prores_frame, text="ProRes Profile:", font=self.custom_font).grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.prores_profile_label = ttk.Label(self.prores_frame, text="", font=self.custom_font) # Text set by update_codec
        self.prores_profile_label.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        
        _, self.qscale_entry = self._create_labeled_entry(self.prores_frame, "Quality (qscale:v):", row=1, entry_var=self.prores_qscale, default_value=self.settings.get("prores_qscale", DEFAULT_SETTINGS["prores_qscale"]), entry_width=10)
        
        self.prores_frame.grid_remove() # Initially hidden by default
        # current_row_output += 1 # This row is shared by codec-specific frames

        # --- Process & Log Frame ---
        process_log_frame = ttk.LabelFrame(self.root, text="Process & Log")
        process_log_frame.grid(row=2, column=0, sticky="nsew", padx=15, pady=(10,15)) # Increased padding
        # Configure grid for process_log_frame
        process_log_frame.grid_columnconfigure(0, weight=1) # Make the first column (where button and progress bar are) expand
        process_log_frame.grid_rowconfigure(4, weight=1)    # Make the text area row (now row 4) expand

        self.run_button = ttk.Button(process_log_frame, text="Run FFmpeg", command=self.run_ffmpeg)
        # To center the button, we can make it span one column and rely on the parent's column configure
        self.run_button.grid(row=0, column=0, pady=(10,5)) 

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(process_log_frame, variable=self.progress_var, maximum=100, mode='determinate')
        self.progress_bar.grid(row=1, column=0, sticky='ew', padx=5, pady=5)

        self.status_label = ttk.Label(process_log_frame, text="", font=self.custom_font)
        self.status_label.grid(row=2, column=0, padx=5, pady=(5,0), sticky='ew')

        # "Open Output Folder" button - created here, gridded by process_queue
        self.open_output_folder_button = ttk.Button(process_log_frame, text="Open Output Folder", command=self._open_last_output_folder)

        # Text area and scrollbar
        text_area_frame = ttk.Frame(process_log_frame) # Use a frame to hold text and scrollbar
        text_area_frame.grid(row=4, column=0, sticky='nsew', padx=5, pady=5) # Moved to row 4
        text_area_frame.grid_rowconfigure(0, weight=1)
        text_area_frame.grid_columnconfigure(0, weight=1)

        self.output_text = tk.Text(text_area_frame, height=10, wrap=tk.WORD, bg='#1e1e1e', fg='#ffffff', font=self.custom_font)
        self.output_text.grid(row=0, column=0, sticky='nsew')
        self.output_scrollbar = ttk.Scrollbar(text_area_frame, orient='vertical', command=self.output_text.yview)
        self.output_scrollbar.grid(row=0, column=1, sticky='ns')
        self.output_text['yscrollcommand'] = self.output_scrollbar.set
        
        # Style for Scrollbar
        self.style.configure("Vertical.TScrollbar", 
                             background='#4a4a4a', 
                             troughcolor='#2b2b2b', 
                             bordercolor='#3c3f41', 
                             arrowcolor='#ffffff',
                             relief='flat')
        self.style.map("Vertical.TScrollbar",
                       background=[('active', '#5c5c5c')])
        
        # Initialize UI states
        self.update_codec() 
        self.root.after(100, self.process_queue)

        # Load window icon if available
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "ffmpeg_ui_icon.png")
        if os.path.exists(icon_path):
            try:
                self._icon_img = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(False, self._icon_img)
            except Exception as e:
                print(f"Could not load window icon: {e}")

    def _create_labeled_entry(self, parent, label_text, row, col_offset=0, default_value="", browse_command=None, entry_var=None, bind_event=None, bind_callback=None, columnspan_entry=1, columnspan_label=1, sticky_label="w", sticky_entry="ew", padx_label=(10,5), pady_label=(8,8), padx_entry=(5,10), pady_entry=(8,8), padx_browse=(5,10), pady_browse=(8,8), entry_width=None):
        label = ttk.Label(parent, text=label_text, font=self.custom_font)
        label.grid(row=row, column=col_offset, columnspan=columnspan_label, sticky=sticky_label, padx=padx_label, pady=pady_label)

        if entry_var is None:
            entry_var = tk.StringVar()
        
        entry_options = {'textvariable': entry_var}
        if entry_width is not None:
            entry_options['width'] = entry_width
            
        entry = ttk.Entry(parent, **entry_options)
        # The entry always starts at col_offset + columnspan_label
        entry.grid(row=row, column=col_offset + columnspan_label, columnspan=columnspan_entry, sticky=sticky_entry, padx=padx_entry, pady=pady_entry)
        
        if default_value:
            entry.insert(0, str(default_value)) # Ensure default is string
        
        if bind_event and bind_callback:
            entry.bind(bind_event, bind_callback)

        if browse_command:
            browse_button = ttk.Button(parent, text="Browse", command=browse_command)
            # Browse button is placed after the entry, considering its span
            browse_button.grid(row=row, column=col_offset + columnspan_label + columnspan_entry, padx=padx_browse, pady=pady_browse, sticky="e")
            return entry_var, entry, browse_button 
        return entry_var, entry

    def _create_labeled_combobox(self, parent, label_text, row, col_offset=0, combo_var=None, values=None, state="readonly", bind_event=None, bind_callback=None, columnspan_combo=1, columnspan_label=1, sticky_label="w", sticky_combo="ew", width=None, default_value=None, padx_label=(10,5), pady_label=(8,8), padx_combo=(5,10), pady_combo=(8,8)):
        label = ttk.Label(parent, text=label_text, font=self.custom_font)
        label.grid(row=row, column=col_offset, columnspan=columnspan_label, sticky=sticky_label, padx=padx_label, pady=pady_label)

        if combo_var is None:
            combo_var = tk.StringVar()
        
        if default_value:
            combo_var.set(str(default_value)) # Ensure default is string

        combo_options = {'textvariable': combo_var, 'state': state}
        if width is not None:
            combo_options['width'] = width
        if values:
            combo_options['values'] = values

        combobox = ttk.Combobox(parent, **combo_options)
        combobox.grid(row=row, column=col_offset + columnspan_label, columnspan=columnspan_combo, sticky=sticky_combo, padx=padx_combo, pady=pady_combo)
        
        if bind_event and bind_callback:
            combobox.bind(bind_event, bind_callback)
            
        return combo_var, combobox

    def browse_img_seq(self):
        current_dir = self.img_seq_folder_var.get() # Use the var from helper
        if not current_dir or not os.path.isdir(current_dir):
            initial_dir = self.settings["last_input_folder"]
        else:
            initial_dir = current_dir

        folder = filedialog.askdirectory(initialdir=initial_dir)
        if folder:
            self.img_seq_folder_var.set(folder)
            self.update_filename_pattern(folder)
            self.save_settings()  # Save settings after updating input folder
            self.update_output_folder(folder)
            self.update_duration()

    def update_filename_pattern(self, folder):
        try:
            files = os.listdir(folder)
            image_files = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.exr'))]
            
            if image_files:
                # Group files by their base pattern
                sequence_groups = {}
                for filename in image_files:
                    base, ext = os.path.splitext(filename)
                    is_exr = ext.lower() == '.exr'  # Check if file is EXR
                    if '.' in base:
                        pattern_base, frame_number = base.rsplit('.', 1)
                        if frame_number.isdigit():
                            if pattern_base not in sequence_groups:
                                sequence_groups[pattern_base] = []
                            sequence_groups[pattern_base].append((filename, is_exr))
                
                # Convert groups to collections
                all_collections = []
                for base_pattern, files in sequence_groups.items():
                    if len(files) > 1:  # Only create a collection if there are multiple files
                        collection_files = sorted([f for f, _ in files])
                        collections, remainder = clique.assemble(collection_files)
                        all_collections.extend(collections)
                
                if all_collections:
                    if len(all_collections) > 1:
                        # Create a sequence selection dialog
                        dialog = tk.Toplevel(self.root)
                        dialog.title("Select Image Sequence")
                        dialog.geometry("600x400")
                        dialog.transient(self.root)
                        dialog.grab_set()  # Make the dialog modal
                        
                        # Configure dialog theme
                        dialog.configure(bg='#2b2b2b')
                        
                        # Add a label
                        ttk.Label(
                            dialog, 
                            text="Multiple image sequences found. Please select one:",
                            font=self.title_font
                        ).pack(pady=10, padx=10)
                        
                        # Create a frame for the listbox and scrollbar
                        frame = ttk.Frame(dialog)
                        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
                        
                        # Create listbox with dark theme
                        listbox = tk.Listbox(
                            frame,
                            bg='#1e1e1e',
                            fg='#ffffff',
                            selectmode=tk.SINGLE,
                            font=self.custom_font
                        )
                        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                        
                        # Add scrollbar
                        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=listbox.yview)
                        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                        listbox.config(yscrollcommand=scrollbar.set)
                        
                        # Populate listbox with sequence information
                        for idx, collection in enumerate(all_collections):
                            first_frame = min(collection.indexes)
                            last_frame = max(collection.indexes)
                            frame_count = len(collection.indexes)
                            sequence_info = f"{collection.head}[{first_frame}-{last_frame}]{collection.tail} ({frame_count} frames)"
                            listbox.insert(tk.END, sequence_info)
                            
                        # Store the collections for later use
                        dialog.collections = all_collections
                        
                        def on_select():
                            selection = listbox.curselection()
                            if selection:
                                selected_idx = selection[0]
                                collection = dialog.collections[selected_idx]
                                # Update the UI with selected sequence
                                pattern = f"{collection.head}%04d{collection.tail}"  # Force 4-digit padding
                                self.filename_pattern_var.set(pattern) # Use the var
                                
                                self.frame_range = (min(collection.indexes), max(collection.indexes))
                                self.total_frames = len(collection.indexes)
                                
                                # Show/hide ACES frame based on file type
                                if pattern.lower().endswith('.exr'):
                                    self.aces_frame.grid()
                                    self.temp_dir_frame.grid()  # Show temp dir selection for EXR files
                                else:
                                    self.aces_frame.grid_remove()
                                    self.temp_dir_frame.grid_remove()  # Hide temp dir selection for non-EXR files
                                    self.temp_dir_var.set("source folder")  # Reset to default when hidden
                                
                                # Update output filename
                                output_name = collection.head.rstrip('_.')
                                self.output_filename_var.set(output_name) # Use the var
                                
                                # Update duration
                                self.update_duration()
                                dialog.destroy()
                            else:
                                messagebox.showwarning("Warning", "Please select a sequence.", parent=dialog)
                        
                        # Add Select button
                        ttk.Button(
                            dialog,
                            text="Select",
                            command=on_select
                        ).pack(pady=10)
                        
                        # Center the dialog on the parent window
                        dialog.update_idletasks()
                        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
                        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
                        dialog.geometry(f"+{x}+{y}")
                        
                        # Wait for the dialog to close
                        self.root.wait_window(dialog)
                    else:
                        # Single sequence found - use existing logic
                        collection = all_collections[0]
                        pattern = f"{collection.head}%04d{collection.tail}"
                        self.filename_pattern_var.set(pattern) # Use the var
                        
                        # Show/hide ACES frame based on file type
                        if pattern.lower().endswith('.exr'):
                            self.aces_frame.grid()
                            self.temp_dir_frame.grid()  # Show temp dir selection for EXR files
                        else:
                            self.aces_frame.grid_remove()
                            self.temp_dir_frame.grid_remove()  # Hide temp dir selection for non-EXR files
                            self.temp_dir_var.set("source folder")  # Reset to default when hidden
                        
                        self.frame_range = (min(collection.indexes), max(collection.indexes))
                        self.total_frames = len(collection.indexes)
                        
                        # Update output filename
                        output_name = collection.head.rstrip('_.')
                        self.output_filename_var.set(output_name) # Use the var
                        
                        # Update duration
                        self.update_duration()
                else:
                    messagebox.showwarning("Warning", "No image sequence found in the selected folder.")
                    self.total_frames = 0
                    self.desired_duration_var.set("0") # Use the var
            else:
                messagebox.showwarning("Warning", "No image files found in the selected folder.")
                self.total_frames = 0
                self.desired_duration_var.set("0") # Use the var
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update filename pattern: {e}")
            self.total_frames = 0
            self.desired_duration_var.set("0") # Use the var

    def update_output_folder(self, input_folder):
        """Update output folder with option to use parent directory of input folder"""
        output_folder = os.path.dirname(input_folder)
        current_output = self.output_folder_var.get() # Use the var
        
        # If there's no current output folder set, or it's different from the suggested one
        if not current_output or current_output != output_folder:
            response = messagebox.askyesno(
                "Update Output Folder",
                f"Would you like to set the output folder to:\n{output_folder}?"
            )
            if response:
                self.output_folder_var.set(output_folder) # Use the var
                self.save_settings()  # Save settings after updating output folder

    def load_settings(self):
        """Load settings from JSON file, or create with defaults if not exists"""
        try:
            with open('ffmpeg_settings.json', 'r') as f:
                settings = json.load(f)
                # Update with any missing default settings
                for key, value in DEFAULT_SETTINGS.items():
                    if key not in settings:
                        settings[key] = value
                return settings
        except (FileNotFoundError, json.JSONDecodeError):
            return DEFAULT_SETTINGS.copy()

    def save_settings(self):
        """Save current settings to JSON file"""
        settings = {
            "last_input_folder": self.img_seq_folder_var.get(), # Use var
            "last_output_folder": self.output_folder_var.get(), # Use var
            "frame_rate": self.frame_rate_var.get(), # Use var
            "source_frame_rate": self.source_frame_rate_var.get(), # Use var
            "desired_duration": self.desired_duration_var.get(), # Use var
            "codec": self.codec_var.get(), # Already a var
            "mp4_bitrate": self.mp4_bitrate.get() if hasattr(self, 'mp4_bitrate') else DEFAULT_SETTINGS["mp4_bitrate"],
            "mp4_crf": self.mp4_crf.get() if hasattr(self, 'mp4_crf') else DEFAULT_SETTINGS["mp4_crf"],
            "prores_profile": self.prores_profile.get() if hasattr(self, 'prores_profile') else DEFAULT_SETTINGS["prores_profile"],
            "prores_qscale": self.prores_qscale.get() if hasattr(self, 'prores_qscale') else DEFAULT_SETTINGS["prores_qscale"]
        }
        
        try:
            with open('ffmpeg_settings.json', 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def browse_output_folder(self):
        initial_dir = self.output_folder_var.get() or self.settings["last_output_folder"] # Use var
        folder = filedialog.askdirectory(initialdir=initial_dir)
        if folder:
            self.output_folder_var.set(folder) # Use var
            self.save_settings()  # Save settings after updating output folder

    def update_codec(self, event=None):
        codec = self.codec_var.get()
        print(f"Selected codec: {codec}")

        if codec in ["h264", "h265"]:
            self.h264_h265_frame.grid()
            self.prores_frame.grid_remove()
            # Set MP4 values from settings or StringVars
            if hasattr(self, 'mp4_bitrate') and self.mp4_bitrate: # Check if StringVar exists
                self.mp4_bitrate.set(self.settings.get("mp4_bitrate", DEFAULT_SETTINGS["mp4_bitrate"]))
            if hasattr(self, 'mp4_crf') and self.mp4_crf:
                self.mp4_crf.set(self.settings.get("mp4_crf", DEFAULT_SETTINGS["mp4_crf"]))
        elif codec.startswith("prores"):
            self.h264_h265_frame.grid_remove()
            self.prores_frame.grid()
            # Set ProRes profile based on selection
            profile_text = ""
            if codec == "prores_422":
                self.prores_profile.set("2")  # Standard 422
                profile_text = "422"
            elif codec == "prores_422_lt":
                self.prores_profile.set("1")  # 422 LT
                profile_text = "422 LT"
            elif codec == "prores_444":
                self.prores_profile.set("4")  # 4444
                profile_text = "4444"
            self.prores_profile_label.config(text=profile_text)
            # Set default ProRes Qscale from settings or StringVar
            if hasattr(self, 'prores_qscale') and self.prores_qscale:
                 self.prores_qscale.set(self.settings.get("prores_qscale", DEFAULT_SETTINGS["prores_qscale"]))
        elif codec == "qtrle":
            self.h264_h265_frame.grid_remove()
            self.prores_frame.grid_remove()
            # Set qtrle codec parameters
            codec_params = [
                "-c:v", "qtrle",
                "-pix_fmt", "rgb24"  # Use rgb24 for Animation codec
            ]
        else:
            # Set ProRes values from settings
            if hasattr(self, 'prores_qscale') and self.prores_qscale:
                self.prores_qscale.set(self.settings.get("prores_qscale", DEFAULT_SETTINGS["prores_qscale"]))
            if hasattr(self, 'prores_profile') and self.prores_profile: # This var holds the number, not text
                # We don't set prores_profile_label here as it depends on the specific prores type
                pass # self.prores_profile.set(self.settings.get("prores_profile", DEFAULT_SETTINGS["prores_profile"]))
            self.h264_h265_frame.grid_remove()
            self.prores_frame.grid_remove()

        self.save_settings()  # Save settings after updating codec
        self.update_duration()

    def update_duration(self, event=None):
        # This method now calculates the scale factor based on desired duration and frame rate
        if hasattr(self, 'total_frames') and self.total_frames > 0:
            try:
                source_frame_rate = float(self.source_frame_rate_var.get()) # Use var
                output_frame_rate = float(self.frame_rate_var.get()) # Use var
                desired_duration = float(self.desired_duration_var.get()) # Use var
                
                if source_frame_rate <= 0 or output_frame_rate <= 0 or desired_duration <= 0:
                    raise ValueError
                    
                # Original duration of sequence at source frame rate
                original_duration = self.total_frames / source_frame_rate
                
                # Calculate the exact number of frames needed for the desired duration at output frame rate
                total_frames_needed = int(round(output_frame_rate * desired_duration))
                
                # Calculate the actual duration based on the exact number of frames
                actual_duration = total_frames_needed / output_frame_rate
                
                # Calculate scale factor for timestamp adjustment
                scale_factor = desired_duration / original_duration
                self.scale_factor = scale_factor  # Store scale factor for use in run_ffmpeg
                print(f"Scale factor updated to: {scale_factor}")  # Debug statement
            except ValueError:
                self.scale_factor = None
        else:
            self.scale_factor = None

    def run_ffmpeg(self):
        print("Debug: run_ffmpeg function called")

        # For now, we'll force image sequence mode since video file handling isn't fully implemented
        input_type = "Image Sequence" # self.input_type_var.get()
        img_folder = self.img_seq_folder_var.get() # Current value in the UI field
        output_dir = self.output_folder_var.get().strip() # Use var
        output_file = self.output_filename_var.get().strip() # Use var
        codec = self.codec_var.get() # Already a var
        pattern = self.filename_pattern_var.get() # Use var
        is_exr_pattern = pattern.lower().endswith('.exr') # Based on the current pattern in UI

        # Initial debug prints for run_ffmpeg call
        print(f"=== Starting run_ffmpeg ({'EXR pattern' if is_exr_pattern else 'Non-EXR pattern'}) ===")
        print(f"  Input folder from UI: {img_folder}")
        print(f"  Pattern from UI: {pattern}")
        if hasattr(self, 'original_exr_path'):
            print(f"  Current self.original_exr_path: {self.original_exr_path}")
        if hasattr(self, 'temp_dir'):
            print(f"  Current self.temp_dir: {self.temp_dir}")

        # Check if this call is for processing temporary PNGs from a previous EXR conversion
        is_processing_temp_pngs_from_exr = (hasattr(self, 'temp_dir') and self.temp_dir and \
                                           hasattr(self, 'original_exr_path') and self.original_exr_path and \
                                           img_folder == self.temp_dir and not is_exr_pattern)
        
        print(f"  Is processing temp PNGs from EXR stage: {is_processing_temp_pngs_from_exr}")

        # Check input directory
        print(f"  Checking input folder: {img_folder}")
        if not os.path.exists(img_folder):
            print("  Error: Input folder does not exist")
            messagebox.showerror("Error", f"Input folder does not exist: {img_folder}")
            return

        # Get filename pattern from UI (already done)
        # is_exr = pattern.lower().endswith('.exr') # Redundant, use is_exr_pattern

        # Check if frame_range exists before continuing (relevant for both EXR first pass and direct sequence)
        if not hasattr(self, 'frame_range'):
            messagebox.showerror("Error", "No image sequence detected. Please select an image sequence folder first.")
            return
            
        # If input is EXR (and not the temp PNG stage), run conversion in a separate thread
        if is_exr_pattern and not is_processing_temp_pngs_from_exr:
            print("  Debug: EXR sequence (first pass). Storing original path and starting EXR conversion.")
            self.original_exr_path = img_folder # Store the original EXR path from UI
            
            # Ensure pattern includes '%04d'
            if "%04d" not in pattern:
                messagebox.showerror("Error", "Filename pattern must contain '%04d' for image sequence.")
                return

            # start_frame and end_frame are expected to have been set during sequence detection
            start_frame, end_frame = self.frame_range
            
            # Store all parameters for second stage processing
            self.exr_conversion_params = {
                'output_framerate': float(self.frame_rate_var.get()), # Use var
                'source_framerate': float(self.source_frame_rate_var.get()), # Use var
                'desired_duration': float(self.desired_duration_var.get()), # Use var
                'codec': codec,
                'output_dir': output_dir,
                'output_file': output_file
            }
            
            # Store codec-specific parameters
            if codec in ["h264", "h265"]:
                self.exr_conversion_params.update({
                    'bitrate': self.mp4_bitrate.get(),
                    'crf': self.mp4_crf.get()
                })
            elif codec.startswith("prores"):
                self.exr_conversion_params.update({
                    'profile': self.prores_profile.get(),
                    'qscale': self.prores_qscale.get()
                })

            # Launch the conversion in a separate thread so that the UI isn't blocked.
            conversion_thread = threading.Thread(
                target=self.convert_exr_files,
                args=(img_folder, pattern, start_frame, end_frame, pattern.split("%04d", 1)[0])
            )
            conversion_thread.start()
            return  # Return immediately so that the UI remains responsive
        
        elif not is_exr_pattern and not is_processing_temp_pngs_from_exr:
            # This is a direct non-EXR sequence (e.g., PNG, JPG directly selected by user)
            # and not the second pass of an EXR job.
            print("  Debug: Direct non-EXR sequence (user selected PNG/JPG etc.). Clearing original_exr_path.")
            self.original_exr_path = None
        
        # If we reach here, it's either:
        # a) A direct non-EXR sequence (self.original_exr_path is None).
        # b) The second pass of an EXR->PNG conversion (self.original_exr_path holds original EXR path, img_folder is temp_dir).
        print(f"  Debug: Proceeding to FFmpeg video encoding. Current self.original_exr_path = {self.original_exr_path}")


        # Validate output directory
        if not output_dir:
            messagebox.showerror("Error", "Please select an output directory")
            return

        # Create output directory if it doesn't exist
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                messagebox.showerror("Error", f"Cannot create output directory: {e}")
                return

        # Check if output directory is writable
        if not os.access(output_dir, os.W_OK):
            messagebox.showerror("Error", f"Cannot write to output directory: {output_dir}")
            return

        # Get and validate output filename
        output_file = self.output_filename_var.get().strip() # Use var
        if not output_file:
            messagebox.showerror("Error", "Please enter an output filename")
            return

        # Hide the "Open Output Folder" button at the start of a new process
        self.queue.put(('hide_open_folder_button', None))

        # Construct full output path
        output_path = os.path.join(output_dir, output_file)

        # Check if output file already exists
        if os.path.exists(output_path):
            response = messagebox.askyesno(
                "File Exists",
                f"The file '{output_file}' already exists in the output directory. Do you want to overwrite it?"
            )
            if not response:
                return

        if not os.path.exists(img_folder) or not os.access(img_folder, os.R_OK):
            messagebox.showerror("Error", f"Cannot read from input folder: {img_folder}")
            return

        # Verify at least one input file exists
        test_file = os.path.join(img_folder, pattern % self.frame_range[0])
        if not os.path.exists(test_file):
            messagebox.showerror("Error", f"Cannot find first frame: {test_file}")
            return

        # Debug output
        self.queue.put(('output', f"Input folder: {img_folder}\n"))
        self.queue.put(('output', f"Output directory: {output_dir}\n"))
        self.queue.put(('output', f"First frame path: {test_file}\n"))

        try:
            source_framerate = float(self.source_frame_rate_var.get()) # Use var
            output_framerate = float(self.frame_rate_var.get()) # Use var
            desired_duration = float(self.desired_duration_var.get()) # Use var
            
            if source_framerate <= 0 or output_framerate <= 0 or desired_duration <= 0:
                raise ValueError
                
            # Original duration of sequence at source frame rate
            original_duration = self.total_frames / source_framerate
            
            # Calculate the exact number of frames needed for the desired duration at output frame rate
            total_frames_needed = int(round(output_framerate * desired_duration))
            
            # Calculate the actual duration based on the exact number of frames
            actual_duration = total_frames_needed / output_framerate
            
            # Calculate scale factor for timestamp adjustment
            scale_factor = desired_duration / original_duration
        except ValueError:
            self.queue.put(('error', "Please enter valid frame rates and desired duration."))
            return

        output_file = self.output_filename_var.get().strip() # Use var
        output_dir = self.output_folder_var.get() # Use var

        if not all([img_folder, pattern, output_framerate, output_file, output_dir]):
            self.queue.put(('error', "Please fill in all fields."))
            return

        # Determine the correct file extension
        file_extension = ".mp4" if codec in ["h264", "h265"] else ".mov"
        
        # Ensure the output filename does not end with a dot or underscore
        output_file_base = output_file.rstrip('_.')
        output_file_base, _ = os.path.splitext(output_file_base)
        output_file_base = output_file_base.rstrip('.')
        output_file = f"{output_file_base}{file_extension}"

        # Use the frame range information to build ffmpeg input arguments
        if hasattr(self, 'frame_range') and self.total_frames > 0:
            start_frame, end_frame = self.frame_range
            input_pattern = pattern  # Use the updated pattern
            input_path = os.path.join(img_folder, input_pattern)
            image_sequence_input_args = [
                "-start_number", str(start_frame),
                "-framerate", str(source_framerate),  # Use source frame rate for input
                "-i", input_path
            ]
        else:
            self.queue.put(('error', "Frame range not detected. Please select the image sequence folder again."))
            return

        output_path = os.path.join(output_dir, output_file)

        # Determine the codec parameters for video
        video_codec_params = []
        if codec in ["h264", "h265"]:
            bitrate = self.mp4_bitrate.get()
            crf = self.mp4_crf.get()
            if not bitrate or not crf:
                self.queue.put(('error', "Bitrate and CRF settings are required for H.264/H.265 encoding."))
                return
            
            codec_lib = "libx264" if codec == "h264" else "libx265"
            video_codec_params = [
                "-c:v", codec_lib,
                "-preset", "medium",
                "-b:v", f"{bitrate}M",
                "-maxrate", f"{int(float(bitrate)*2)}M",
                "-bufsize", f"{int(float(bitrate)*2)}M"
            ]
            if codec == "h264":
                video_codec_params.extend(["-profile:v", "high", "-level:v", "5.1"])
            else:
                video_codec_params.extend(["-tag:v", "hvc1"])
        elif codec.startswith("prores"):
            profile = self.prores_profile.get()
            qscale = self.prores_qscale.get()
            if not profile or not qscale:
                self.queue.put(('error', "ProRes profile and Quality settings are required for ProRes encoding."))
                return
            
            video_codec_params = [
                "-c:v", "prores_ks",
                "-profile:v", profile,
                "-qscale:v", qscale
            ]
        elif codec == "qtrle":
            video_codec_params = [
                "-c:v", "qtrle",
                # "-pix_fmt", "rgb24" # This will be handled later by general pix_fmt for output
            ]
        else:
            self.queue.put(('error', "Unsupported codec selected."))
            return

        # Video filters
        setpts_filter = f"setpts={scale_factor:.10f}*PTS"
        # Scale filter for color matrix should ideally be more context-aware based on input if not bt709
        ffmpeg_filters_str = f"{setpts_filter},scale=in_color_matrix=bt709:out_color_matrix=bt709"
        video_filter_args = ["-vf", ffmpeg_filters_str]
        
        frames_arg = ["-frames:v", str(total_frames_needed)]
        
        output_color_space_args = [
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-colorspace", "bt709"
        ]

        # --- Construct the ffmpeg command --- 
        cmd = ["ffmpeg", "-accurate_seek"] # Base command and global options

        # --- INPUTS ---
        # Image sequence input (with -ss 0 for fast seeking at start of this input)
        cmd += ["-ss", "0"] + image_sequence_input_args

        # Audio input (if blank audio selected)
        audio_option = self.audio_option_var.get()
        blank_audio_input_args = []
        output_audio_handling_args = [] # For -an or audio codec settings

        if audio_option == "Blank Audio Track":
            blank_audio_input_args = [
                "-f", "lavfi",
                "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-shortest"  # Ensures this silent audio input matches duration of other inputs
            ]
            # Explicitly set audio codec and bitrate for the blank track
            output_audio_handling_args.extend(["-c:a", "aac", "-b:a", "128k"])
        elif audio_option == "No Audio":
            output_audio_handling_args = ["-an"] # Output option to disable audio

        cmd += blank_audio_input_args # Add blank audio input args if any

        # --- OUTPUTS, FILTERS, CODECS ---
        cmd += [
            "-t", f"{desired_duration:.6f}",   # Output duration
            "-r", str(output_framerate),       # Output frame rate
            "-fps_mode", "cfr",                # Replaces deprecated -vsync cfr for constant frame rate
        ]
        
        cmd += video_filter_args # Video filters (-vf)

        # Pixel format and video track timescale
        # For qtrle (Animation codec), rgb24 is often used. For others, yuv420p is common for compatibility.
        output_pix_fmt = "rgb24" if codec == "qtrle" else "yuv420p"
        cmd += [
            "-pix_fmt", output_pix_fmt,
            "-video_track_timescale", "30000"
        ]
        
        cmd += output_audio_handling_args # Add -an if no audio, or audio codec settings
        
        cmd += video_codec_params         # Video codec settings from UI
        cmd += output_color_space_args     # Output video color space settings

        cmd += [output_path]                # Output file path

        print("FFmpeg command:", " ".join(cmd))

        # Execute the ffmpeg command in a separate thread
        thread = threading.Thread(target=self.execute_ffmpeg, args=(cmd, output_path, actual_duration))
        thread.start()

    def execute_ffmpeg(self, cmd, output_path, actual_duration):
        try:
            self.queue.put(('output', "Starting FFmpeg process...\n"))
            print(f"\nExecuting FFmpeg command:\n{' '.join(cmd)}\n")
            
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            self.active_processes.append(process)  # Add process to active processes list
            
            self.queue.put(('output', f"Process started with PID: {process.pid}\n"))
            print(f"FFmpeg process started with PID: {process.pid}")

            def read_stderr():
                try:
                    print("Starting stderr reader thread")
                    for line in iter(process.stderr.readline, ''):
                        self.queue.put(('output', line))
                        print(f"STDERR: {line.strip()}")
                        if "frame=" in line:
                            try:
                                frame_match = re.search(r'frame=\s*(\d+)', line)
                                time_match = re.search(r'time=\s*(\d+:\d+:\d+\.\d+)', line)
                                speed_match = re.search(r'speed=\s*(\d+\.\d+)x', line)
                                
                                if frame_match:
                                    current_frame = int(frame_match.group(1))
                                    progress = (current_frame / self.total_frames) * 100 if self.total_frames > 0 else 0
                                    status_parts = [f"Frame: {current_frame}/{self.total_frames}"]
                                    if time_match:
                                        status_parts.append(f"Time: {time_match.group(1)}")
                                    if speed_match:
                                        status_parts.append(f"Speed: {speed_match.group(1)}x")
                                    status = " | ".join(status_parts)
                                    self.queue.put(('progress', (progress, status)))
                            except Exception as e:
                                print(f"Error parsing progress: {str(e)}")
                except Exception as e:
                    print(f"Stderr reader error: {str(e)}")
                    self.queue.put(('output', f"\nError Reading Stderr: {str(e)}\n"))

            def read_stdout():
                try:
                    print("Starting stdout reader thread")
                    for line in iter(process.stdout.readline, ''):
                        print(f"STDOUT: {line.strip()}")
                        self.queue.put(('output', line))
                except Exception as e:
                    print(f"Stdout reader error: {str(e)}")
                    self.queue.put(('output', f"\nOutput Reader Error: {str(e)}\n"))

            stdout_thread = threading.Thread(target=read_stdout)
            stderr_thread = threading.Thread(target=read_stderr)
            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()

            process.wait()
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

            # Clean up temp directory if it exists and ffmpeg completed successfully
            if process.returncode == 0 and hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                try:
                    print(f"DEBUG: Cleaning up temp directory after successful conversion: {self.temp_dir}")
                    self.queue.put(('output', f"Cleaning up temporary files...\n"))
                    shutil.rmtree(self.temp_dir)
                    print(f"Cleaned up temp directory: {self.temp_dir}")
                except Exception as e:
                    print(f"Warning: Could not clean up temp directory: {e}")
                    self.queue.put(('output', f"Warning: Could not clean up temp files: {e}\n"))

            if process.returncode != 0:
                error_message = f"FFmpeg process returned {process.returncode}"
                try:
                    remaining_error = process.stderr.read()
                    if remaining_error:
                        error_message += f"\nError details:\n{remaining_error}"
                except:
                    pass
                self.queue.put(('error', error_message))
            else:
                success_message = f"Video created at {output_path}\nActual duration: {actual_duration:.3f} seconds"
                self.queue.put(('success', success_message))
                self.queue.put(('show_open_folder_button', os.path.dirname(output_path))) # Send output directory

                # If original_exr_path is set, it means we converted EXRs and should restore the path
                if hasattr(self, 'original_exr_path') and self.original_exr_path:
                    self.queue.put(('restore_path', self.original_exr_path))
                    self.original_exr_path = None # Clear it after use

        except Exception as e:
            self.queue.put(('error', f"Unexpected error: {str(e)}"))

    def process_queue(self):
        try:
            while not self.queue.empty():
                msg_type, content = self.queue.get_nowait()
                if msg_type == 'output':
                    self.output_text.insert(tk.END, content)
                    self.output_text.see(tk.END)
                elif msg_type == 'progress':
                    progress, status = content
                    self.progress_var.set(progress)
                    self.status_label.config(text=status)
                elif msg_type == 'error':
                    messagebox.showerror("FFmpeg Error", content)
                elif msg_type == 'success':
                    self.progress_var.set(100)
                    self.status_label.config(text="Conversion complete")
                    messagebox.showinfo("Success", content)
                elif msg_type == 'prepare_ffmpeg':
                    # Handle FFmpeg preparation on main thread
                    self.prepare_ffmpeg_conversion(content)
                elif msg_type == 'restore_path':
                    self.img_seq_folder.delete(0, tk.END)
                    self.img_seq_folder.insert(0, content)
                    # Also update the var if using helpers that rely on it
                    if hasattr(self, 'img_seq_folder_var'):
                        self.img_seq_folder_var.set(content)
                    self.output_text.insert(tk.END, f"INFO: Input path restored to: {content}\n")
                    self.output_text.see(tk.END)
                elif msg_type == 'show_open_folder_button':
                    self.last_successful_output_dir = content
                    self.open_output_folder_button.grid(row=3, column=0, pady=(5,10)) # Grid below status_label
                elif msg_type == 'hide_open_folder_button':
                    self.open_output_folder_button.grid_remove()
                    self.last_successful_output_dir = None
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_queue)

    def prepare_ffmpeg_conversion(self, params):
        """Prepare and start FFmpeg conversion on the main thread"""
        try:
            # Update UI elements safely on main thread
            self.img_seq_folder.delete(0, tk.END)
            self.img_seq_folder.insert(0, params['temp_dir'])
            
            # Get all PNG files in temp directory
            png_files = sorted([f for f in os.listdir(params['temp_dir']) if f.endswith('.png')])
            collections, remainder = clique.assemble(png_files)
            
            if collections:
                collection = collections[0]  # We know we only have one sequence
                pattern = params['pattern']
                self.filename_pattern.delete(0, tk.END)
                self.filename_pattern.insert(0, pattern)
                
                # Set the frame range and total frames for FFmpeg
                self.frame_range = params['frame_range']
                self.total_frames = params['total_frames']
                
                # Start FFmpeg conversion safely on main thread
                self.run_ffmpeg()
            else:
                self.queue.put(('error', "Failed to detect PNG sequence in temp directory"))
        except Exception as e:
            self.queue.put(('error', f"Error preparing FFmpeg conversion: {str(e)}"))

    def convert_exr_files(self, img_folder, pattern, start_frame, end_frame, before):
        print("\nDEBUG: convert_exr_files starting")
        self.queue.put(('output', "\nDEBUG: Starting EXR conversion (thread)...\n"))
        
        # Define OCIO configuration path
        ocio_config = "/mnt/studio/config/ocio/aces_1.2/config.ocio"
        # First try to create temp directory as a subdirectory of the input folder
        temp_dir_name = f"ffmpeg_tmp_{os.getpid()}"
        
        # Get selected temp directory location
        temp_location = self.temp_dir_var.get()
        
        if temp_location == "source folder":
            # Try creating temp dir in input folder first
            input_temp_dir = os.path.join(img_folder, temp_dir_name)
            try:
                os.makedirs(input_temp_dir, exist_ok=True)
                # Test write permissions
                test_file = os.path.join(input_temp_dir, ".permission_test")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                self.temp_dir = input_temp_dir
                print(f"DEBUG: Created temp dir in input folder: {self.temp_dir}")
                self.queue.put(('output', f"DEBUG: Created temp dir in input folder: {self.temp_dir}\n"))
            except (IOError, PermissionError) as e:
                print(f"DEBUG: Cannot create temp dir in input folder: {e}")
                self.queue.put(('output', f"DEBUG: Cannot create temp dir in input folder: {e}\n"))
                # Fall through to tmp dir as last resort
                temp_location = "tmp dir"
        
        if temp_location == "temporal drive":
            # Try /mnt/temporal/ffmpeg_tool_cache/
            try:
                mnt_temp_dir = "/mnt/temporal/ffmpeg_tool_cache"
                os.makedirs(mnt_temp_dir, exist_ok=True)
                self.temp_dir = os.path.join(mnt_temp_dir, temp_dir_name)
                os.makedirs(self.temp_dir, exist_ok=True)
                # Test write permissions
                test_file = os.path.join(self.temp_dir, ".permission_test")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                print(f"DEBUG: Created temp dir in /mnt/temporal: {self.temp_dir}")
                self.queue.put(('output', f"DEBUG: Created temp dir in /mnt/temporal: {self.temp_dir}\n"))
            except (IOError, PermissionError, FileNotFoundError) as e:
                print(f"DEBUG: Cannot create temp dir in /mnt/temporal: {e}")
                self.queue.put(('output', f"DEBUG: Cannot create temp dir in /mnt/temporal: {e}\n"))
                # Fall through to tmp dir as last resort
                temp_location = "tmp dir"
        
        if temp_location == "tmp dir":
            # Try the base temp dir first
            self.temp_dir = os.path.join("/tmp", f"convert_{os.getpid()}")
            try:
                os.makedirs(self.temp_dir, exist_ok=True)
                print(f"DEBUG: Created temp dir in base location: {self.temp_dir}")
                self.queue.put(('output', f"DEBUG: Created temp dir in base location: {self.temp_dir}\n"))
            except Exception as e:
                # Last resort - try /tmp
                print(f"DEBUG: Cannot create temp dir in base location: {e}")
                self.queue.put(('output', f"DEBUG: Cannot create temp dir in base location: {e}\n"))
                self.temp_dir = os.path.join("/tmp", f"ffmpeg_tmp_{os.getpid()}")
                os.makedirs(self.temp_dir, exist_ok=True)
                print(f"DEBUG: Created temp dir in /tmp: {self.temp_dir}")
                self.queue.put(('output', f"DEBUG: Created temp dir in /tmp: {self.temp_dir}\n"))
        
        total_frames = end_frame - start_frame + 1
        print("DEBUG: total_frames =", total_frames)
        self.queue.put(('output', f"DEBUG: Total frames to convert: {total_frames}\n"))
        
        # Check if all PNG files already exist
        all_files_exist = True
        missing_frames = []
        for frame in range(start_frame, end_frame + 1):
            png_file = os.path.join(self.temp_dir, f"{before}{frame:04d}.png")
            if not os.path.exists(png_file):
                all_files_exist = False
                missing_frames.append(frame)
        
        if all_files_exist:
            print("DEBUG: All PNG files already exist, skipping conversion")
            self.queue.put(('output', "All PNG files already exist, skipping conversion\n"))
            self.queue.put(('progress', (100, "EXR conversion complete (skipped)")))
            # Store frame range for FFmpeg conversion
            self.temp_frame_range = (start_frame, end_frame)
            # Proceed directly to FFmpeg conversion
            new_pattern = f"{before}%04d.png"
            print("DEBUG: Starting FFmpeg conversion with pattern:", new_pattern)
            self.queue.put(('output', f"DEBUG: Starting FFmpeg conversion with pattern: {new_pattern}\n"))
            self.root.after(0, lambda: self.finish_exr_conversion_main_callback(start_frame, end_frame))
            return
        
        print(f"DEBUG: Need to convert {len(missing_frames)} frames")
        self.queue.put(('output', f"Converting {len(missing_frames)} frames\n"))
        
        # Get selected color space names (preserve spaces, no underscores)
        input_colorspace = self.color_space_var.get()
        output_colorspace = "Output - sRGB"
        
        # Verify that at least the first input file exists
        first_frame = missing_frames[0] if missing_frames else start_frame
        input_file_pattern = os.path.join(img_folder, pattern)
        test_file = input_file_pattern.replace("%04d", f"{first_frame:04d}")
        if not os.path.exists(test_file):
            error_msg = f"Input file not found: {test_file}"
            print(f"DEBUG: {error_msg}")
            self.queue.put(('error', error_msg))
            return
        
        # Build command for individual files using the pattern from UI
        cmds = []
        for frame in missing_frames:
            # Use the pattern directly from UI with proper frame substitution
            input_file = input_file_pattern.replace("%04d", f"{frame:04d}")
            output_file = os.path.join(self.temp_dir, f"{before}{frame:04d}.png")
            
            # Skip file if it already exists
            if os.path.exists(output_file):
                continue
                
            # Check if input file exists
            if not os.path.exists(input_file):
                error_msg = f"Input file not found: {input_file}"
                print(f"DEBUG: {error_msg}")
                self.queue.put(('error', error_msg))
                return
                
            cmd = [
                "oiiotool",
                "-v",
                "--colorconfig", ocio_config,
                "--threads", "1",  # Use single thread per file
                input_file,
                "--ch", "R,G,B",
                "--colorconvert", input_colorspace, output_colorspace,  # Preserve spaces, don't use underscores
                "-d", "uint8",
                "--compression", "none",
                "--no-clobber",
                "-o", output_file
            ]
            cmds.append((cmd, frame))
            
        if not cmds:
            print("DEBUG: No valid frames to convert")
            self.queue.put(('error', "No valid frames to convert. Check that input files exist."))
            return
            
        # Print sample command for debugging
        print("\nDEBUG: Sample conversion command:", " ".join(cmds[0][0]))
        self.queue.put(('output', f"\nDEBUG: Will convert {len(cmds)} frames individually\n"))
        
        # Process files with a thread pool to speed things up but not overload the system
        max_workers = min(os.cpu_count(), 8)  # Limit to 8 parallel processes max
        total_files = len(cmds)
        completed_files = 0
        
        try:
            # Define a function to process one file
            def process_file(cmd_info):
                cmd, frame_num = cmd_info
                try:
                    print(f"DEBUG: Starting conversion for frame {frame_num}")
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True
                    )
                    stdout, stderr = process.communicate()
                    
                    # Log detailed output for debugging
                    if stdout:
                        print(f"DEBUG: Frame {frame_num} stdout: {stdout[:100]}")
                    
                    if process.returncode != 0:
                        print(f"DEBUG: Frame {frame_num} FAILED with return code {process.returncode}")
                        print(f"DEBUG: Frame {frame_num} error output: {stderr}")
                        
                        # Check if output directory still exists and is writable
                        output_file = os.path.join(self.temp_dir, f"{before}{frame_num:04d}.png")
                        output_dir = os.path.dirname(output_file)
                        print(f"DEBUG: Output path: {output_file}")
                        print(f"DEBUG: Output dir exists: {os.path.exists(output_dir)}")
                        if os.path.exists(output_dir):
                            print(f"DEBUG: Output dir writable: {os.access(output_dir, os.W_OK)}")
                        
                        return (frame_num, process.returncode, stderr)
                    return (frame_num, 0, None)
                except Exception as e:
                    print(f"DEBUG: Exception for frame {frame_num}: {str(e)}")
                    return (frame_num, -1, str(e))
            
            # Create and start worker threads
            threads = []
            active_workers = 0
            cmd_queue = list(cmds)
            results = []
            
            while cmd_queue or threads:
                # Start new workers if we have capacity and commands
                while active_workers < max_workers and cmd_queue:
                    cmd_info = cmd_queue.pop(0)
                    thread = threading.Thread(target=lambda c=cmd_info: results.append(process_file(c)))
                    thread.daemon = True
                    thread.start()
                    threads.append(thread)
                    active_workers += 1
                
                # Check for completed threads
                still_active = []
                for thread in threads:
                    if thread.is_alive():
                        still_active.append(thread)
                    else:
                        active_workers -= 1
                        completed_files += 1
                        # Update progress
                        progress = (completed_files / total_files) * 100
                        status = f"Converting EXR frames: {completed_files}/{total_files} ({progress:.1f}%)"
                        self.queue.put(('progress', (progress, status)))
                
                threads = still_active
                time.sleep(0.1)  # Don't hammer the CPU checking thread status
            
            # Check results
            failures = [r for r in results if r[1] != 0]
            if failures:
                print("\nDEBUG: DETAILED FAILURE INFORMATION:")
                for i, failure in enumerate(failures[:10]):  # Show first 10 failures in detail
                    frame_num, return_code, error_msg = failure
                    print(f"DEBUG: Frame {frame_num} failed with code {return_code}")
                    if error_msg:
                        print(f"DEBUG: Error message: {error_msg}")
                    # Print the command that was used for this frame
                    input_file = input_file_pattern.replace("%04d", f"{frame_num:04d}")
                    output_file = os.path.join(self.temp_dir, f"{before}{frame_num:04d}.png")
                    print(f"DEBUG: Failed command: oiiotool --colorconfig {ocio_config} {input_file} -o {output_file}")
                    # Check if input and output files exist
                    print(f"DEBUG: Input file exists: {os.path.exists(input_file)}")
                    print(f"DEBUG: Output directory exists: {os.path.exists(os.path.dirname(output_file))}")
                    print(f"DEBUG: Output directory writable: {os.access(os.path.dirname(output_file), os.W_OK)}")
                    print(f"DEBUG: ---")
                
                # Also check temp directory status
                print(f"DEBUG: Temp directory: {self.temp_dir}")
                print(f"DEBUG: Temp directory exists: {os.path.exists(self.temp_dir)}")
                if os.path.exists(self.temp_dir):
                    print(f"DEBUG: Temp directory writable: {os.access(self.temp_dir, os.W_OK)}")
                    print(f"DEBUG: Temp directory contents: {os.listdir(self.temp_dir)}")
                    # Check disk space
                    try:
                        stat = os.statvfs(self.temp_dir)
                        free_space_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
                        print(f"DEBUG: Free space in temp directory: {free_space_mb:.2f} MB")
                    except Exception as e:
                        print(f"DEBUG: Error checking disk space: {e}")
                
                error_frames = ", ".join(str(f[0]) for f in failures[:5])
                more_text = f" and {len(failures) - 5} more" if len(failures) > 5 else ""
                
                # Get first error message for display
                first_error = failures[0][2] if failures and len(failures) > 0 and failures[0][2] else "Unknown error"
                first_error_preview = first_error[:150] + "..." if len(first_error) > 150 else first_error
                
                error_msg = (
                    f"Failed to convert {len(failures)} frames (frames {error_frames}{more_text})\n\n"
                    f"Sample error: {first_error_preview}\n\n"
                    f"Possible issues:\n"
                    f"1. Check if OCIO configuration exists at {ocio_config}\n"
                    f"2. Verify permissions on temp directory: {self.temp_dir}\n"
                    f"3. Check disk space in temp location\n"
                    f"4. Verify input EXR files exist and are readable"
                )
                print(f"DEBUG: {error_msg}")
                self.queue.put(('error', error_msg))
                return
            
            # If we get here, conversion was 100% successful
            self.queue.put(('output', "EXR conversion completed successfully\n"))
            
            # Store frame range for FFmpeg conversion
            self.temp_frame_range = (start_frame, end_frame)
            
            # Proceed with FFmpeg conversion on the main thread
            self.root.after(0, lambda: self.finish_exr_conversion_main_callback(start_frame, end_frame))

        except Exception as e:
            error_msg = f"Error during EXR conversion: {str(e)}"
            print(f"DEBUG: {error_msg}")
            self.queue.put(('error', error_msg))

    def finish_exr_conversion_main_callback(self, start_frame, end_frame):
        """
        This helper method is called on the main thread after successful EXR conversion.
        It updates the UI (setting the input folder to the temporary PNG directory and
        adjusting the filename pattern), retrieves all relevant user input parameters, and then
        starts the FFmpeg conversion using those settings.
        """
        # Update input folder with the temporary directory path.
        self.img_seq_folder.delete(0, tk.END)
        self.img_seq_folder.insert(0, self.temp_dir)
        if hasattr(self, 'img_seq_folder_var'): # Update the associated StringVar
            self.img_seq_folder_var.set(self.temp_dir)
        
        # Assemble the PNG sequence from the temporary directory.
        png_files = sorted([f for f in os.listdir(self.temp_dir) if f.endswith('.png')])
        
        if not png_files:
            self.queue.put(('error', "No PNG files found in temp directory"))
            return
            
        # Verify all expected frames exist
        expected_count = end_frame - start_frame + 1
        if len(png_files) != expected_count:
            error_msg = f"Expected {expected_count} PNG files but found {len(png_files)}"
            self.queue.put(('error', error_msg))  # Use error instead of warning to stop process
            return
        
        # Use clique to assemble the sequence properly
        collections, _ = clique.assemble(png_files)
        
        if collections:
            collection = collections[0]  # Assume only one sequence exists.
            pattern = f"{collection.head}%04d{collection.tail}"
            
            # Update the filename pattern widget.
            self.filename_pattern.delete(0, tk.END)
            self.filename_pattern.insert(0, pattern)
            if hasattr(self, 'filename_pattern_var'): # Update the associated StringVar
                self.filename_pattern_var.set(pattern)
            
            # Set the frame range and total frames for FFmpeg.
            self.frame_range = self.temp_frame_range
            self.total_frames = end_frame - start_frame + 1
            
            # Restore parameters from storage if available
            if hasattr(self, 'exr_conversion_params'):
                # Update UI widgets to match stored parameters
                self.frame_rate.delete(0, tk.END)
                self.frame_rate.insert(0, str(self.exr_conversion_params['output_framerate']))
                if hasattr(self, 'frame_rate_var'): self.frame_rate_var.set(str(self.exr_conversion_params['output_framerate']))
                
                self.source_frame_rate.delete(0, tk.END)
                self.source_frame_rate.insert(0, str(self.exr_conversion_params['source_framerate']))
                if hasattr(self, 'source_frame_rate_var'): self.source_frame_rate_var.set(str(self.exr_conversion_params['source_framerate']))

                self.desired_duration.delete(0, tk.END)
                self.desired_duration.insert(0, str(self.exr_conversion_params['desired_duration']))
                if hasattr(self, 'desired_duration_var'): self.desired_duration_var.set(str(self.exr_conversion_params['desired_duration']))
                
                # Set the codec dropdown
                self.codec_var.set(self.exr_conversion_params['codec'])
                self.update_codec()  # Update the UI for the selected codec
                
                # Set codec-specific parameters
                codec = self.exr_conversion_params['codec']
                if codec in ["h264", "h265"] and hasattr(self, 'mp4_bitrate') and hasattr(self, 'mp4_crf'):
                    self.mp4_bitrate.set(self.exr_conversion_params['bitrate'])
                    self.mp4_crf.set(self.exr_conversion_params['crf'])
                elif codec.startswith("prores") and hasattr(self, 'prores_profile') and hasattr(self, 'prores_qscale'):
                    self.prores_profile.set(self.exr_conversion_params['profile'])
                    self.prores_qscale.set(self.exr_conversion_params['qscale'])
                
                # Set output file and folder
                self.output_folder.delete(0, tk.END)
                self.output_folder.insert(0, self.exr_conversion_params['output_dir'])
                if hasattr(self, 'output_folder_var'): self.output_folder_var.set(self.exr_conversion_params['output_dir'])
                
                self.output_filename.delete(0, tk.END)
                self.output_filename.insert(0, self.exr_conversion_params['output_file'])
                if hasattr(self, 'output_filename_var'): self.output_filename_var.set(self.exr_conversion_params['output_file'])
                
                # Call update_duration to recalculate scale_factor properly
                self.update_duration()
                
                # Now that all UI is set up correctly, let the existing code handle the FFmpeg stage
                self.run_ffmpeg()
            else:
                # If parameters are missing, show error and stop
                self.queue.put(('error', "Required parameters for FFmpeg conversion are missing"))
                return
        else:
            self.queue.put(('error', "Failed to detect PNG sequence in temp directory"))

    def get_ui_parameters(self):
        # Read all critical values from UI widgets
        ui_params = {
            "codec": self.codec_var.get(),
            "frame_rate": self.frame_rate.get(),
            "desired_duration": self.desired_duration.get(),
            "output_filename": self.output_filename.get(),
            "output_folder": self.output_folder.get(),
            "mp4_bitrate": self.mp4_bitrate.get() if hasattr(self, 'mp4_bitrate') else "",
            "mp4_crf": self.mp4_crf.get() if hasattr(self, 'mp4_crf') else "",
            "prores_profile": self.prores_profile.get() if hasattr(self, 'prores_profile') else "",
            "prores_qscale": self.prores_qscale.get() if hasattr(self, 'prores_qscale') else "",
        }
        print("UI Parameters gathered:", ui_params)
        return ui_params

    def signal_handler(self, signum, frame):
        """Handle termination signals gracefully"""
        print(f"\nDEBUG: Received signal {signum}, initiating cleanup...")
        self.cleanup()
        sys.exit(0)

    def cleanup(self):
        """Centralized cleanup method"""
        if self.is_shutting_down:
            print("DEBUG: Cleanup already in progress, skipping...")
            return
            
        self.is_shutting_down = True
        print("\nDEBUG: Starting cleanup process...")
        
        # First stop all reader threads
        for thread in self.active_threads:
            try:
                if thread and thread.is_alive():
                    print(f"DEBUG: Waiting for thread to finish")
                    thread.join(timeout=2)
            except Exception as e:
                print(f"DEBUG: Error stopping thread: {e}")

        # Then terminate all processes
        for process in self.active_processes:
            try:
                if process and process.poll() is None:  # Process is still running
                    pid = process.pid
                    print(f"DEBUG: Terminating process {pid}")
                    
                    # First try SIGTERM
                    process.terminate()
                    try:
                        process.wait(timeout=3)  # Wait longer for graceful shutdown
                        print(f"DEBUG: Process {pid} terminated gracefully")
                    except subprocess.TimeoutExpired:
                        print(f"DEBUG: Process {pid} didn't terminate, sending SIGKILL")
                        # If still running, force kill
                        process.kill()
                        try:
                            process.wait(timeout=2)
                            print(f"DEBUG: Process {pid} killed")
                        except subprocess.TimeoutExpired:
                            print(f"DEBUG: Failed to kill process {pid}")
            except Exception as e:
                print(f"DEBUG: Error terminating process: {e}")
                try:
                    # Force kill as last resort
                    if process and process.pid:
                        os.kill(process.pid, signal.SIGKILL)
                        print(f"DEBUG: Sent SIGKILL to process {process.pid}")
                except Exception as kill_error:
                    print(f"DEBUG: Final kill attempt failed: {kill_error}")

        # Clean up temp directories
        try:
            # First clean up process-specific temp directory
            if hasattr(self, 'temp_dir') and self.temp_dir and os.path.exists(self.temp_dir):
                print(f"DEBUG: Removing process temp directory: {self.temp_dir}")
                for _ in range(3):  # Try a few times with delays
                    try:
                        shutil.rmtree(self.temp_dir)
                        print(f"DEBUG: Successfully removed {self.temp_dir}")
                        break
                    except Exception as e:
                        print(f"DEBUG: Failed to remove directory, retrying... Error: {e}")
                        time.sleep(1)  # Wait a bit before retrying
            
            # Then clean up base temp directory if it's empty
            if hasattr(self, 'base_temp_dir') and self.base_temp_dir and os.path.exists(self.base_temp_dir):
                try:
                    # Only remove if empty
                    if not os.listdir(self.base_temp_dir):
                        os.rmdir(self.base_temp_dir)
                        print(f"DEBUG: Removed empty base temp directory: {self.base_temp_dir}")
                except Exception as e:
                    print(f"DEBUG: Error cleaning base temp directory: {e}")
                    
        except Exception as e:
            print(f"DEBUG: Error during temp directory cleanup: {e}")

        print("DEBUG: Cleanup completed")

    def on_closing(self):
        """Handle window close button"""
        print("\nDEBUG: Application closing, initiating cleanup...")
        self.cleanup()
        self.root.destroy()

    def read_process_output(self, process, total_frames):
        import select, time
        stdout_buffer = ""
        stderr_buffer = ""
        current_frame = 0
        stdout_closed = False
        stderr_closed = False

        while not (stdout_closed and stderr_closed):
            streams = []
            if not stdout_closed:
                streams.append(process.stdout)
            if not stderr_closed:
                streams.append(process.stderr)
            if streams:
                rlist, _, _ = select.select(streams, [], [], 0.1)
            else:
                break
            for stream in rlist:
                try:
                    ch = stream.read(1)
                except Exception:
                    ch = ""
                if ch == '':
                    if stream == process.stdout:
                        stdout_closed = True
                    elif stream == process.stderr:
                        stderr_closed = True
                    continue
                if stream == process.stdout:
                    stdout_buffer += ch
                    if ch in ['\n', '\r']:
                        self.queue.put(('output', stdout_buffer))
                        print("DEBUG: OIIO STDOUT:", stdout_buffer.strip())
                        stdout_buffer = ""
                elif stream == process.stderr:
                    stderr_buffer += ch
                    if ch in ['\n', '\r']:
                        line = stderr_buffer.strip()
                        self.queue.put(('output', stderr_buffer))
                        print("DEBUG: OIIO STDERR:", line)
                        if "Writing" in line:
                            current_frame += 1
                            progress = (current_frame / total_frames) * 100
                            status = f"Converting EXR frames: {current_frame}/{total_frames} ({progress:.1f}%)"
                            self.queue.put(('progress', (progress, status)))
                        stderr_buffer = ""
            time.sleep(0.01)
        
        # Flush any remaining data from the streams.
        remaining_stdout = process.stdout.read()
        if remaining_stdout:
            self.queue.put(('output', remaining_stdout))
        remaining_stderr = process.stderr.read()
        if remaining_stderr:
            self.queue.put(('output', remaining_stderr))

    def _open_last_output_folder(self):
        if self.last_successful_output_dir:
            try:
                if sys.platform == "win32":
                    os.startfile(self.last_successful_output_dir)
                elif sys.platform == "darwin": # macOS
                    subprocess.Popen(["open", self.last_successful_output_dir])
                else: # Linux and other UNIX-like systems
                    subprocess.Popen(["xdg-open", self.last_successful_output_dir])
            except Exception as e:
                messagebox.showerror("Error", f"Failed to open output folder: {e}")
                print(f"Failed to open output folder: {e}")
        else:
            messagebox.showinfo("Info", "No output folder available. Please run a successful conversion first.")

if __name__ == "__main__":
    check_and_install_dependencies()
    root = tk.Tk()
    app = FFmpegUI(root)
    root.mainloop()