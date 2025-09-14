"""
Utility functions for the GUI application.

This module contains common utility functions used throughout the GUI
that don't belong to any specific component.
"""

import os
import platform
import subprocess
from typing import List, Optional
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk


def browse_text_file(parent=None) -> Optional[str]:
    """Open file dialog to select a text file containing URLs."""
    if parent is None:
        # Create a temporary root window if none provided
        temp_root = tk.Tk()
        temp_root.withdraw()  # Hide the root window
        file_path = filedialog.askopenfilename(
            parent=temp_root,
            title="Select URL List File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        temp_root.destroy()
    else:
        file_path = filedialog.askopenfilename(
            parent=parent,
            title="Select URL List File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
    
    return file_path if file_path else None


def browse_directory(parent=None) -> Optional[str]:
    """Open directory selection dialog."""
    if parent is None:
        # Create a temporary root window if none provided
        temp_root = tk.Tk()
        temp_root.withdraw()  # Hide the root window
        dir_path = filedialog.askdirectory(
            parent=temp_root,
            title="Select Download Directory"
        )
        temp_root.destroy()
    else:
        dir_path = filedialog.askdirectory(
            parent=parent,
            title="Select Download Directory"
        )
    
    return dir_path if dir_path else None


def open_folder_cross_platform(path: str) -> bool:
    """
    Open a folder in the system's default file explorer.
    
    Args:
        path: Path to the folder to open
        
    Returns:
        bool: True if successful, False otherwise
    """
    if not os.path.isdir(path):
        return False
    
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", path])
        else:  # Linux and other Unix-like systems
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception as e:
        print(f"Error opening folder {path}: {e}")
        return False


def validate_civitai_url(url: str) -> bool:
    """
    Validate if a URL appears to be a valid Civitai URL.
    
    Args:
        url: URL string to validate
        
    Returns:
        bool: True if URL looks valid, False otherwise
    """
    import urllib.parse
    
    try:
        parsed_url = urllib.parse.urlparse(url)
        return all([parsed_url.scheme, parsed_url.netloc]) and 'civitai.com' in parsed_url.netloc
    except Exception:
        return False


def parse_urls_from_text(text: str) -> List[str]:
    """
    Parse URLs from text input (can be from textbox or file).
    
    Args:
        text: Text containing URLs separated by newlines
        
    Returns:
        List[str]: List of valid URLs
    """
    if not text:
        return []
    
    # Split by newlines and strip whitespace
    urls = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Filter out invalid URLs
    valid_urls = [url for url in urls if validate_civitai_url(url)]
    
    return valid_urls


def format_file_size(bytes_val: int) -> str:
    """
    Format bytes into human readable file size.
    
    Args:
        bytes_val: Size in bytes
        
    Returns:
        str: Human readable file size
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


def format_time_duration(seconds: float) -> str:
    """
    Format seconds into human readable time duration.
    
    Args:
        seconds: Time in seconds
        
    Returns:
        str: Human readable time duration
    """
    if seconds <= 0:
        return "Unknown"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def format_speed(bytes_per_sec: float) -> str:
    """
    Format bytes per second into human readable speed.
    
    Args:
        bytes_per_sec: Speed in bytes per second
        
    Returns:
        str: Human readable speed
    """
    return f"{format_file_size(int(bytes_per_sec))}/s"


def thread_safe_after(widget, func, *args):
    """
    Safely schedule a function to run after a delay on the main thread.
    
    Args:
        widget: Tkinter widget to schedule on
        func: Function to call
        *args: Arguments to pass to function
    """
    if widget:
        widget.after(0, lambda: func(*args))


def thread_safe_after_idle(widget, func, *args):
    """
    Safely schedule a function to run idle on the main thread.
    
    Args:
        widget: Tkinter widget to schedule on
        func: Function to call
        *args: Arguments to pass to function
    """
    if widget:
        widget.after_idle(lambda: func(*args))


class ThreadSafeLogger:
    """Thread-safe logger for GUI messages."""
    
    def __init__(self, log_widget):
        """
        Initialize the logger.
        
        Args:
            log_widget: CTkTextbox widget to log to
        """
        self.log_widget = log_widget
    
    def log_message(self, message: str):
        """
        Log a message to the GUI.
        
        Args:
            message: Message to log
        """
        if self.log_widget:
            self.log_widget.configure(state="normal")
            self.log_widget.insert(ctk.END, message + "\n")
            self.log_widget.see(ctk.END)
            self.log_widget.configure(state="disabled")
    
    def log_error(self, message: str):
        """
        Log an error message to the GUI.
        
        Args:
            message: Error message to log
        """
        self.log_message(f"ERROR: {message}")
    
    def clear_log(self):
        """Clear the log widget."""
        if self.log_widget:
            self.log_widget.configure(state="normal")
            self.log_widget.delete(1.0, ctk.END)
            self.log_widget.configure(state="disabled")


def get_platform_open_command() -> List[str]:
    """
    Get the appropriate open command for the current platform.
    
    Returns:
        List[str]: Command to open files/folders
    """
    if platform.system() == "Windows":
        return ["start"]
    elif platform.system() == "Darwin":  # macOS
        return ["open"]
    else:  # Linux and other Unix-like systems
        return ["xdg-open"]


def validate_path(path: str) -> bool:
    """
    Validate if a path exists and is accessible.
    
    Args:
        path: Path to validate
        
    Returns:
        bool: True if path is valid, False otherwise
    """
    return os.path.exists(path) and os.path.isdir(path) if path else False