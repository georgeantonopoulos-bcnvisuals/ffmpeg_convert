import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import re
import clique
import json
import threading
from tkinter.font import Font

class FFmpegUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FFmpeg GUI")
        self.root.configure(bg='#2b2b2b')
        self.root.geometry("800x700")  # Increased height to accommodate new label
        self.root.minsize(600, 400)    # Set minimum window size

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

        # Load last used input folder
        self.last_input_folder = self.load_last_input_folder()

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
        self.codec_var = tk.StringVar(value="h265")
        self.codec_dropdown = ttk.Combobox(root, textvariable=self.codec_var, values=["h264", "h265", "prores_422", "prores_444"], state="readonly")
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
            elif codec == "prores_444":
                self.prores_profile.set("4")  # 4444
                self.prores_profile_label.config(text="4444")
            # Set default ProRes Qscale
            self.prores_qscale.set("9")
        else:
            self.h264_h265_frame.grid_remove()
            self.prores_frame.grid_remove()

        self.update_duration()  # Update duration when codec changes

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
        img_folder = self.img_seq_folder.get()
        pattern = self.filename_pattern.get()
        codec = self.codec_var.get()
        try:
            framerate = float(self.frame_rate.get())
            desired_duration = float(self.desired_duration.get())
            if framerate <= 0 or desired_duration <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Please enter valid frame rate and desired duration.")
            return

        # Calculate the exact number of frames needed for the desired duration
        total_frames_needed = int(round(desired_duration * framerate))
        
        # Calculate the actual duration based on the rounded number of frames
        actual_duration = total_frames_needed / framerate

        output_file = self.output_filename.get().strip()
        output_dir = self.output_folder.get()

        if not all([img_folder, pattern, framerate, output_file, output_dir]):
            messagebox.showerror("Error", "Please fill in all fields.")
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
            input_pattern = re.sub(r'%0+', '%0', pattern)
            input_path = os.path.join(img_folder, input_pattern)
            input_args = [
                "-start_number", str(start_frame),
                "-i", input_path
            ]
        else:
            messagebox.showerror("Error", "Frame range not detected. Please select the image sequence folder again.")
            return

        output_path = os.path.join(output_dir, output_file)

        # Determine the codec parameters
        codec_params = []
        if codec in ["h264", "h265"]:
            bitrate = self.mp4_bitrate.get()
            crf = self.mp4_crf.get()
            if not bitrate or not crf:
                messagebox.showerror("Error", "Bitrate and CRF settings are required for H.264/H.265 encoding.")
                return
            
            codec_lib = "libx264" if codec == "h264" else "libx265"
            codec_params = [
                "-c:v", codec_lib,
                "-preset", "medium",
                "-crf", crf,
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
                messagebox.showerror("Error", "ProRes profile and Quality settings are required for ProRes encoding.")
                return
            
            codec_params = [
                "-c:v", "prores_ks",
                "-profile:v", profile,
                "-qscale:v", qscale
            ]
        else:
            messagebox.showerror("Error", "Unsupported codec selected.")
            return

        # Calculate scale factor based on the exact number of frames needed
        scale_factor = total_frames_needed / self.total_frames if self.total_frames else 1

        # Use the exact scale factor in the setpts filter
        setpts_filter = f"setpts={scale_factor}*PTS"
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
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            
            total_frames = self.total_frames
            start_frame = self.frame_range[0]
            
            for line in process.stdout:
                self.output_text.insert(tk.END, line)
                self.output_text.see(tk.END)
                self.root.update_idletasks()
                
                if "frame=" in line:
                    match = re.search(r'frame=\s*(\d+)', line)
                    if match:
                        current_frame = int(match.group(1)) + start_frame - 1
                        progress = (current_frame - start_frame + 1) / total_frames * 100
                        self.progress_var.set(progress)
                        self.status_label.config(text=f"Processing frame {current_frame} of {start_frame + total_frames - 1}")
                        self.root.update_idletasks()

            process.wait()
            if process.returncode == 0:
                self.progress_var.set(100)
                self.status_label.config(text="Conversion complete")
                messagebox.showinfo("Success", f"Video created at {output_path}\nActual duration: {actual_duration:.3f} seconds")
            else:
                raise subprocess.CalledProcessError(process.returncode, cmd)
        except subprocess.CalledProcessError as e:
            messagebox.showerror("FFmpeg Error", f"An error occurred while running FFmpeg:\n{e}")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred:\n{str(e)}")
        finally:
            self.progress_var.set(0)
            self.status_label.config(text="")

if __name__ == "__main__":
    root = tk.Tk()
    app = FFmpegUI(root)
    root.mainloop()