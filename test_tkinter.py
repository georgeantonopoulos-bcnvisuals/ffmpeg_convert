#!/usr/bin/env python
import tkinter as tk
import sys
import os

def main():
    print(f"Python version: {sys.version}")
    print(f"Tkinter version: {tk.TkVersion}")
    print(f"Tkinter imported from: {tk.__file__}")
    
    # Get environment variables related to Tk
    print("\nEnvironment variables:")
    for var in ['TCL_LIBRARY', 'TK_LIBRARY', 'LD_LIBRARY_PATH', 'PYTHONPATH']:
        print(f"{var}={os.environ.get(var, 'Not set')}")
    
    # Creating a simple Tk window
    try:
        print("\nCreating Tkinter window...")
        root = tk.Tk()
        root.title("Tkinter Test")
        
        label = tk.Label(root, text="Tkinter is working!")
        label.pack(padx=20, pady=20)
        
        button = tk.Button(root, text="Click me", command=root.destroy)
        button.pack(padx=20, pady=10)
        
        print("Window created successfully. Will close after 5 seconds.")
        root.after(5000, root.destroy)
        root.mainloop()
        print("Window closed successfully!")
        return 0
    except Exception as e:
        print(f"Error creating Tkinter window: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 