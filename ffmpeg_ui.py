import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import re
import clique  # New import for clique library
import json
import threading

class FFmpegUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FFmpeg GUI")
        self.root.configure(bg='#2b2b2b')

        # Set up dark theme
        self.style = ttk.Style()
        self.style.theme_use("default")  # Start with default to modify
        self.style.configure("TLabel", background="#2b2b2b", foreground="#ffffff")
        self.style.configure("TButton", background="#3c3f41", foreground="#ffffff")
        self.style.configure("TRadiobutton", background="#2b2b2b", foreground="#ffffff")
        self.style.configure("TEntry", fieldbackground="#3c3f41", foreground="#ffffff")
        self.style.map("TButton",
                       background=[('active', '#4a4a4a')],
                       foreground=[('active', '#ffffff')])
        self.style.map("TRadiobutton",
                       background=[('selected', '#2b2b2b')],
                       foreground=[('selected', '#ffffff')])

        # Load last used input folder
        self.last_input_folder = self.load_last_input_folder()

        # Image Sequence Selection
        ttk.Label(root, text="Image Sequence Folder:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.img_seq_folder = ttk.Entry(root, width=50)
        self.img_seq_folder.grid(row=0, column=1, padx=5, pady=5)
        self.img_seq_folder.insert(0, self.last_input_folder)
        ttk.Button(root, text="Browse", command=self.browse_img_seq).grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(root, text="Filename Pattern:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.filename_pattern = ttk.Entry(root, width=50)
        self.filename_pattern.grid(row=1, column=1, padx=5, pady=5, columnspan=2)

        # Codec Selection (changed to dropdown)
        ttk.Label(root, text="Codec:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        self.codec_var = tk.StringVar(value="h265")  # Default selection
        self.codec_dropdown = ttk.Combobox(root, textvariable=self.codec_var, values=["h264", "h265"], state="readonly")
        self.codec_dropdown.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        self.codec_dropdown.bind("<<ComboboxSelected>>", self.update_codec)

        # Frame Rate Selection
        ttk.Label(root, text="Frame Rate:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        self.frame_rate = ttk.Entry(root, width=10)
        self.frame_rate.insert(0, "60")
        self.frame_rate.grid(row=3, column=1, padx=5, pady=5, sticky=tk.W)

        # Output File Name
        ttk.Label(root, text="Output Filename:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=5)
        self.output_filename = ttk.Entry(root, width=50)
        self.output_filename.insert(0, "bau_miebo_delivery_v005.mp4")
        self.output_filename.grid(row=4, column=1, padx=5, pady=5, columnspan=2)

        # Output Folder Selection
        ttk.Label(root, text="Output Folder:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=5)
        self.output_folder = ttk.Entry(root, width=50)
        self.output_folder.grid(row=5, column=1, padx=5, pady=5)
        ttk.Button(root, text="Browse", command=self.browse_output_folder).grid(row=5, column=2, padx=5, pady=5)

        # Run Button
        ttk.Button(root, text="Run FFmpeg", command=self.run_ffmpeg).grid(row=6, column=1, pady=10)

        # Initialize codec-specific parameters (if any)
        self.codec_specific_frame = ttk.Frame(root)
        self.codec_specific_frame.grid(row=7, column=0, columnspan=3, pady=5)
        self.update_codec()

        # Progress Bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(root, variable=self.progress_var, maximum=100, mode='determinate')
        self.progress_bar.grid(row=7, column=0, columnspan=3, sticky='ew', padx=5, pady=5)

        # Status Label
        self.status_label = ttk.Label(root, text="")
        self.status_label.grid(row=8, column=0, columnspan=3, padx=5, pady=5)

    def browse_img_seq(self):
        folder = filedialog.askdirectory(initialdir=self.last_input_folder)
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
                    
                    # Update output filename
                    output_name = f"{collection.head.rstrip('_')}.mp4"
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

    def run_ffmpeg(self):
        img_folder = self.img_seq_folder.get()
        pattern = self.filename_pattern.get()
        codec = self.codec_var.get()
        framerate = self.frame_rate.get()
        output_file = self.output_filename.get()
        output_dir = self.output_folder.get()

        if not all([img_folder, pattern, framerate, output_file, output_dir]):
            messagebox.showerror("Error", "Please fill in all fields.")
            return

        # Use the frame range information
        if hasattr(self, 'frame_range'):
            start_frame, end_frame = self.frame_range
            input_pattern = pattern.replace('%0', '%')  # Remove leading zeros from pattern
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
                "-crf", "23"
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
