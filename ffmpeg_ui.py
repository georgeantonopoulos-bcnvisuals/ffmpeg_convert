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
        self.root.geometry("800x600")  # Set initial window size
        self.root.minsize(600, 400)  # Set minimum window size

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
        for i in range(9):
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
        ttk.Label(root, text="Frame Rate:", font=self.title_font).grid(row=3, column=0, sticky="w", padx=10, pady=5)
        self.frame_rate = ttk.Entry(root)
        self.frame_rate.insert(0, "60")
        self.frame_rate.grid(row=3, column=1, columnspan=2, sticky="ew", padx=10, pady=5)

        # Output File Name
        ttk.Label(root, text="Output Filename:", font=self.title_font).grid(row=4, column=0, sticky="w", padx=10, pady=5)
        self.output_filename = ttk.Entry(root)
        self.output_filename.insert(0, "output.mp4")
        self.output_filename.grid(row=4, column=1, columnspan=2, sticky="ew", padx=10, pady=5)

        # Output Folder Selection
        ttk.Label(root, text="Output Folder:", font=self.title_font).grid(row=5, column=0, sticky="w", padx=10, pady=5)
        self.output_folder = ttk.Entry(root)
        self.output_folder.grid(row=5, column=1, sticky="ew", padx=10, pady=5)
        ttk.Button(root, text="Browse", command=self.browse_output_folder).grid(row=5, column=2, padx=10, pady=5)

        # Run Button
        ttk.Button(root, text="Run FFmpeg", command=self.run_ffmpeg).grid(row=6, column=1, pady=20)

        # Codec-specific options frame
        self.codec_specific_frame = ttk.Frame(root)
        self.codec_specific_frame.grid(row=7, column=0, columnspan=3, sticky="ew", padx=10, pady=5)

        # Progress Bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(root, variable=self.progress_var, maximum=100, mode='determinate')
        self.progress_bar.grid(row=8, column=0, columnspan=3, sticky='ew', padx=10, pady=(20,5))

        # Status Label
        self.status_label = ttk.Label(root, text="", font=self.custom_font)
        self.status_label.grid(row=9, column=0, columnspan=3, padx=10, pady=(5,20))

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
                    
                    # Update output filename without extension and remove trailing dots or underscores
                    output_name = collection.head.rstrip('_.')
                    self.output_filename.delete(0, tk.END)
                    self.output_filename.insert(0, output_name)
                else:
                    messagebox.showwarning("Warning", "No image sequence found in the selected folder.")
            else:
                messagebox.showwarning("Warning", "No image files found in the selected folder.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update filename pattern: {e}")

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
        # Clear existing codec-specific options if any
        for widget in self.codec_specific_frame.winfo_children():
            widget.destroy()
        
        codec = self.codec_var.get()
        if codec == "h264":
            # Add H.264 specific settings here if needed
            pass
        elif codec == "h265":
            # Add H.265 specific settings here if needed
            pass
        elif codec.startswith("prores"):
            # ProRes specific settings
            ttk.Label(self.codec_specific_frame, text="ProRes Profile:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
            self.prores_profile = ttk.Entry(self.codec_specific_frame, width=10)
            self.prores_profile.insert(0, "3" if codec == "prores_422" else "4")
            self.prores_profile.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

            # Add qscale option
            ttk.Label(self.codec_specific_frame, text="Quality (qscale:v):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
            self.prores_qscale = ttk.Entry(self.codec_specific_frame, width=10)
            self.prores_qscale.insert(0, "9")  # Default value
            self.prores_qscale.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)

    def run_ffmpeg(self):
        img_folder = self.img_seq_folder.get()
        pattern = self.filename_pattern.get()
        codec = self.codec_var.get()
        framerate = self.frame_rate.get()
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
        if hasattr(self, 'frame_range'):
            start_frame, end_frame = self.frame_range
            # Ensure the pattern has only one '%0' by replacing '%00' with '%0'
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
        if codec == "h265":
            codec_params = [
                "-c:v", "libx265",
                "-tag:v", "hvc1",
                "-preset", "medium",
                "-crf", "23"
            ]
        elif codec == "h264":
            codec_params = [
                "-c:v", "libx264",
                "-preset", "medium",
                "-profile:v", "high",
                "-level:v", "5.1",
                "-b:v", "30M",
                "-maxrate", "60M",
                "-bufsize", "60M"
            ]
        elif codec.startswith("prores"):
            profile = self.prores_profile.get()
            qscale = self.prores_qscale.get()
            codec_params = [
                "-c:v", "prores_ks",
                "-profile:v", profile,
                "-qscale:v", qscale
            ]
        else:
            messagebox.showerror("Error", "Unsupported codec selected.")
            return

        # Base ffmpeg command
        cmd = [
            "ffmpeg",
            "-framerate", framerate
        ] + input_args + [
            "-pix_fmt", "yuv420p",
            "-an"
        ] + codec_params + [
            output_path
        ]

        print("FFmpeg command:", " ".join(cmd))

        # Execute the ffmpeg command in a separate thread
        thread = threading.Thread(target=self.execute_ffmpeg, args=(cmd, output_path))
        thread.start()

    def execute_ffmpeg(self, cmd, output_path):
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            
            for line in process.stdout:
                if "frame=" in line:
                    match = re.search(r'frame=\s*(\d+)', line)
                    if match:
                        current_frame = int(match.group(1))
                        progress = (current_frame - self.frame_range[0]) / (self.frame_range[1] - self.frame_range[0]) * 100
                        self.progress_var.set(progress)
                        self.status_label.config(text=f"Processing frame {current_frame}")
                        self.root.update_idletasks()

            process.wait()
            if process.returncode == 0:
                self.progress_var.set(100)
                self.status_label.config(text="Conversion complete")
                messagebox.showinfo("Success", f"Video created at {output_path}")
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
