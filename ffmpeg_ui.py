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
import inspect

# Add this at the start of your script
sys.stdout = open('ffmpeg_ui.log', 'a')
sys.stderr = open('ffmpeg_ui.error.log', 'a')

class FFmpegUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FFmpeg GUI")
        self.root.configure(bg='#2b2b2b')
        self.root.geometry("800x700")  # Increased height to accommodate new label
        self.root.minsize(600, 400)    # Set minimum window size

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
        for i in range(13):  # Increased range to accommodate new widgets
            self.root.grid_rowconfigure(i, weight=1)

        # Load last used input folder
        self.last_input_folder = self.load_last_input_folder()

        # Input Type Selection
        ttk.Label(root, text="Input Type:", font=self.title_font).grid(row=0, column=0, sticky="w", padx=10, pady=(20,5))
        self.input_type_var = tk.StringVar(value="Image Sequence")
        self.input_type_dropdown = ttk.Combobox(root, textvariable=self.input_type_var, values=["Image Sequence", "Video File"], state="readonly")
        self.input_type_dropdown.grid(row=0, column=1, sticky="ew", padx=10, pady=(20,5))
        self.input_type_dropdown.bind("<<ComboboxSelected>>", self.update_input_type)

        # Create frames for input selections
        self.image_sequence_frame = ttk.Frame(root)
        self.image_sequence_frame.grid(row=1, column=0, columnspan=3, sticky='ew')
        self.video_file_frame = ttk.Frame(root)
        self.video_file_frame.grid(row=1, column=0, columnspan=3, sticky='ew')
        self.video_file_frame.grid_remove()  # Hide video file frame initially

        # Image Sequence Selection
        ttk.Label(self.image_sequence_frame, text="Image Sequence Folder:", font=self.title_font).grid(row=0, column=0, sticky="w", padx=10, pady=(20,5))
        self.img_seq_folder = ttk.Entry(self.image_sequence_frame)
        self.img_seq_folder.grid(row=0, column=1, sticky="ew", padx=10, pady=(20,5))
        self.img_seq_folder.insert(0, self.last_input_folder)
        ttk.Button(self.image_sequence_frame, text="Browse", command=self.browse_img_seq).grid(row=0, column=2, padx=10, pady=(20,5))

        ttk.Label(self.image_sequence_frame, text="Filename Pattern:", font=self.title_font).grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.filename_pattern = ttk.Entry(self.image_sequence_frame)
        self.filename_pattern.grid(row=1, column=1, columnspan=2, sticky="ew", padx=10, pady=5)

        # Video File Selection
        ttk.Label(self.video_file_frame, text="Video File:", font=self.title_font).grid(row=0, column=0, sticky="w", padx=10, pady=(20,5))
        self.video_file_entry = ttk.Entry(self.video_file_frame)
        self.video_file_entry.grid(row=0, column=1, sticky="ew", padx=10, pady=(20,5))
        self.video_file_entry.bind('<KeyRelease>', self.validate_video_path)  # Add binding for manual path entry
        ttk.Button(self.video_file_frame, text="Browse", command=self.browse_video_file).grid(row=0, column=2, padx=10, pady=(20,5))

        # Codec Selection
        ttk.Label(root, text="Codec:", font=self.title_font).grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.codec_var = tk.StringVar(value="h265")
        self.codec_dropdown = ttk.Combobox(root, textvariable=self.codec_var, values=["h264", "h265", "prores_422", "prores_422_lt", "prores_444", "qtrle"], state="readonly")
        self.codec_dropdown.grid(row=2, column=1, columnspan=2, sticky="ew", padx=10, pady=5)
        self.codec_dropdown.bind("<<ComboboxSelected>>", self.update_codec)

        # Frame Rate Selection
        ttk.Label(root, text="Frame Rate (fps):", font=self.title_font).grid(row=3, column=0, sticky="w", padx=10, pady=5)
        self.frame_rate = ttk.Entry(root)
        self.frame_rate.insert(0, "60")
        self.frame_rate.grid(row=3, column=1, columnspan=2, sticky="ew", padx=10, pady=5)
        self.frame_rate.bind("<KeyRelease>", self.update_duration)  # Update duration on frame rate change

        # Desired Duration Input
        ttk.Label(root, text="Desired Duration (seconds):", font=self.title_font).grid(row=4, column=0, sticky="w", padx=10, pady=5)
        self.desired_duration = ttk.Entry(root)
        self.desired_duration.insert(0, "15")
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

    def update_input_type(self, event=None):
        input_type = self.input_type_var.get()
        if input_type == "Image Sequence":
            self.image_sequence_frame.grid()
            self.video_file_frame.grid_remove()
        elif input_type == "Video File":
            self.image_sequence_frame.grid_remove()
            self.video_file_frame.grid()
        else:
            pass
        self.update_duration()  # Update duration when input type changes

    def browse_img_seq(self):
        current_dir = self.img_seq_folder.get()
        if not current_dir or not os.path.isdir(current_dir):
            initial_dir = self.last_input_folder
        else:
            initial_dir = current_dir

        folder = filedialog.askdirectory(initialdir=initial_dir)
        if folder:
            self.img_seq_folder.delete(0, tk.END)
            self.img_seq_folder.insert(0, folder)
            self.update_filename_pattern(folder)
            self.save_last_input_folder(folder)
            self.update_output_folder(folder)
            self.update_duration()  # Update duration after selecting new folder

    def browse_video_file(self):
        file_path = filedialog.askopenfilename(
            initialdir=self.last_input_folder,
            title="Select Video File",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.avi"),  # Changed from semicolons to spaces
                ("MP4 files", "*.mp4"),
                ("MOV files", "*.mov"),
                ("AVI files", "*.avi"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.video_file_entry.delete(0, tk.END)
            self.video_file_entry.insert(0, file_path)
            self.save_last_input_folder(os.path.dirname(file_path))
            self.update_output_folder(os.path.dirname(file_path))
            self.update_video_file_duration(file_path)

    def update_video_file_duration(self, file_path):
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration,r_frame_rate",
                "-of", "json",
                file_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            
            if result.returncode != 0:
                raise ValueError(f"ffprobe error: {result.stderr.strip()}")
            
            data = json.loads(result.stdout)
            streams = data.get('streams', [])
            
            if not streams:
                raise ValueError("No video streams found in the file.")
            
            stream = streams[0]
            
            # Parse duration
            duration_str = stream.get('duration', None)
            if duration_str is None:
                raise ValueError("Duration not found in ffprobe output.")
            
            try:
                duration = float(duration_str)
            except ValueError:
                raise ValueError(f"Invalid duration value: '{duration_str}'")
            
            # Parse frame rate
            frame_rate_str = stream.get('r_frame_rate', '0/1')
            if '/' in frame_rate_str:
                num_str, denom_str = frame_rate_str.split('/')
                try:
                    num = float(num_str.strip())
                    denom = float(denom_str.strip())
                    if denom == 0:
                        raise ValueError("Denominator in frame rate is zero.")
                    frame_rate = num / denom
                except ValueError as ve:
                    raise ValueError(f"Invalid frame rate components: {ve}")
            else:
                try:
                    frame_rate = float(frame_rate_str)
                except ValueError:
                    raise ValueError(f"Invalid frame rate value: '{frame_rate_str}'")
            
            if frame_rate <= 0:
                raise ValueError("Frame rate must be greater than zero.")
            
            self.video_duration = duration
            self.video_frame_rate = frame_rate
            self.video_total_frames = int(round(duration * frame_rate))
            self.total_frames = self.video_total_frames  # For consistency
            
            # Update the frame_rate and desired_duration entries
            self.frame_rate.delete(0, tk.END)
            self.frame_rate.insert(0, f"{frame_rate:.2f}")
            self.desired_duration.delete(0, tk.END)
            self.desired_duration.insert(0, f"{duration:.2f}")
            
            # Update output filename based on input filename
            input_filename = os.path.splitext(os.path.basename(file_path))[0]
            self.output_filename.delete(0, tk.END)
            self.output_filename.insert(0, input_filename)
            
            self.update_duration()
            
        except Exception as e:
            self.queue.put(('error', f"Failed to get video information: {e}"))
            self.video_duration = None
            self.video_frame_rate = None
            self.video_total_frames = None
            self.total_frames = None

    def update_filename_pattern(self, folder):
        try:
            files = os.listdir(folder)
            image_files = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp'))]
            if image_files:
                collections, remainder = clique.assemble(image_files)
                
                if collections:
                    collection = collections[0]
                    pattern = f"{collection.head}%0{collection.padding}d{collection.tail}"
                    first_frame = min(collection.indexes)
                    last_frame = max(collection.indexes)
                    
                    self.filename_pattern.delete(0, tk.END)
                    self.filename_pattern.insert(0, pattern)
                    
                    self.frame_range = (first_frame, last_frame)
                    self.total_frames = len(collection.indexes)  # Store total frames
                    
                    # Update duration
                    self.update_duration()

                    # Update output filename without extension and remove trailing dots or underscores
                    output_name = collection.head.rstrip('_.')
                    self.output_filename.delete(0, tk.END)
                    self.output_filename.insert(0, output_name)
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
        output_folder = os.path.dirname(input_folder)
        self.output_folder.delete(0, tk.END)
        self.output_folder.insert(0, output_folder)

    def load_last_input_folder(self):
        try:
            with open('last_input_folder.json', 'r') as f:
                return json.load(f)['folder']
        except:
            return ""

    def save_last_input_folder(self, folder):
        with open('last_input_folder.json', 'w') as f:
            json.dump({'folder': folder}, f)

    def browse_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder.delete(0, tk.END)
            self.output_folder.insert(0, folder)

    def update_codec(self, event=None):
        codec = self.codec_var.get()
        print(f"Selected codec: {codec}")  # Debug statement

        if codec in ["h264", "h265"]:
            self.h264_h265_frame.grid()
            self.prores_frame.grid_remove()
            # Set default ProRes values to None
            self.prores_qscale.set("")
            self.prores_profile.set("")
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
            self.h264_h265_frame.grid_remove()
            self.prores_frame.grid_remove()

        self.update_duration()  # Update duration when codec changes

    def update_duration(self, event=None):
        input_type = self.input_type_var.get()
        if input_type == "Image Sequence":
            if hasattr(self, 'total_frames') and self.total_frames > 0:
                try:
                    frame_rate = float(self.frame_rate.get())
                    desired_duration = float(self.desired_duration.get())
                    if frame_rate <= 0 or desired_duration <= 0:
                        raise ValueError
                    scale_factor = desired_duration * frame_rate / self.total_frames
                    self.scale_factor = scale_factor  # Store scale factor for use in run_ffmpeg
                    print(f"Scale factor updated to: {scale_factor}")  # Debug statement
                except ValueError:
                    self.scale_factor = None
            else:
                self.scale_factor = None
        elif input_type == "Video File":
            if hasattr(self, 'video_total_frames') and self.video_total_frames > 0:
                try:
                    frame_rate = float(self.frame_rate.get())
                    desired_duration = float(self.desired_duration.get())
                    if frame_rate <= 0 or desired_duration <= 0:
                        raise ValueError
                    scale_factor = desired_duration * frame_rate / self.video_total_frames
                    self.scale_factor = scale_factor
                    print(f"Scale factor updated to: {scale_factor}")  # Debug statement
                except ValueError:
                    self.scale_factor = None
            else:
                self.scale_factor = None
        else:
            self.scale_factor = None

    def run_ffmpeg(self):
        print("\nDEBUG -- VALIDATION CHECK")
        print(f"Line number: {inspect.currentframe().f_lineno}")  # Ensures 'import inspect' is present

        input_type = self.input_type_var.get()
        output_dir = self.output_folder.get().strip()
        output_file = self.output_filename.get().strip()
        codec = self.codec_var.get()

        print(f"Input Type: {input_type}")
        print(f"Output Dir: {output_dir}")
        print(f"Output File: {output_file}")
        print(f"Codec: {codec}")

        # Initialize variables
        img_folder = ""
        pattern = ""
        framerate = 0.0
        desired_duration = 0.0
        video_file_path = ""
        scale_factor = 1.0  # Default scale factor

        # Input-Type Specific Validation
        missing_fields = []

        if input_type == "Video File":
            video_file_path = self.video_file_entry.get().strip()
            if not video_file_path:
                missing_fields.append("Video File")
            if not output_dir:
                missing_fields.append("Output Folder")
            if not output_file:
                missing_fields.append("Output Filename")

            if missing_fields:
                self.queue.put(('error', f"Missing required fields: {', '.join(missing_fields)}"))
                return

            # Additional validations for video file
            try:
                framerate = float(self.frame_rate.get())
                desired_duration = float(self.desired_duration.get())
                if framerate <= 0 or desired_duration <= 0:
                    raise ValueError
            except ValueError:
                self.queue.put(('error', "Please enter valid frame rate and desired duration."))
                return

            # Validate the existence and readability of the video file
            if not os.path.exists(video_file_path):
                messagebox.showerror("Error", f"Video file does not exist: {video_file_path}")
                return
            if not os.access(video_file_path, os.R_OK):
                messagebox.showerror("Error", f"Cannot read video file: {video_file_path}")
                return

            # Calculate the exact number of frames needed for the desired duration
            total_frames_needed = int(round(framerate * desired_duration))  # Preserved rounding
            actual_duration = total_frames_needed / framerate

            # Calculate scale factor based on video duration
            if hasattr(self, 'video_duration') and self.video_duration > 0:
                scale_factor = desired_duration / self.video_duration
                print(f"Scale factor updated to: {scale_factor}")  # Debug statement
            else:
                self.queue.put(('error', "Video duration not detected. Please select the video file again."))
                return

            # Prepare input arguments for FFmpeg (Preserved)
            input_args = ["-i", video_file_path]

        elif input_type == "Image Sequence":
            img_folder = self.img_seq_folder.get().strip()
            pattern = self.filename_pattern.get().strip()
            if not img_folder:
                missing_fields.append("Image Sequence Folder")
            if not pattern:
                missing_fields.append("Filename Pattern")
            if not output_dir:
                missing_fields.append("Output Folder")
            if not output_file:
                missing_fields.append("Output Filename")

            if missing_fields:
                self.queue.put(('error', f"Missing required fields: {', '.join(missing_fields)}"))
                return

            # Additional validations for image sequence
            try:
                framerate = float(self.frame_rate.get())
                desired_duration = float(self.desired_duration.get())
                if framerate <= 0 or desired_duration <= 0:
                    raise ValueError
            except ValueError:
                self.queue.put(('error', "Please enter valid frame rate and desired duration."))
                return

            # Validate the existence of the image sequence folder
            if not os.path.isdir(img_folder):
                self.queue.put(('error', f"Image sequence folder does not exist: {img_folder}"))
                return

            # Verify at least one image file exists
            test_file = os.path.join(img_folder, pattern % self.frame_range[0])
            if not os.path.exists(test_file):
                self.queue.put(('error', f"Cannot find first frame: {test_file}"))
                return

            # Calculate the exact number of frames needed for the desired duration
            total_frames_needed = int(round(framerate * desired_duration))  # Preserved rounding
            actual_duration = total_frames_needed / framerate

            # Calculate scale factor based on total frames
            if hasattr(self, 'total_frames') and self.total_frames > 0:
                scale_factor = desired_duration * framerate / self.total_frames
                print(f"Scale factor updated to: {scale_factor}")  # Debug statement
            else:
                self.queue.put(('error', "Frame range not detected. Please select the image sequence folder again."))
                return

            # Prepare input arguments for FFmpeg (Preserved)
            input_args = [
                "-start_number", str(self.frame_range[0]),
                "-i", os.path.join(img_folder, pattern)
            ]

        else:
            self.queue.put(('error', "Unsupported input type selected."))
            return

        # Determine the correct file extension based on codec (Preserved)
        file_extension = ".mp4" if codec in ["h264", "h265"] else ".mov"

        # Clean the output filename and append the correct extension (Preserved)
        output_file_base = output_file.rstrip('_.')
        output_file_base, _ = os.path.splitext(output_file_base)
        output_file_base = output_file_base.rstrip('.')
        output_file = f"{output_file_base}{file_extension}"

        output_path = os.path.join(output_dir, output_file)

        # Check and create output directory if it doesn't exist (Preserved)
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                print(f"Created output directory: {output_dir}")  # Debug statement
            except Exception as e:
                messagebox.showerror("Error", f"Cannot create output directory: {e}")
                return

        if not os.access(output_dir, os.W_OK):
            self.queue.put(('error', f"Cannot write to output directory: {output_dir}"))
            return

        # Determine codec parameters (Preserved)
        codec_params = self.get_codec_params(codec)
        if codec_params is None:
            # Error already queued in get_codec_params
            return

        # Color space settings (Preserved)
        color_space_args = [
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-colorspace", "bt709"
        ]

        # Set PTS filter with high precision (Preserved)
        setpts_filter = f"setpts={scale_factor:.10f}*PTS"  # Added precision to avoid floating point errors
        ffmpeg_filters = f"{setpts_filter},scale=in_color_matrix=bt709:out_color_matrix=bt709"

        ffmpeg_filter_args = ["-vf", ffmpeg_filters]

        # Add -frames:v argument to limit the number of output frames (Preserved)
        frames_arg = ["-frames:v", str(total_frames_needed)]

        # Base ffmpeg command construction based on input type
        if input_type == "Video File":
            cmd = ["ffmpeg"] + input_args + ffmpeg_filter_args + frames_arg + [
                "-pix_fmt", "yuv420p",
                "-an"
            ] + codec_params + color_space_args + [
                output_path
            ]
        else:  # Image Sequence
            cmd = [
                "ffmpeg",
                "-framerate", str(framerate)
            ] + input_args + ffmpeg_filter_args + frames_arg + [
                "-pix_fmt", "yuv420p",
                "-an"
            ] + codec_params + color_space_args + [
                output_path
            ]

        print("FFmpeg command:", " ".join(cmd))  # Debug statement

        # Execute the ffmpeg command in a separate thread
        thread = threading.Thread(target=self.execute_ffmpeg, args=(cmd, output_path, actual_duration))
        thread.start()

    def get_codec_params(self, codec):
        """Helper method to get codec parameters based on selected codec."""
        if codec in ["h264", "h265"]:
            bitrate = self.mp4_bitrate.get().strip()
            crf = self.mp4_crf.get().strip()
            if not bitrate or not crf:
                self.queue.put(('error', "Bitrate and CRF settings are required for H.264/H.265 encoding."))
                return None

            try:
                bitrate_float = float(bitrate)
                if bitrate_float <= 0:
                    raise ValueError
            except ValueError:
                self.queue.put(('error', "Bitrate must be a positive number."))
                return None

            codec_lib = "libx264" if codec == "h264" else "libx265"
            codec_params = [
                "-c:v", codec_lib,
                "-preset", "medium",
                "-b:v", f"{bitrate}M",
                "-maxrate", f"{int(float(bitrate)*2)}M",
                "-bufsize", f"{int(float(bitrate)*2)}M",
                "-crf", crf
            ]
            if codec == "h264":
                codec_params.extend(["-profile:v", "high", "-level:v", "5.1"])
            else:  # h265
                codec_params.extend(["-tag:v", "hvc1"])
            return codec_params

        elif codec.startswith("prores"):
            profile = self.prores_profile.get().strip()
            qscale = self.prores_qscale.get().strip()
            if not profile or not qscale:
                self.queue.put(('error', "ProRes profile and Quality settings are required for ProRes encoding."))
                return None

            codec_params = [
                "-c:v", "prores_ks",
                "-profile:v", profile,
                "-qscale:v", qscale
            ]
            return codec_params

        elif codec == "qtrle":
            codec_params = [
                "-c:v", "qtrle",
                "-pix_fmt", "rgb24"  # Use rgb24 for Animation codec
            ]
            return codec_params

        input_args = []
        frames_arg = ["-frames:v", str(total_frames_needed)]
        setpts_filter = ""
        ffmpeg_filters = ""
        ffmpeg_filter_args = []
        scale_factor = 1

        if input_type == "Image Sequence":
            # Check input directory and files
            img_folder = self.img_seq_folder.get()
            if not os.path.exists(img_folder):
                messagebox.showerror("Error", f"Input folder does not exist: {img_folder}")
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

            # Calculate scale factor
            scale_factor = total_frames_needed / (self.total_frames - 1)  # Adjusted for frame counting

        elif input_type == "Video File":
            video_file_path = self.video_file_entry.get()
            if not os.path.exists(video_file_path):
                messagebox.showerror("Error", f"Video file does not exist: {video_file_path}")
                return
            if not os.access(video_file_path, os.R_OK):
                messagebox.showerror("Error", f"Cannot read video file: {video_file_path}")
                return

            input_args = ["-i", video_file_path]

            if hasattr(self, 'video_duration'):
                scale_factor = desired_duration / self.video_duration
            else:
                self.queue.put(('error', "Video duration not detected. Please select the video file again."))
                return
        else:
            # Unsupported input type
            self.queue.put(('error', "Unsupported input type selected."))
            return

        # Use the exact scale factor in the setpts filter with higher precision
        setpts_filter = f"setpts={scale_factor:.10f}*PTS"  # Added precision to avoid floating point errors
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

        # Base ffmpeg command with setpts filter and frame limit
        cmd = [
            "ffmpeg",
            "-framerate", str(framerate)
        ] + input_args + ffmpeg_filter_args + frames_arg + [
            "-pix_fmt", "yuv420p",
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
                                current_frame = int(match.group(1))
                                if hasattr(self, 'total_frames') and self.total_frames > 0:
                                    progress = current_frame / self.total_frames * 100
                                    status = f"Processing frame {current_frame} of {self.total_frames}"
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

    def validate_video_path(self, event=None):
        """Validate the video path when manually entered or pasted"""
        file_path = self.video_file_entry.get().strip()
        
        # Only process if there's actually a path
        if file_path:
            # Small delay to ensure the entry is complete (especially for paste operations)
            self.root.after(100, lambda: self.process_video_path(file_path))

    def process_video_path(self, file_path):
        """Process the video path and update relevant fields"""
        if os.path.isfile(file_path):
            # Check if it's a video file
            _, ext = os.path.splitext(file_path)
            if ext.lower() in ['.mp4', '.mov', '.avi']:
                self.save_last_input_folder(os.path.dirname(file_path))
                self.update_output_folder(os.path.dirname(file_path))
                self.update_video_file_duration(file_path)
            else:
                self.queue.put(('error', "Selected file is not a supported video format."))
        else:
            # Clear duration info if the path is invalid
            self.video_duration = None
            self.video_frame_rate = None
            self.video_total_frames = None
            self.total_frames = None

if __name__ == "__main__":
    root = tk.Tk()
    app = FFmpegUI(root)
    root.mainloop()