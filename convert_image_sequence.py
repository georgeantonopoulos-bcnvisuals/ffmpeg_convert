import tkinter as tk
from tkinter import filedialog, ttk
import os
import re
import subprocess

def select_input_directory():
    input_dir = filedialog.askdirectory()
    input_entry.delete(0, tk.END)
    input_entry.insert(0, input_dir)
    update_filename_pattern(input_dir)

def select_output_directory():
    output_dir = filedialog.askdirectory()
    output_entry.delete(0, tk.END)
    output_entry.insert(0, output_dir)

def update_filename_pattern(input_dir):
    files = os.listdir(input_dir)
    image_files = [f for f in files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp'))]
    if image_files:
        first_file = image_files[0]
        pattern = re.sub(r'\d+', '%04d', first_file)
        filename_pattern_entry.delete(0, tk.END)
        filename_pattern_entry.insert(0, pattern)

def convert_sequence():
    input_dir = input_entry.get()
    output_dir = output_entry.get()
    filename_pattern = filename_pattern_entry.get()
    fps = fps_entry.get()
    
    input_path = os.path.join(input_dir, filename_pattern)
    output_path = os.path.join(output_dir, "output.mp4")
    
    ffmpeg_command = [
        "ffmpeg",
        "-framerate", fps,
        "-i", input_path,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    
    try:
        subprocess.run(ffmpeg_command, check=True)
        result_label.config(text="Conversion completed successfully!")
    except subprocess.CalledProcessError as e:
        result_label.config(text=f"Error during conversion: {e}")

# Set up the main window
root = tk.Tk()
root.title("Image Sequence to Video Converter")
root.configure(bg='#2b2b2b')

style = ttk.Style()
style.theme_create("darktheme", parent="alt", settings={
    "TLabel": {"configure": {"background": "#2b2b2b", "foreground": "#ffffff"}},
    "TButton": {"configure": {"background": "#3c3f41", "foreground": "#ffffff"}},
    "TEntry": {"configure": {"background": "#3c3f41", "foreground": "#ffffff", "insertcolor": "#ffffff"}},
})
style.theme_use("darktheme")

# Input directory
tk.Label(root, text="Input Directory:", bg='#2b2b2b', fg='#ffffff').grid(row=0, column=0, sticky="w", padx=5, pady=5)
input_entry = tk.Entry(root, width=50, bg='#3c3f41', fg='#ffffff', insertbackground='#ffffff')
input_entry.grid(row=0, column=1, padx=5, pady=5)
tk.Button(root, text="Browse", command=select_input_directory, bg='#3c3f41', fg='#ffffff').grid(row=0, column=2, padx=5, pady=5)

# Output directory
tk.Label(root, text="Output Directory:", bg='#2b2b2b', fg='#ffffff').grid(row=1, column=0, sticky="w", padx=5, pady=5)
output_entry = tk.Entry(root, width=50, bg='#3c3f41', fg='#ffffff', insertbackground='#ffffff')
output_entry.grid(row=1, column=1, padx=5, pady=5)
tk.Button(root, text="Browse", command=select_output_directory, bg='#3c3f41', fg='#ffffff').grid(row=1, column=2, padx=5, pady=5)

# Filename pattern
tk.Label(root, text="Filename Pattern:", bg='#2b2b2b', fg='#ffffff').grid(row=2, column=0, sticky="w", padx=5, pady=5)
filename_pattern_entry = tk.Entry(root, width=50, bg='#3c3f41', fg='#ffffff', insertbackground='#ffffff')
filename_pattern_entry.grid(row=2, column=1, padx=5, pady=5)

# FPS
tk.Label(root, text="FPS:", bg='#2b2b2b', fg='#ffffff').grid(row=3, column=0, sticky="w", padx=5, pady=5)
fps_entry = tk.Entry(root, width=10, bg='#3c3f41', fg='#ffffff', insertbackground='#ffffff')
fps_entry.grid(row=3, column=1, sticky="w", padx=5, pady=5)
fps_entry.insert(0, "24")

# Convert button
convert_button = tk.Button(root, text="Convert", command=convert_sequence, bg='#3c3f41', fg='#ffffff')
convert_button.grid(row=4, column=1, pady=10)

# Result label
result_label = tk.Label(root, text="", bg='#2b2b2b', fg='#ffffff')
result_label.grid(row=5, column=0, columnspan=3, pady=5)

root.mainloop()
