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
import importlib

# Default settings
DEFAULT_SETTINGS = {
    "last_input_folder": "",
    "last_output_folder": "",
    "frame_rate": "60",
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
        self.root.geometry("800x700")  # Increased height to accommodate new label
        self.root.minsize(600, 400)    # Set minimum window size

        # Load settings
        self.settings = self.load_settings()
        
        # Initialize the queue for thread-safe communication
        self.queue = queue.Queue()

        # Custom font
        self.custom_font = Font(family="Roboto", size=10)
        self.title_font = Font(family="Roboto", size=12, weight="bold")

        # Set up dark theme
        self.style = ttk.Style()
        self.style.theme_use("clam")

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
        
        # Button style with outline and round edges
        self.style.configure("TButton",
                             padding=6,
                             relief="flat",
                             background="#3c3f41",
                             borderwidth=1,
                             bordercolor="#ffffff",
                             lightcolor="#ffffff",
                             darkcolor="#ffffff")
        self.style.map("TButton",
                       background=[('active', '#4c4c4c')])
        
        # Configure grid
        self.root.grid_columnconfigure(1, weight=1)
        for i in range(12):  # Increased range to accommodate new widgets
            self.root.grid_rowconfigure(i, weight=1)

        # Configure Combobox style for dark selection
        self.style.map('TCombobox',
            selectbackground=[('readonly', '#404040')],
            selectforeground=[('readonly', '#ffffff')],
            fieldbackground=[('readonly', '#2b2b2b')],
            background=[('readonly', '#2b2b2b')]
        )

        # Load last used input folder
        self.last_input_folder = self.settings["last_input_folder"]

        # Image Sequence Selection
        ttk.Label(root, text="Image Sequence Folder:", font=self.title_font).grid(row=0, column=0, sticky="w", padx=10, pady=(20,5))
        self.img_seq_folder = ttk.Entry(root)
        self.img_seq_folder.grid(row=0, column=1, sticky="ew", padx=10, pady=(20,5))
        self.img_seq_folder.insert(0, self.last_input_folder)
        ttk.Button(root, text="Browse", command=self.browse_img_seq).grid(row=0, column=2, padx=10, pady=(20,5))

        ttk.Label(root, text="Filename Pattern:", font=self.title_font).grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.filename_pattern = ttk.Entry(root)
        self.filename_pattern.grid(row=1, column=1, columnspan=2, sticky="ew", padx=10, pady=5)

        # Codec Selection
        ttk.Label(root, text="Codec:", font=self.title_font).grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.codec_var = tk.StringVar(value=self.settings["codec"])
        self.codec_dropdown = ttk.Combobox(root, textvariable=self.codec_var, values=["h264", "h265", "prores_422", "prores_422_lt", "prores_444", "qtrle"], state="readonly")
        self.codec_dropdown.grid(row=2, column=1, columnspan=2, sticky="ew", padx=10, pady=5)
        self.codec_dropdown.bind("<<ComboboxSelected>>", self.update_codec)

        # Frame Rate Selection
        ttk.Label(root, text="Frame Rate (fps):", font=self.title_font).grid(row=3, column=0, sticky="w", padx=10, pady=5)
        self.frame_rate = ttk.Entry(root)
        self.frame_rate.insert(0, self.settings["frame_rate"])
        self.frame_rate.grid(row=3, column=1, columnspan=2, sticky="ew", padx=10, pady=5)
        self.frame_rate.bind("<KeyRelease>", self.update_duration)  # Update duration on frame rate change

        # Desired Duration Input
        ttk.Label(root, text="Desired Duration (seconds):", font=self.title_font).grid(row=4, column=0, sticky="w", padx=10, pady=5)
        self.desired_duration = ttk.Entry(root)
        self.desired_duration.insert(0, self.settings["desired_duration"])
        self.desired_duration.grid(row=4, column=1, columnspan=2, sticky="ew", padx=10, pady=5)
        self.desired_duration.bind("<KeyRelease>", self.update_duration)  # Update duration on duration change

        # Output File Name
        ttk.Label(root, text="Output Filename:", font=self.title_font).grid(row=5, column=0, sticky="w", padx=10, pady=5)
        self.output_filename = ttk.Entry(root)
        self.output_filename.insert(0, "output.mp4")
        self.output_filename.grid(row=5, column=1, columnspan=2, sticky="ew", padx=10, pady=5)

        # Output Folder Selection
        ttk.Label(root, text="Output Folder:", font=self.title_font).grid(row=6, column=0, sticky="w", padx=10, pady=5)
        self.output_folder = ttk.Entry(root)
        self.output_folder.grid(row=6, column=1, sticky="ew", padx=10, pady=5)
        # Initialize output folder from settings
        if self.settings["last_output_folder"]:
            self.output_folder.insert(0, self.settings["last_output_folder"])
        ttk.Button(root, text="Browse", command=self.browse_output_folder).grid(row=6, column=2, padx=10, pady=5)

        # Run Button
        ttk.Button(root, text="Run FFmpeg", command=self.run_ffmpeg).grid(row=7, column=1, pady=20)

        # Codec-specific options frames
        self.h264_h265_frame = ttk.Frame(root)
        self.h264_h265_frame.grid(row=8, column=0, columnspan=3, sticky="ew", padx=10, pady=5)

        self.prores_frame = ttk.Frame(root)
        self.prores_frame.grid(row=8, column=0, columnspan=3, sticky="ew", padx=10, pady=5)
        self.prores_frame.grid_remove()  # Initially hidden

        # Initialize codec-specific variables
        self.prores_profile = tk.StringVar()
        self.prores_qscale = tk.StringVar()
        self.mp4_bitrate = tk.StringVar()
        self.mp4_crf = tk.StringVar()

        # Populate h264/h265 settings
        ttk.Label(self.h264_h265_frame, text="Bitrate (Mbps):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.bitrate_entry = ttk.Entry(self.h264_h265_frame, textvariable=self.mp4_bitrate, width=10)
        self.bitrate_entry.insert(0, "30")
        self.bitrate_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(self.h264_h265_frame, text="CRF:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.crf_entry = ttk.Entry(self.h264_h265_frame, textvariable=self.mp4_crf, width=10)
        self.crf_entry.insert(0, "23")
        self.crf_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)

        # Populate ProRes settings
        ttk.Label(self.prores_frame, text="ProRes Profile:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.prores_profile_label = ttk.Label(self.prores_frame, text="422")
        self.prores_profile_label.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

        ttk.Label(self.prores_frame, text="Quality (qscale:v):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.qscale_entry = ttk.Entry(self.prores_frame, textvariable=self.prores_qscale, width=10)
        self.qscale_entry.insert(0, "9")
        self.qscale_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)

        # Progress Bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(root, variable=self.progress_var, maximum=100, mode='determinate')
        self.progress_bar.grid(row=9, column=0, columnspan=3, sticky='ew', padx=10, pady=(20,5))

        # Status Label
        self.status_label = ttk.Label(root, text="", font=self.custom_font)
        self.status_label.grid(row=10, column=0, columnspan=3, padx=10, pady=(5,20))

        # FFmpeg Output Text Widget
        self.output_text = tk.Text(root, height=10, width=80, wrap=tk.WORD, bg='#1e1e1e', fg='#ffffff')
        self.output_text.grid(row=11, column=0, columnspan=3, padx=10, pady=10, sticky='nsew')
        self.output_scrollbar = ttk.Scrollbar(root, orient='vertical', command=self.output_text.yview)
        self.output_scrollbar.grid(row=11, column=3, sticky='ns')
        self.output_text['yscrollcommand'] = self.output_scrollbar.set

        # Configure the new row to expand
        root.grid_rowconfigure(11, weight=1)

        # Initialize codec-specific UI based on default selection
        self.update_codec()

        # Start the queue processing loop
        self.root.after(100, self.process_queue)

    def browse_img_seq(self):
        current_dir = self.img_seq_folder.get()
        if not current_dir or not os.path.isdir(current_dir):
            initial_dir = self.settings["last_input_folder"]
        else:
            initial_dir = current_dir

        folder = filedialog.askdirectory(initialdir=initial_dir)
        if folder:
            self.img_seq_folder.delete(0, tk.END)
            self.img_seq_folder.insert(0, folder)
            self.update_filename_pattern(folder)
            self.save_settings()  # Save settings after updating input folder
            self.update_output_folder(folder)
            self.update_duration()

    def update_filename_pattern(self, folder):
        try:
            files = os.listdir(folder)
            image_files = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp'))]
            
            if image_files:
                # Group files by their base pattern (everything before the frame number)
                sequence_groups = {}
                for filename in image_files:
                    # Split the filename into parts
                    base, ext = os.path.splitext(filename)  # First split off the final extension
                    if '.' in base:  # If there's another dot (for frame number)
                        pattern_base, frame_number = base.rsplit('.', 1)  # Split at the last dot before extension
                        if frame_number.isdigit():  # Only process if the part between dots is a number
                            if pattern_base not in sequence_groups:
                                sequence_groups[pattern_base] = []
                            sequence_groups[pattern_base].append(filename)
                
                # Convert groups to collections
                all_collections = []
                for base_pattern, files in sequence_groups.items():
                    if len(files) > 1:  # Only create a collection if there are multiple files
                        collection_files = sorted(files)  # Sort files to ensure proper order
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
                                pattern = f"{collection.head}%0{collection.padding}d{collection.tail}"
                                self.filename_pattern.delete(0, tk.END)
                                self.filename_pattern.insert(0, pattern)
                                
                                self.frame_range = (min(collection.indexes), max(collection.indexes))
                                self.total_frames = len(collection.indexes)
                                
                                # Update output filename
                                output_name = collection.head.rstrip('_.')
                                self.output_filename.delete(0, tk.END)
                                self.output_filename.insert(0, output_name)
                                
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
                        pattern = f"{collection.head}%0{collection.padding}d{collection.tail}"
                        self.filename_pattern.delete(0, tk.END)
                        self.filename_pattern.insert(0, pattern)
                        
                        self.frame_range = (min(collection.indexes), max(collection.indexes))
                        self.total_frames = len(collection.indexes)
                        
                        # Update output filename
                        output_name = collection.head.rstrip('_.')
                        self.output_filename.delete(0, tk.END)
                        self.output_filename.insert(0, output_name)
                        
                        # Update duration
                        self.update_duration()
                else:
                    messagebox.showwarning("Warning", "No image sequence found in the selected folder.")
                    self.total_frames = 0
                    self.desired_duration.delete(0, tk.END)
                    self.desired_duration.insert(0, "0")
            else:
                messagebox.showwarning("Warning", "No image files found in the selected folder.")
                self.total_frames = 0
                self.desired_duration.delete(0, tk.END)
                self.desired_duration.insert(0, "0")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update filename pattern: {e}")
            self.total_frames = 0
            self.desired_duration.delete(0, tk.END)
            self.desired_duration.insert(0, "0")

    def update_output_folder(self, input_folder):
        """Update output folder with option to use parent directory of input folder"""
        output_folder = os.path.dirname(input_folder)
        current_output = self.output_folder.get()
        
        # If there's no current output folder set, or it's different from the suggested one
        if not current_output or current_output != output_folder:
            response = messagebox.askyesno(
                "Update Output Folder",
                f"Would you like to set the output folder to:\n{output_folder}?"
            )
            if response:
                self.output_folder.delete(0, tk.END)
                self.output_folder.insert(0, output_folder)
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
            "last_input_folder": self.img_seq_folder.get(),
            "last_output_folder": self.output_folder.get(),
            "frame_rate": self.frame_rate.get(),
            "desired_duration": self.desired_duration.get(),
            "codec": self.codec_var.get(),
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
        initial_dir = self.output_folder.get() or self.settings["last_output_folder"]
        folder = filedialog.askdirectory(initialdir=initial_dir)
        if folder:
            self.output_folder.delete(0, tk.END)
            self.output_folder.insert(0, folder)
            self.save_settings()  # Save settings after updating output folder

    def update_codec(self, event=None):
        codec = self.codec_var.get()
        print(f"Selected codec: {codec}")

        if codec in ["h264", "h265"]:
            self.h264_h265_frame.grid()
            self.prores_frame.grid_remove()
            # Set MP4 values from settings
            if hasattr(self, 'mp4_bitrate'):
                self.mp4_bitrate.set(self.settings["mp4_bitrate"])
            if hasattr(self, 'mp4_crf'):
                self.mp4_crf.set(self.settings["mp4_crf"])
        elif codec.startswith("prores"):
            self.h264_h265_frame.grid_remove()
            self.prores_frame.grid()
            # Set ProRes profile based on selection
            if codec == "prores_422":
                self.prores_profile.set("2")  # Standard 422
                self.prores_profile_label.config(text="422")
            elif codec == "prores_422_lt":
                self.prores_profile.set("1")  # 422 LT
                self.prores_profile_label.config(text="422 LT")
            elif codec == "prores_444":
                self.prores_profile.set("4")  # 4444
                self.prores_profile_label.config(text="4444")
            # Set default ProRes Qscale
            self.prores_qscale.set("9")
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
            if hasattr(self, 'prores_qscale'):
                self.prores_qscale.set(self.settings["prores_qscale"])
            if hasattr(self, 'prores_profile'):
                self.prores_profile.set(self.settings["prores_profile"])
            self.h264_h265_frame.grid_remove()
            self.prores_frame.grid_remove()

        self.save_settings()  # Save settings after updating codec
        self.update_duration()

    def update_duration(self, event=None):
        # This method now calculates the scale factor based on desired duration and frame rate
        if hasattr(self, 'total_frames') and self.total_frames > 0:
            try:
                frame_rate = float(self.frame_rate.get())
                desired_duration = float(self.desired_duration.get())
                if frame_rate <= 0 or desired_duration <= 0:
                    raise ValueError
                scale_factor = desired_duration * frame_rate / self.total_frames
                self.scale_factor = scale_factor  # Store scale factor for use in run_ffmpeg
                print(f"Scale factor updated to: {scale_factor}")  # Debug statement
                # Optionally, update a label or status to show scale factor
            except ValueError:
                self.scale_factor = None
                # Optionally, display an error message or indicator
        else:
            self.scale_factor = None

    def run_ffmpeg(self):
        # Check input directory and files
        img_folder = self.img_seq_folder.get()
        if not os.path.exists(img_folder):
            messagebox.showerror("Error", f"Input folder does not exist: {img_folder}")
            return

        # Get and validate output directory
        output_dir = self.output_folder.get().strip()
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
        output_file = self.output_filename.get().strip()
        if not output_file:
            messagebox.showerror("Error", "Please enter an output filename")
            return

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

        if not os.access(img_folder, os.R_OK):
            messagebox.showerror("Error", f"Cannot read from input folder: {img_folder}")
            return

        # Verify at least one input file exists
        pattern = self.filename_pattern.get()
        test_file = os.path.join(img_folder, pattern % self.frame_range[0])
        if not os.path.exists(test_file):
            messagebox.showerror("Error", f"Cannot find first frame: {test_file}")
            return

        # Add debug output
        self.queue.put(('output', f"Input folder: {img_folder}\n"))
        self.queue.put(('output', f"Output directory: {output_dir}\n"))
        self.queue.put(('output', f"First frame path: {test_file}\n"))

        img_folder = self.img_seq_folder.get()
        pattern = self.filename_pattern.get()
        codec = self.codec_var.get()
        try:
            framerate = float(self.frame_rate.get())
            desired_duration = float(self.desired_duration.get())
            if framerate <= 0 or desired_duration <= 0:
                raise ValueError
        except ValueError:
            self.queue.put(('error', "Please enter valid frame rate and desired duration."))
            return

        # Calculate the exact number of frames needed for the desired duration
        total_frames_needed = int(round(framerate * desired_duration))  # Added round() function

        # Calculate the actual duration based on the exact number of frames
        actual_duration = total_frames_needed / framerate

        output_file = self.output_filename.get().strip()
        output_dir = self.output_folder.get()

        if not all([img_folder, pattern, framerate, output_file, output_dir]):
            self.queue.put(('error', "Please fill in all fields."))
            return

        # Determine the correct file extension
        file_extension = ".mp4" if codec in ["h264", "h265"] else ".mov"
        
        # Ensure the output filename does not end with a dot or underscore
        output_file_base = output_file.rstrip('_.')
        
        # Split the filename to remove any existing extension
        output_file_base, _ = os.path.splitext(output_file_base)
        
        # Ensure no trailing dots after splitting
        output_file_base = output_file_base.rstrip('.')
        
        # Append the correct extension
        output_file = f"{output_file_base}{file_extension}"

        # Use the frame range information
        if hasattr(self, 'frame_range') and self.total_frames > 0:
            start_frame, end_frame = self.frame_range
            input_pattern = pattern  # Use the original pattern with correct padding
            input_path = os.path.join(img_folder, input_pattern)
            input_args = [
                "-start_number", str(start_frame),
                "-i", input_path
            ]
        else:
            self.queue.put(('error', "Frame range not detected. Please select the image sequence folder again."))
            return

        output_path = os.path.join(output_dir, output_file)

        # Determine the codec parameters
        codec_params = []
        if codec in ["h264", "h265"]:
            bitrate = self.mp4_bitrate.get()
            crf = self.mp4_crf.get()
            if not bitrate or not crf:
                self.queue.put(('error', "Bitrate and CRF settings are required for H.264/H.265 encoding."))
                return
            
            codec_lib = "libx264" if codec == "h264" else "libx265"
            codec_params = [
                "-c:v", codec_lib,
                "-preset", "medium",
                "-b:v", f"{bitrate}M",
                "-maxrate", f"{int(float(bitrate)*2)}M",
                "-bufsize", f"{int(float(bitrate)*2)}M"
            ]
            if codec == "h264":
                codec_params.extend(["-profile:v", "high", "-level:v", "5.1"])
            else:  # h265
                codec_params.extend(["-tag:v", "hvc1"])
        elif codec.startswith("prores"):
            profile = self.prores_profile.get()
            qscale = self.prores_qscale.get()
            if not profile or not qscale:
                self.queue.put(('error', "ProRes profile and Quality settings are required for ProRes encoding."))
                return
            
            codec_params = [
                "-c:v", "prores_ks",
                "-profile:v", profile,
                "-qscale:v", qscale
            ]
        elif codec == "qtrle":
            codec_params = [
                "-c:v", "qtrle",
                "-pix_fmt", "rgb24"  # Use rgb24 for Animation codec
            ]
        else:
            self.queue.put(('error', "Unsupported codec selected."))
            return

        # Calculate scale factor with higher precision
        scale_factor = total_frames_needed / (self.total_frames - 1)  # Adjusted for frame counting

        # Use the exact scale factor in the setpts filter with higher precision
        # Modified to include PTS-STARTPTS for clean timestamps
        setpts_filter = f"setpts={scale_factor:.10f}*PTS, setpts=PTS-STARTPTS"
        ffmpeg_filters = f"{setpts_filter},scale=in_color_matrix=bt709:out_color_matrix=bt709"

        ffmpeg_filter_args = ["-vf", ffmpeg_filters]

        # Add -frames:v argument to limit the number of output frames
        frames_arg = ["-frames:v", str(total_frames_needed)]

        # Color space settings
        color_space_args = [
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-colorspace", "bt709"
        ]

        # Base ffmpeg command with precise NTSC timing parameters
        cmd = [
            "ffmpeg",
            "-accurate_seek",
            "-ss", "0",  # Start from beginning
            "-t", f"{desired_duration:.6f}",  # Duration before input for better precision
            "-framerate", f"{framerate}"  # Use exact framerate from user input
        ] + input_args + [
            "-r", str(framerate),  # Set output framerate
            "-vsync", "cfr"  # Moved -vsync cfr immediately after input
        ] + ffmpeg_filter_args + frames_arg + [
            "-pix_fmt", "yuv420p",
            "-video_track_timescale", "30000",  # Proper NTSC timing
            "-an"
        ] + codec_params + color_space_args + [
            output_path
        ]

        print("FFmpeg command:", " ".join(cmd))  # Debug statement

        # Execute the ffmpeg command in a separate thread
        thread = threading.Thread(target=self.execute_ffmpeg, args=(cmd, output_path, actual_duration))
        thread.start()

    def execute_ffmpeg(self, cmd, output_path, actual_duration):
        try:
            # Start FFmpeg process
            self.queue.put(('output', "Starting FFmpeg process...\n"))
            
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            self.queue.put(('output', f"Process started with PID: {process.pid}\n"))

            # Function to read stdout
            def read_stdout():
                try:
                    for line in process.stdout:
                        self.queue.put(('output', line))
                        if "frame=" in line:
                            match = re.search(r'frame=\s*(\d+)', line)
                            if match:
                                current_frame = int(match.group(1)) + self.frame_range[0] - 1
                                progress = (current_frame - self.frame_range[0] + 1) / self.total_frames * 100
                                status = f"Processing frame {current_frame} of {self.frame_range[0] + self.total_frames - 1}"
                                self.queue.put(('progress', (progress, status)))
                except Exception as e:
                    self.queue.put(('output', f"\nOutput Reader Error: {str(e)}\n"))

            # Function to read stderr
            def read_stderr():
                try:
                    for line in process.stderr:
                        self.queue.put(('output', f"ERROR: {line}"))
                except Exception as e:
                    self.queue.put(('output', f"\nError Reading Stderr: {str(e)}\n"))

            # Start threads to read stdout and stderr
            stdout_thread = threading.Thread(target=read_stdout)
            stderr_thread = threading.Thread(target=read_stderr)
            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()

            # Wait for FFmpeg process to complete
            process.wait()
            stdout_thread.join()
            stderr_thread.join()

            if process.returncode != 0:
                self.queue.put(('error', f"FFmpeg process returned {process.returncode}"))
            else:
                success_message = f"Video created at {output_path}\nActual duration: {actual_duration:.3f} seconds"
                self.queue.put(('success', success_message))
            
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
        except queue.Empty:
            pass
        finally:
            # Schedule the next queue check
            self.root.after(100, self.process_queue)

if __name__ == "__main__":
    check_and_install_dependencies()
    root = tk.Tk()
    app = FFmpegUI(root)
    root.mainloop()