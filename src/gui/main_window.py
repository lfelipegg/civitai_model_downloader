"""
Main window class for the Civitai Model Downloader GUI.

This module contains the primary application window and its initialization.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
from dotenv import load_dotenv
import threading
import platform
import subprocess
import time
import urllib.parse # Added for URL validation
import queue # For thread-safe progress updates
import uuid
import re

# Import utilities module
from src.gui.utils import (
    browse_text_file, 
    browse_directory, 
    open_folder_cross_platform,
    validate_civitai_url,
    parse_urls_from_text,
    format_file_size,
    format_time_duration,
    format_speed,
    thread_safe_after,
    thread_safe_after_idle,
    ThreadSafeLogger,
    validate_path
)

# Assuming civitai_downloader functions are available
from src.civitai_downloader import (
    get_model_info_from_url,
    download_civitai_model,
    download_file,
    is_model_downloaded,
    get_model_with_versions
)
from src.history_manager import HistoryManager
from src.progress_tracker import progress_manager, ProgressPhase, ProgressStats
from src.thumbnail_manager import thumbnail_manager
from src.enhanced_progress_bar import EnhancedProgressWidget, ThumbnailWidget


class App(ctk.CTk):
    """Main application window class."""
    
    def __init__(self):
        super().__init__()

        self.title("Civitai Model Downloader")
        self.geometry("900x900")

        self._download_queue_list = [] # Replaced queue.Queue with a list
        self._queue_lock = threading.Lock() # Lock for thread-safe access to the queue list
        self._queue_condition = threading.Condition(self._queue_lock) # Condition for signaling queue changes
        self.download_tasks = {} # To hold references to download frames and progress bars
        self.background_threads = {} # To track background threads for completion detection
        self.queue_row_counter = 0 # To manage grid placement in the queue_frame
        self.stop_event = threading.Event() # Event to signal threads to stop
        
        # Progress update queue for thread-safe UI updates
        self.progress_queue = queue.Queue()
        self._start_progress_processor()

        # Initialize history manager
        self.history_manager = HistoryManager()

        self.protocol("WM_DELETE_WINDOW", self._on_closing) # Handle window close event

        # Create main notebook for tabs
        self.notebook = ctk.CTkTabview(self)
        self.notebook.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        # Configure grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Create tabs
        self.download_tab = self.notebook.add("Downloads")
        self.history_tab = self.notebook.add("History")
        
        # Setup download tab
        self._setup_download_tab()
        
        # Setup history tab
        self._setup_history_tab()
    
    def _start_progress_processor(self):
        """Start the progress processor to handle UI updates efficiently"""
        def process_progress_updates():
            try:
                while not self.stop_event.is_set():
                    try:
                        # Get progress update from queue with timeout
                        update_data = self.progress_queue.get(timeout=0.1)
                        if update_data is None:  # Poison pill to stop
                            break
                        
                        # Process the update on main thread
                        self.after_idle(lambda data=update_data: self._apply_progress_update(data))
                        self.progress_queue.task_done()
                    except queue.Empty:
                        continue
            except Exception as e:
                print(f"Progress processor error: {e}")
        
        # Start progress processor thread
        self.progress_thread = threading.Thread(target=process_progress_updates, daemon=True)
        self.progress_thread.start()
    
    def _apply_progress_update(self, update_data):
        """Apply progress update to UI (called on main thread)"""
        try:
            update_type = update_data.get('type')
            task_id = update_data.get('task_id')
            
            if update_type == 'progress' and task_id in self.download_tasks:
                task = self.download_tasks[task_id]
                bytes_downloaded = update_data.get('bytes_downloaded', 0)
                total_size = update_data.get('total_size', 0)
                speed = update_data.get('speed', 0)
                
                if task['pause_event'].is_set():  # Don't update progress if paused
                    return
                
                # Update enhanced progress tracker
                if 'tracker' in task:
                    tracker = task['tracker']
                    tracker.set_phase(ProgressPhase.DOWNLOADING)
                    stats = tracker.update_progress(bytes_downloaded, total_size)
                    
                    # Update enhanced progress widget
                    if 'enhanced_progress' in task:
                        task['enhanced_progress'].update_from_tracker(stats)
                else:
                    # Fallback for backward compatibility
                    if total_size > 0:
                        progress_percent = (bytes_downloaded / total_size) * 100
                        task['progress_bar'].set(progress_percent / 100)
                    else:
                        task['progress_bar'].set(0)
                
                # Update main speed/remaining labels with enhanced formatting
                if 'tracker' in task:
                    formatted_stats = task['tracker'].get_formatted_stats()
                    self.speed_label.configure(text=f"Speed: {formatted_stats.get('current_speed', '0 B/s')}")
                    self.remaining_label.configure(text=f"ETA: {formatted_stats.get('eta', 'Unknown')}")
                else:
                    # Fallback formatting
                    self.speed_label.configure(text=f"Speed: {speed / 1024:.2f} KB/s")
                    if speed > 0 and total_size > 0:
                        remaining_bytes = total_size - bytes_downloaded
                        remaining_time_sec = remaining_bytes / speed
                        mins, secs = divmod(remaining_time_sec, 60)
                        self.remaining_label.configure(text=f"Remaining: {int(mins)}m {int(secs)}s")
                    else:
                        self.remaining_label.configure(text="Remaining: Calculating...")
                    
        except Exception as e:
            print(f"Error applying progress update: {e}")

    def _setup_download_tab(self):
        # Configure grid layout for download tab
        self.download_tab.grid_columnconfigure(1, weight=1)
        self.download_tab.grid_rowconfigure(4, weight=1)

        # Input Frame
        self.input_frame = ctk.CTkFrame(self.download_tab)
        self.input_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.input_frame.grid_columnconfigure(1, weight=1)

        # URL Input
        self.url_label = ctk.CTkLabel(self.input_frame, text="Civitai URL:")
        self.url_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.url_entry = ctk.CTkTextbox(self.input_frame, height=100, width=400) # Increased height for multiple URLs
        self.url_entry.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.browse_button = ctk.CTkButton(self.input_frame, text="Browse .txt", command=self.browse_txt_file)
        self.browse_button.grid(row=0, column=2, padx=10, pady=10, sticky="e")

        # API Key Input
        # Move API key and download path labels down due to increased URL entry height
        self.api_key_label = ctk.CTkLabel(self.input_frame, text="Civitai API Key:")
        self.api_key_label.grid(row=1, column=0, padx=10, pady=(10, 5), sticky="w")
        self.api_key_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Enter your Civitai API Key (optional)", show="*")
        self.api_key_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

        # Download Path Input
        self.download_path_label = ctk.CTkLabel(self.input_frame, text="Download Path:")
        self.download_path_label.grid(row=2, column=0, padx=10, pady=(5, 10), sticky="w")
        self.download_path_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Select download directory")
        self.download_path_entry.grid(row=2, column=1, padx=10, pady=10, sticky="ew")
        self.browse_path_button = ctk.CTkButton(self.input_frame, text="Browse Dir", command=self.browse_download_path)
        self.browse_path_button.grid(row=2, column=2, padx=10, pady=10, sticky="e")

        # Download scope selection
        self.download_scope_var = tk.StringVar(value="Current version only")
        scope_frame = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        scope_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="ew")
        scope_frame.grid_columnconfigure(1, weight=1)

        scope_label = ctk.CTkLabel(scope_frame, text="Download scope:")
        scope_label.grid(row=0, column=0, padx=(0, 6), sticky="w")

        self.download_scope_option = ctk.CTkOptionMenu(
            scope_frame,
            variable=self.download_scope_var,
            values=["Current version only", "All versions"]
        )
        self.download_scope_option.grid(row=0, column=1, sticky="w")

        scope_hint = ctk.CTkLabel(
            scope_frame,
            text="Choose whether to download just the referenced version or every version of each model.",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        scope_hint.grid(row=1, column=0, columnspan=2, pady=(4, 0), sticky="w")

        # Load environment variables
        load_dotenv()
        self.api_key_entry.insert(0, os.getenv("CIVITAI_API_KEY", ""))
        self.download_path_entry.insert(0, os.getenv("DOWNLOAD_PATH", os.getcwd()))

        # Download Button
        self.download_button = ctk.CTkButton(self.download_tab, text="Start Download", command=self.start_download_thread)
        self.download_button.grid(row=1, column=0, padx=(10, 5), pady=10, sticky="ew")

        # Open Download Folder Button
        self.open_folder_button = ctk.CTkButton(self.download_tab, text="Open Downloads Folder", command=self.open_download_folder)
        self.open_folder_button.grid(row=1, column=1, padx=(5, 10), pady=10, sticky="ew")

        # Clear/Reset Button
        self.clear_button = ctk.CTkButton(self.download_tab, text="Clear/Reset GUI", command=self.clear_gui)
        self.clear_button.grid(row=8, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        # Download Stats Labels
        self.progress_label = ctk.CTkLabel(self.download_tab, text="Progress: N/A")
        self.progress_label.grid(row=2, column=0, columnspan=2, padx=10, pady=(10, 0), sticky="w")
        self.speed_label = ctk.CTkLabel(self.download_tab, text="Speed: N/A")
        self.speed_label.grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 0), sticky="w")
        self.remaining_label = ctk.CTkLabel(self.download_tab, text="Remaining: N/A")
        self.remaining_label.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")


        # Download Queue Display
        self.queue_frame = ctk.CTkScrollableFrame(self.download_tab, label_text="Download Queue")
        self.queue_frame.grid(row=5, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.queue_frame.grid_columnconfigure(0, weight=1)

        # Log Area
        self.log_label = ctk.CTkLabel(self.download_tab, text="Logs:")
        self.log_label.grid(row=6, column=0, padx=10, pady=(10, 0), sticky="w")
        self.log_text = ctk.CTkTextbox(self.download_tab, width=600, height=200)
        self.log_text.grid(row=7, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.log_text.configure(state="disabled") # Make it read-only

        # Configure grid layout to expand queue and log area
        self.download_tab.grid_rowconfigure(5, weight=2) # Queue frame
        self.download_tab.grid_rowconfigure(7, weight=1) # Log area
    
    def _setup_history_tab(self):
        """Setup the download history tab."""
        # Configure grid layout for history tab
        self.history_tab.grid_columnconfigure(0, weight=1)
        self.history_tab.grid_rowconfigure(3, weight=1)  # Updated for new filter frame
        
        # Search frame
        self.search_frame = ctk.CTkFrame(self.history_tab)
        self.search_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.search_frame.grid_columnconfigure(1, weight=1)
        
        self.search_label = ctk.CTkLabel(self.search_frame, text="Search:")
        self.search_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.search_entry = ctk.CTkEntry(self.search_frame, placeholder_text="Search by name, type, or trigger words...")
        self.search_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.search_entry.bind("<KeyRelease>", self._on_search_changed)
        
        self.search_button = ctk.CTkButton(self.search_frame, text="Search", command=self.search_history)
        self.search_button.grid(row=0, column=2, padx=10, pady=10)
        
        self.refresh_button = ctk.CTkButton(self.search_frame, text="Refresh", command=self.refresh_history)
        self.refresh_button.grid(row=0, column=3, padx=5, pady=10)
        
        # Advanced filters frame
        self.filters_frame = ctk.CTkFrame(self.history_tab)
        self.filters_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        self.filters_frame.grid_columnconfigure(0, weight=1)
        self.filters_frame.grid_columnconfigure(1, weight=1)
        self.filters_frame.grid_columnconfigure(2, weight=1)
        self.filters_frame.grid_columnconfigure(3, weight=1)
        
        # Initialize filter state
        self.current_filters = {}
        self.current_sort_by = "download_date"
        self.current_sort_order = "desc"
        
        self._setup_filter_controls()
        
        # Control buttons frame
        self.history_controls_frame = ctk.CTkFrame(self.history_tab)
        self.history_controls_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        
        self.scan_button = ctk.CTkButton(self.history_controls_frame, text="Scan Downloads", command=self.scan_downloads)
        self.scan_button.grid(row=0, column=0, padx=5, pady=5)
        
        self.export_button = ctk.CTkButton(self.history_controls_frame, text="Export History", command=self.export_history)
        self.export_button.grid(row=0, column=1, padx=5, pady=5)
        
        self.import_button = ctk.CTkButton(self.history_controls_frame, text="Import History", command=self.import_history)
        self.import_button.grid(row=0, column=2, padx=5, pady=5)
        
        # Statistics label
        self.stats_label = ctk.CTkLabel(self.history_controls_frame, text="")
        self.stats_label.grid(row=0, column=3, padx=20, pady=5, sticky="e")
        
        # Active filters display frame
        self.active_filters_frame = ctk.CTkFrame(self.history_controls_frame)
        self.active_filters_frame.grid(row=1, column=0, columnspan=4, padx=5, pady=5, sticky="ew")
        
        # History display
        self.history_frame = ctk.CTkScrollableFrame(self.history_tab, label_text="Download History")
        self.history_frame.grid(row=3, column=0, padx=10, pady=10, sticky="nsew")
        self.history_frame.grid_columnconfigure(0, weight=1)
        
        # Load initial history
        self.refresh_history()
    
    def _setup_filter_controls(self):
        """Setup advanced filter controls."""
        
        # Row 1: Model type and base model filters
        self.model_type_label = ctk.CTkLabel(self.filters_frame, text="Model Type:")
        self.model_type_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        
        self.model_type_var = tk.StringVar(value="All")
        self.model_type_menu = ctk.CTkOptionMenu(
            self.filters_frame,
            values=["All"],
            variable=self.model_type_var,
            command=self._on_filter_changed
        )
        self.model_type_menu.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        self.base_model_label = ctk.CTkLabel(self.filters_frame, text="Base Model:")
        self.base_model_label.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        
        self.base_model_var = tk.StringVar(value="All")
        self.base_model_menu = ctk.CTkOptionMenu(
            self.filters_frame,
            values=["All"],
            variable=self.base_model_var,
            command=self._on_filter_changed
        )
        self.base_model_menu.grid(row=0, column=3, padx=5, pady=5, sticky="ew")
        
        # Row 2: Date range filters
        self.date_from_label = ctk.CTkLabel(self.filters_frame, text="From Date:")
        self.date_from_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        
        self.date_from_entry = ctk.CTkEntry(self.filters_frame, placeholder_text="YYYY-MM-DD")
        self.date_from_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.date_from_entry.bind("<KeyRelease>", self._on_filter_changed)
        
        self.date_to_label = ctk.CTkLabel(self.filters_frame, text="To Date:")
        self.date_to_label.grid(row=1, column=2, padx=5, pady=5, sticky="w")
        
        self.date_to_entry = ctk.CTkEntry(self.filters_frame, placeholder_text="YYYY-MM-DD")
        self.date_to_entry.grid(row=1, column=3, padx=5, pady=5, sticky="ew")
        self.date_to_entry.bind("<KeyRelease>", self._on_filter_changed)
        
        # Row 3: File size range and sorting
        self.size_label = ctk.CTkLabel(self.filters_frame, text="Size (MB):")
        self.size_label.grid(row=2, column=0, padx=5, pady=5, sticky="w")
        
        self.size_frame = ctk.CTkFrame(self.filters_frame, fg_color="transparent")
        self.size_frame.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        self.size_frame.grid_columnconfigure(2, weight=1)
        
        self.size_min_entry = ctk.CTkEntry(self.size_frame, placeholder_text="Min", width=60)
        self.size_min_entry.grid(row=0, column=0, padx=2)
        self.size_min_entry.bind("<KeyRelease>", self._on_filter_changed)
        
        self.size_sep_label = ctk.CTkLabel(self.size_frame, text="-")
        self.size_sep_label.grid(row=0, column=1, padx=2)
        
        self.size_max_entry = ctk.CTkEntry(self.size_frame, placeholder_text="Max", width=60)
        self.size_max_entry.grid(row=0, column=2, padx=2, sticky="w")
        self.size_max_entry.bind("<KeyRelease>", self._on_filter_changed)
        
        self.sort_label = ctk.CTkLabel(self.filters_frame, text="Sort by:")
        self.sort_label.grid(row=2, column=2, padx=5, pady=5, sticky="w")
        
        self.sort_var = tk.StringVar(value="Date ↓")
        self.sort_menu = ctk.CTkOptionMenu(
            self.filters_frame,
            values=["Date ↓", "Date ↑", "Name ↓", "Name ↑", "Size ↓", "Size ↑", "Type ↓", "Type ↑"],
            variable=self.sort_var,
            command=self._on_sort_changed
        )
        self.sort_menu.grid(row=2, column=3, padx=5, pady=5, sticky="ew")
        
        # Row 4: Additional filters and clear button
        self.triggers_var = tk.BooleanVar()
        self.triggers_checkbox = ctk.CTkCheckBox(
            self.filters_frame,
            text="Has trigger words",
            variable=self.triggers_var,
            command=self._on_filter_changed
        )
        self.triggers_checkbox.grid(row=3, column=0, padx=5, pady=5, sticky="w")
        
        self.clear_filters_button = ctk.CTkButton(
            self.filters_frame,
            text="Clear All Filters",
            command=self.clear_filters,
            fg_color="red",
            hover_color="darkred",
            width=120
        )
        self.clear_filters_button.grid(row=3, column=3, padx=5, pady=5, sticky="e")
        
        # Update filter options
        self._update_filter_options()

    def browse_txt_file(self):
        file_path = browse_text_file(self)
        if file_path:
            with open(file_path, 'r') as f:
                content = f.read()
            self.url_entry.delete("1.0", ctk.END) # Clear existing content
            self.url_entry.insert("1.0", content) # Insert new content

    def browse_download_path(self):
        dir_path = browse_directory(self)
        if dir_path:
            self.download_path_entry.delete(0, ctk.END)
            self.download_path_entry.insert(0, dir_path)

    def log_message(self, message):
        # Initialize logger if not already done
        if not hasattr(self, 'logger'):
            self.logger = ThreadSafeLogger(self.log_text)
        self.logger.log_message(message)

    def start_download_thread(self):
        # Get content from CTkTextbox
        url_input_content = self.url_entry.get("1.0", ctk.END).strip()
        api_key = self.api_key_entry.get()
        download_path = self.download_path_entry.get()

        if not url_input_content:
            messagebox.showerror("Input Error", "Please enter Civitai URLs or select a .txt file.")
            return
        if not download_path:
            messagebox.showerror("Input Error", "Please select a download directory.")
            return

        self.log_text.configure(state="normal")
        self.log_text.delete(1.0, ctk.END) # Clear previous logs
        self.log_text.configure(state="disabled")

        self.log_message("Starting download process...")
        self.download_button.configure(state="disabled", text="Downloading...")

        # Start download in a separate thread to keep GUI responsive
        # Create a new thread for adding URLs to the queue and then waiting for them to complete
        self.processing_and_completion_thread = threading.Thread(target=self._initiate_download_process, args=(url_input_content, api_key, download_path), daemon=True)
        self.processing_and_completion_thread.start()

    def _initiate_download_process(self, url_input_content, api_key, download_path):
        # Add URLs to the queue
        self._add_urls_to_queue(url_input_content, api_key, download_path)

        # Start queue processing in a separate thread if not already running
        if not hasattr(self, 'queue_processor_thread') or not self.queue_processor_thread.is_alive():
            self.queue_processor_thread = threading.Thread(target=self._process_download_queue, daemon=True)
            self.queue_processor_thread.start()
        
        # This thread will wait for all tasks to be done and then re-enable the button
        # It should not be daemonized if we want to join it gracefully
        self.completion_watcher_thread = threading.Thread(target=self._watch_completion, args=(self.processing_and_completion_thread,), daemon=True)
        self.completion_watcher_thread.start()

        # The _initiate_download_process now just adds URLs and starts the queue processor.
        # The completion logic is moved to _watch_completion.
        # Removed premature completion messages from here.

    def _update_progress(self, bytes_downloaded, total_size, speed):
        if total_size > 0:
            progress_percent = (bytes_downloaded / total_size) * 100
            self.progress_label.configure(text=f"Progress: {format_file_size(bytes_downloaded)} / {format_file_size(total_size)} ({progress_percent:.2f}%)")
            self.speed_label.configure(text=f"Speed: {format_speed(speed)}")
            
            if speed > 0:
                remaining_bytes = total_size - bytes_downloaded
                remaining_time_sec = remaining_bytes / speed
                self.remaining_label.configure(text=f"Remaining: {format_time_duration(remaining_time_sec)}")
            else:
                self.remaining_label.configure(text="Remaining: Calculating...")
        else:
            self.progress_label.configure(text="Progress: Unknown size")
            self.speed_label.configure(text="Speed: N/A")
            self.remaining_label.configure(text="Remaining: N/A")

    def open_download_folder(self):
        download_path = self.download_path_entry.get()
        if not download_path or not validate_path(download_path):
            messagebox.showerror("Error", "Download path is not valid or not set.")
            return

        if not open_folder_cross_platform(download_path):
            messagebox.showerror("Error", "Could not open folder.")

    def _add_urls_to_queue(self, url_input_content, api_key, download_path):
        try:
            urls = parse_urls_from_text(url_input_content)
            if not urls:
                self.log_message("No URLs provided. Exiting.")
                messagebox.showinfo("Download Info", "No URLs provided.")
                self.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
                return

            download_all_versions = self.download_scope_var.get() == "All versions"

            for url in urls:
                if download_all_versions:
                    handled = self._queue_all_versions_for_url(url, api_key, download_path)
                    if handled:
                        continue
                    self.log_message(f"Falling back to referenced version for {url}.")
                self._queue_single_url(url, api_key, download_path)
        except Exception as e:
            self.log_message(f"An unexpected error occurred while adding URLs to queue: {e}")
            messagebox.showerror("Unexpected Error", f"An unexpected error occurred while adding URLs to queue: {e}")
        finally:
            self.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))

    def _queue_single_url(self, url, api_key, download_path):
        """Queue a single model version download."""
        if not validate_civitai_url(url):
            self.log_message(f"Skipping invalid URL: {url}")
            task_id = self._enqueue_url_task(
                url,
                api_key,
                download_path,
                display_label=f"Invalid URL: {url}",
                enqueue=False,
                initial_state='failed'
            )
            self.after(50, lambda tid=task_id: self._safe_update_status(
                tid,
                "Status: Failed - Invalid URL format",
                "red"
            ))
            return

        self._enqueue_url_task(url, api_key, download_path)

    def _queue_all_versions_for_url(self, url, api_key, download_path):
        """Expand a model URL into separate tasks for every available version."""
        model_id = self._extract_model_id(url)

        if not model_id:
            version_info, error = get_model_info_from_url(url, api_key)
            if error or not version_info:
                self.log_message(f"Unable to resolve model ID for {url}: {error or 'unknown error'}")
                return False
            model_id = str(
                version_info.get('modelId')
                or version_info.get('model', {}).get('id')
                or ""
            )
            if not model_id:
                self.log_message(f"Could not determine model ID from metadata for {url}.")
                return False

        model_data, error = get_model_with_versions(model_id, api_key)
        if error or not model_data:
            self.log_message(f"Failed to retrieve model metadata for {model_id}: {error or 'unknown error'}")
            return False

        versions = model_data.get('modelVersions') or []
        if not versions:
            self.log_message(f"No versions available for model {model_id}.")
            return False

        base_name = model_data.get('name') or f"Model {model_id}"
        queued = 0
        seen_versions = set()

        for version in versions:
            version_id = version.get('id')
            if not version_id:
                continue
            version_id = str(version_id)
            if version_id in seen_versions:
                continue
            seen_versions.add(version_id)

            version_url = self._build_version_url(url, model_id, version_id)
            version_name = version.get('name', f"Version {version_id}")
            display_label = f"{base_name} - {version_name}"

            self._enqueue_url_task(
                version_url,
                api_key,
                download_path,
                display_label=display_label
            )
            queued += 1

        if queued:
            self.log_message(f"Queued {queued} versions for {base_name}.")
            return True

        self.log_message(f"No versions queued for model {model_id}.")
        return False

    def _enqueue_url_task(self, url, api_key, download_path, display_label=None, enqueue=True, initial_state='queued'):
        """Create or update a task entry and optionally enqueue it for processing."""
        task_id = f"task_{uuid.uuid4().hex}"
        existing = self.download_tasks.get(task_id, {})

        task_entry = {
            'url': url,
            'display_url': display_label or url,
            'stop_event': existing.get('stop_event', threading.Event()),
            'pause_event': existing.get('pause_event', threading.Event()),
            'frame': existing.get('frame'),
            'progress_bar': existing.get('progress_bar'),
            'enhanced_progress': existing.get('enhanced_progress'),
            'tracker': existing.get('tracker'),
            'status_label': existing.get('status_label'),
            'cancel_button': existing.get('cancel_button'),
            'pause_button': existing.get('pause_button'),
            'resume_button': existing.get('resume_button'),
            'pause_resume_button': existing.get('pause_resume_button'),
            'context_button': existing.get('context_button'),
            'status_indicator': existing.get('status_indicator'),
            'status_state': initial_state,
        }
        self.download_tasks[task_id] = task_entry

        if enqueue:
            with self._queue_lock:
                self._download_queue_list.append({
                    'task_id': task_id,
                    'url': url,
                    'api_key': api_key,
                    'download_path': download_path
                })
                self._queue_condition.notify()

        self.after(0, self._add_download_task_ui, task_id, url)
        return task_id

    def _extract_model_id(self, url):
        """Extract the model ID from a Civitai URL."""
        match = re.search(r'/models/(\d+)', url)
        return match.group(1) if match else None

    def _build_version_url(self, original_url, model_id, version_id):
        """Build a URL that points explicitly to a model version."""
        parsed = urllib.parse.urlparse(original_url)
        if parsed.scheme and parsed.netloc:
            base = f"{parsed.scheme}://{parsed.netloc}"
        else:
            base = "https://civitai.com"
        return f"{base}/models/{model_id}?modelVersionId={version_id}"

    def _add_download_task_ui(self, task_id, url):
        row = self.queue_row_counter
        self.queue_row_counter += 1
        task_frame = ctk.CTkFrame(self.queue_frame)
        task_frame.grid(row=row, column=0, padx=5, pady=5, sticky="ew")
        task_frame.grid_columnconfigure(1, weight=1)
        
        # URL display
        existing = self.download_tasks.get(task_id, {})
        display_text = existing.get('display_url', existing.get('url', url))
        url_display = (display_text[:50] + '...') if len(display_text) > 53 else display_text
        task_label = ctk.CTkLabel(task_frame, text=f"Task: {url_display}", anchor="w")
        task_label.grid(row=0, column=0, padx=5, pady=2, sticky="w")
        
        # Enhanced progress widget
        enhanced_progress = EnhancedProgressWidget(task_frame, task_id)
        enhanced_progress.grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky="ew")
        
        # Create progress tracker
        tracker = progress_manager.create_tracker(task_id)
        tracker.set_phase(ProgressPhase.INITIALIZING)
        # Store references to update later. If a placeholder already exists (pre-registered
        # in _add_urls_to_queue), update it instead of overwriting to avoid races.
        self.download_tasks[task_id] = {
            'frame': task_frame,
            'label': task_label,
            'progress_bar': enhanced_progress.progress_bar,  # For backward compatibility
            'enhanced_progress': enhanced_progress,
            'tracker': tracker,
            'status_label': existing.get('status_label'),  # Might not exist; keep None
            'display_url': display_text,
            'url': existing.get('url', url), # Preserve original URL if set
            'stop_event': existing.get('stop_event', threading.Event()), # Per-task stop event
            'pause_event': existing.get('pause_event', threading.Event()), # Per-task pause event
            'cancel_button': existing.get('cancel_button'),
            'pause_button': existing.get('pause_button'),
            'resume_button': existing.get('resume_button'),
            'pause_resume_button': existing.get('pause_resume_button'),
            'context_button': existing.get('context_button'),
            'status_indicator': existing.get('status_indicator'),
            'status_state': existing.get('status_state', 'queued')
        }
        # Control Buttons Frame
        button_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
        button_frame.grid(row=0, column=2, padx=5, pady=2, sticky="e")
        button_frame.grid_columnconfigure(0, weight=1) # For pause
        button_frame.grid_columnconfigure(1, weight=1) # For resume
        button_frame.grid_columnconfigure(2, weight=1) # For cancel
        button_frame.grid_columnconfigure(3, weight=1) # For up
        button_frame.grid_columnconfigure(4, weight=1) # For down
        # Add Pause Button
        pause_button = ctk.CTkButton(button_frame, text="Pause", command=lambda tid=task_id: self.pause_download(tid))
        pause_button.grid(row=0, column=0, padx=2, pady=0, sticky="ew")
        self.download_tasks[task_id]['pause_button'] = pause_button
        # Add Resume Button (initially disabled)
        resume_button = ctk.CTkButton(button_frame, text="Resume", command=lambda tid=task_id: self.resume_download(tid), state="disabled")
        resume_button.grid(row=0, column=1, padx=2, pady=0, sticky="ew")
        self.download_tasks[task_id]['resume_button'] = resume_button
        
        # Add Cancel Button
        cancel_button = ctk.CTkButton(button_frame, text="Cancel", command=lambda tid=task_id: self.cancel_download(tid))
        cancel_button.grid(row=0, column=2, padx=2, pady=0, sticky="ew")
        self.download_tasks[task_id]['cancel_button'] = cancel_button
        # Add Move Up Button
        move_up_button = ctk.CTkButton(button_frame, text="▲", command=lambda tid=task_id: self.move_task_up(tid), width=30)
        move_up_button.grid(row=0, column=3, padx=2, pady=0, sticky="ew")
        self.download_tasks[task_id]['move_up_button'] = move_up_button
        # Add Move Down Button
        move_down_button = ctk.CTkButton(button_frame, text="▼", command=lambda tid=task_id: self.move_task_down(tid), width=30)
        move_down_button.grid(row=0, column=4, padx=2, pady=0, sticky="ew")
        self.download_tasks[task_id]['move_down_button'] = move_down_button
    
    def cancel_download(self, task_id):
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
            task['stop_event'].set()

            # Update enhanced progress tracker
            if 'tracker' in task:
                task['tracker'].cancel()
                stats = task['tracker']._get_stats_copy()
                if 'enhanced_progress' in task:
                    task['enhanced_progress'].update_from_tracker(stats)

            # Clean up background thread if it exists
            if task_id in self.background_threads:
                del self.background_threads[task_id]

            if task['cancel_button']:
                task['cancel_button'].configure(state="disabled", text="Cancelled")
            if task['pause_button']:
                task['pause_button'].configure(state="disabled")
            if task['resume_button']:
                task['resume_button'].configure(state="disabled")
            self.log_message(f"Cancellation requested for task: {task['url']}")
    def pause_download(self, task_id):
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
            task['pause_event'].set() # Set the event to signal pause
            
            # Update enhanced progress tracker
            if 'tracker' in task:
                task['tracker'].pause()
                stats = task['tracker']._get_stats_copy()
                if 'enhanced_progress' in task:
                    task['enhanced_progress'].update_from_tracker(stats)
            
            if task['pause_button']:
                task['pause_button'].configure(state="disabled")
            if task['resume_button']:
                task['resume_button'].configure(state="normal")
            self.log_message(f"Pause requested for task: {task['url']}")
            
    def resume_download(self, task_id):
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
            task['pause_event'].clear() # Clear the event to signal resume
            
            # Update enhanced progress tracker
            if 'tracker' in task:
                task['tracker'].resume()
                stats = task['tracker']._get_stats_copy()
                if 'enhanced_progress' in task:
                    task['enhanced_progress'].update_from_tracker(stats)
            
            if task['pause_button']:
                task['pause_button'].configure(state="normal")
            if task['resume_button']:
                task['resume_button'].configure(state="disabled")
            self.log_message(f"Resume requested for task: {task['url']}")
 
    def _cleanup_task_ui(self, task_id):
        # Ensure cleanup is called on the main thread to avoid race conditions
        self.after(0, lambda: self.__cleanup_task_ui_internal(task_id))

    def __cleanup_task_ui_internal(self, task_id):
        if task_id in self.download_tasks:
            try:
                # Clean up enhanced progress tracker
                if 'tracker' in self.download_tasks[task_id]:
                    progress_manager.remove_tracker(task_id)

                self.download_tasks[task_id]['frame'].destroy()  # Destroy UI frame
                del self.download_tasks[task_id]  # Remove from tracking

                # Clean up background thread if it exists
                if task_id in self.background_threads:
                    del self.background_threads[task_id]

                self._update_queue_ui_order()  # Re-grid remaining tasks
                print(f"Cleaned up task UI for: {task_id}")  # Debug logging
            except Exception as e:
                print(f"Error during task cleanup for {task_id}: {e}")

    def _process_download_queue(self):
        while not self.stop_event.is_set():
            task = None
            with self._queue_lock:
                while not self._download_queue_list and not self.stop_event.is_set():
                    self._queue_condition.wait(timeout=0.5) # Wait for new tasks or shutdown signal
                
                if self.stop_event.is_set(): # Check after waiting
                    break
                
                if self._download_queue_list:
                    task = self._download_queue_list.pop(0) # Get the first task
                    print(f"Processing task from queue. Remaining: {len(self._download_queue_list)}")  # Debug logging
 
    def move_task_up(self, task_id):
        with self._queue_lock:
            current_index = -1
            for i, task_item in enumerate(self._download_queue_list):
                if task_item['task_id'] == task_id:
                    current_index = i
                    break
            
            if current_index > 0:
                # Swap the tasks in the list
                self._download_queue_list[current_index], self._download_queue_list[current_index - 1] = \
                    self._download_queue_list[current_index - 1], self._download_queue_list[current_index]
                self.log_message(f"Moved task {self.download_tasks[task_id]['url']} up in queue.")
                self._update_queue_ui_order() # Update UI to reflect new order
            else:
                self.log_message(f"Task {self.download_tasks[task_id]['url']} is already at the top of the queue.")
    def move_task_down(self, task_id):
        with self._queue_lock:
            current_index = -1
            for i, task_item in enumerate(self._download_queue_list):
                if task_item['task_id'] == task_id:
                    current_index = i
                    break
            
            if current_index != -1 and current_index < len(self._download_queue_list) - 1:
                # Swap the tasks in the list
                self._download_queue_list[current_index], self._download_queue_list[current_index + 1] = \
                    self._download_queue_list[current_index + 1], self._download_queue_list[current_index]
                self.log_message(f"Moved task {self.download_tasks[task_id]['url']} down in queue.")
                self._update_queue_ui_order() # Update UI to reflect new order
            else:
                self.log_message(f"Task {self.download_tasks[task_id]['url']} is already at the bottom of the queue.")
    def _update_queue_ui_order(self):
        # This function needs to be called from the main thread
        self.after(0, self.__update_queue_ui_order_internal)
    def __update_queue_ui_order_internal(self):
        # Re-grid all task frames based on their current order in _download_queue_list
        with self._queue_lock:
            for i, task_item in enumerate(self._download_queue_list):
                task_id = task_item['task_id']
                if task_id in self.download_tasks:
                    task_frame = self.download_tasks[task_id]['frame']
                    task_frame.grid(row=i, column=0, padx=5, pady=5, sticky="ew")
        
        # After re-gridding, ensure the scrollable frame updates its view
        self.queue_frame.update_idletasks() # Force update layout
    def _watch_completion(self, processing_thread):
        processing_thread.join()  # Wait for all URLs to be added to the queue

        # Track completion more robustly
        tasks_processed = 0
        total_tasks_expected = 0

        # Count total tasks that were added
        with self._queue_lock:
            total_tasks_expected = len(self._download_queue_list)

        # Wait for all tasks to be processed
        while True:
            with self._queue_lock:
                current_queue_size = len(self._download_queue_list)

            # Calculate tasks processed
            tasks_processed = total_tasks_expected - current_queue_size

            # Check if queue is empty (all tasks have been taken for processing)
            queue_empty = (current_queue_size == 0)

            # Check if queue processor is still alive and working
            queue_processor_running = (hasattr(self, 'queue_processor_thread') and
                                      self.queue_processor_thread.is_alive())

            # Completion condition: queue is empty AND either no processor running OR all tasks processed
            if queue_empty and (not queue_processor_running or len(self.download_tasks) == 0):
                break

            # Failsafe: if we have processed expected tasks and queue is empty, complete
            if queue_empty and tasks_processed >= total_tasks_expected:
                break

            time.sleep(0.3)  # Reduced sleep time for more responsive completion detection

        # Wait for all background threads to complete (HTML generation, history updates, etc.)
        self.log_message("Waiting for background tasks to complete...")
        while self.background_threads:
            # Remove completed threads
            completed_tasks = []
            for task_id, bg_thread in self.background_threads.items():
                if not bg_thread.is_alive():
                    completed_tasks.append(task_id)

            # Clean up completed threads
            for task_id in completed_tasks:
                del self.background_threads[task_id]

            # If there are still active background threads, wait
            if self.background_threads:
                time.sleep(0.5)
            else:
                break

        # Wait a bit more to ensure all cleanup operations complete
        time.sleep(1.0)

        if not self.stop_event.is_set():  # Only show completion if not shutting down
            self.after(0, lambda: self.log_message("\nAll downloads finished."))
            self.after(0, lambda: messagebox.showinfo("Download Complete", "All requested models have been processed."))

            # Reset main UI elements
            self.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
            self.after(0, lambda: self.progress_label.configure(text="Progress: N/A"))
            self.after(0, lambda: self.speed_label.configure(text="Speed: N/A"))
            self.after(0, lambda: self.remaining_label.configure(text="Remaining: N/A"))
    def _process_download_queue(self):
        while not self.stop_event.is_set():
            task = None
            with self._queue_lock:
                while not self._download_queue_list and not self.stop_event.is_set():
                    self._queue_condition.wait(timeout=0.5) # Wait for new tasks or shutdown signal
                
                if self.stop_event.is_set(): # Check after waiting
                    break
                
                if self._download_queue_list:
                    task = self._download_queue_list.pop(0) # Get the first task
            
            if task:
                task_id = task['task_id']
                url = task['url']
                api_key = task['api_key']
                download_path = task['download_path']
                
                # Retrieve task_stop_event after popping as the task_id might be new
                # In rare cases the UI thread may not have registered the task yet.
                if task_id not in self.download_tasks:
                    # Wait briefly for UI registration to catch up
                    waited = 0
                    while task_id not in self.download_tasks and waited < 1.0:
                        time.sleep(0.05)
                        waited += 0.05
                if task_id not in self.download_tasks:
                    self.log_message(f"Error: Task {task_id} not found in download_tasks dictionary. Skipping.")
                    continue
                task_stop_event = self.download_tasks[task_id]['stop_event']
                
                # Handle task cancelled before processing
                if task_stop_event.is_set():
                    self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Cancelled", "red"))
                    self.log_message(f"Task {url} was cancelled before processing. Skipping.")
                    self._cleanup_task_ui(task_id)
                    continue
                try:
                    self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Fetching Info..."))
                    self.log_message(f"\nProcessing URL: {url}")
                    
                    model_info, error_message = get_model_info_from_url(url, api_key)
                    if error_message:
                        self.after_idle(lambda id=task_id, msg=error_message: self._safe_update_status(id, f"Status: Failed - {msg}", "red"))
                        self.log_message(f"Error retrieving model info for {url}: {error_message}")
                        self.after_idle(lambda msg=error_message, u=url: messagebox.showerror("Download Error", f"Could not retrieve model information for URL: {u}\nError: {msg}"))
                        self._cleanup_task_ui(task_id)
                        continue
                    
                    # Check if model is already downloaded
                    if is_model_downloaded(model_info, download_path):
                        self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Already Downloaded"))
                        self.log_message(f"Model {model_info['model']['name']} v{model_info['name']} already downloaded. Skipping.")
                        self._cleanup_task_ui(task_id)
                        continue
                    
                    # Define a specific progress callback for this task (queue-based, non-blocking)
                    def task_progress_callback(bytes_downloaded, total_size, speed):
                        # Put progress update in queue instead of direct UI update
                        try:
                            update_data = {
                                'type': 'progress',
                                'task_id': task_id,
                                'bytes_downloaded': bytes_downloaded,
                                'total_size': total_size,
                                'speed': speed
                            }
                            self.progress_queue.put_nowait(update_data)
                        except queue.Full:
                            pass  # Skip this update if queue is full (prevents memory buildup)
                    
                    self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Downloading..."))
                    download_error, bg_thread = download_civitai_model(model_info, download_path, api_key, progress_callback=task_progress_callback, stop_event=task_stop_event, pause_event=self.download_tasks[task_id]['pause_event'])

                    if download_error:
                        self.after_idle(lambda id=task_id, err=download_error: self._safe_update_status(id, f"Status: Failed - {err}", "red"))
                        self.log_message(f"Download failed for {url}: {download_error}")
                        self.after_idle(lambda u=url, err=download_error: messagebox.showerror("Download Error", f"Download failed for {u}\nError: {err}"))
                        self._cleanup_task_ui(task_id)
                    else:
                        # Store background thread for completion tracking
                        if bg_thread:
                            self.background_threads[task_id] = bg_thread

                        self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Complete", "green"))
                        self.log_message(f"Download complete for {url}")
                        self._cleanup_task_ui(task_id)
                    
                except Exception as e:
                    self.log_message(f"An unexpected error occurred during queue processing: {e}")
                    if 'task_id' in locals() and task_id in self.download_tasks:
                        self.after_idle(lambda id=task_id, err=e: self._safe_update_status(id, f"Status: Unexpected Error - {err}", "red"))
                        self._cleanup_task_ui(task_id)
        self.log_message("Download queue processing stopped.") # Log when the thread actually stops
    
    def _safe_update_status(self, task_id, status_text, text_color=None):
        """Safely update task status with error handling"""
        try:
            if task_id in self.download_tasks:
                if text_color:
                    self.download_tasks[task_id]['status_label'].configure(text=status_text, text_color=text_color)
                else:
                    self.download_tasks[task_id]['status_label'].configure(text=status_text)
        except Exception as e:
            print(f"Error updating status for task {task_id}: {e}")
    
    # Note: _update_task_progress_ui method is now replaced by _apply_progress_update
    # which is called via the progress queue system for better performance
 
    def _on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit? Ongoing downloads will be interrupted."):
            self.stop_event.set() # Signal main queue processing thread to stop
            self.log_message("Shutdown initiated. Signalling individual downloads to stop...")
            
            # Stop progress processor
            try:
                self.progress_queue.put_nowait(None)  # Poison pill to stop progress processor
            except queue.Full:
                pass
            
            # Signal all individual download threads to stop and clear pause events
            for task_id, task_data in list(self.download_tasks.items()): # Iterate over a copy as dict might change
                if 'stop_event' in task_data:
                    task_data['stop_event'].set()
                if 'pause_event' in task_data: # Clear pause event to unblock any waiting threads
                    task_data['pause_event'].clear()
                if task_data.get('cancel_button'):
                    task_data['cancel_button'].configure(state="disabled", text="Stopping...")
                if task_data.get('pause_button'):
                    task_data['pause_button'].configure(state="disabled")
                if task_data.get('resume_button'):
                    task_data['resume_button'].configure(state="disabled")

            # Clear background threads tracking
            self.background_threads.clear()

            self.log_message("Waiting for threads to finish...")
            
            # Wait for the progress processor thread to finish
            if hasattr(self, 'progress_thread') and self.progress_thread.is_alive():
                self.progress_thread.join(timeout=2)
                if self.progress_thread.is_alive():
                    self.log_message("Progress processor thread did not terminate gracefully.")
            
            # Wait for the queue processor thread to finish
            if hasattr(self, 'queue_processor_thread') and self.queue_processor_thread.is_alive():
                self.queue_processor_thread.join(timeout=5) # Give it some time to clean up
                if self.queue_processor_thread.is_alive():
                    self.log_message("Queue processor thread did not terminate gracefully.")
            
            # Wait for the completion watcher thread to finish
            if hasattr(self, 'completion_watcher_thread') and self.completion_watcher_thread.is_alive():
                self.completion_watcher_thread.join(timeout=5)
                if self.completion_watcher_thread.is_alive():
                    self.log_message("Completion watcher thread did not terminate gracefully.")
            self.destroy() # Close the main window
    def clear_gui(self):
        self.url_entry.delete("1.0", ctk.END)
        # Only clear the URL entry as requested

        # Clear background threads tracking
        self.background_threads.clear()

        self.log_message("URL input cleared.")
        # Do not reset other fields or download queue display
        # As per the new requirement, "Clear GUI" only clears the current URLs.
    
    # History management methods
    def refresh_history(self):
        """Refresh the history display."""
        # Update filter options first
        self._update_filter_options()
        
        # Clear existing history items
        for widget in self.history_frame.winfo_children():
            widget.destroy()
        
        # Clean up thumbnail cache periodically
        try:
            thumbnail_manager.cleanup_cache()
        except Exception as e:
            print(f"Error during thumbnail cache cleanup: {e}")
        
        # Use the enhanced search to display all downloads with current filters
        self._perform_filtered_search()
    
    def _create_history_item(self, download, row):
        """Create a GUI item for a download history entry."""
        # Main frame for the history item
        item_frame = ctk.CTkFrame(self.history_frame)
        item_frame.grid(row=row, column=0, padx=5, pady=5, sticky="ew")
        item_frame.grid_columnconfigure(1, weight=1)
        
        # Model info frame
        info_frame = ctk.CTkFrame(item_frame)
        info_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
        info_frame.grid_columnconfigure(1, weight=1)
        
        # Model name and version
        model_name = download.get('model_name', 'Unknown')
        version_name = download.get('version_name', 'Unknown')
        title_text = f"{model_name} - {version_name}"
        if len(title_text) > 60:
            title_text = title_text[:57] + "..."
        
        title_label = ctk.CTkLabel(info_frame, text=title_text, font=ctk.CTkFont(weight="bold"))
        title_label.grid(row=0, column=0, columnspan=2, padx=5, pady=2, sticky="w")
        
        # Model details
        model_type = download.get('model_type', 'Unknown')
        base_model = download.get('base_model', 'Unknown')
        file_size_mb = download.get('file_size', 0) / (1024 * 1024)
        download_date = download.get('download_date', 'Unknown')
        
        # Format date
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(download_date.replace('Z', '+00:00'))
            formatted_date = dt.strftime('%Y-%m-%d %H:%M')
        except:
            formatted_date = download_date[:19] if len(download_date) > 19 else download_date
        
        details_text = f"Type: {model_type} | Base: {base_model} | Size: {file_size_mb:.1f} MB | Downloaded: {formatted_date}"
        details_label = ctk.CTkLabel(info_frame, text=details_text, font=ctk.CTkFont(size=10))
        details_label.grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky="w")
        
        # Trigger words
        trigger_words = download.get('trigger_words', [])
        if trigger_words:
            trigger_text = "Triggers: " + ", ".join(trigger_words[:5])  # Show first 5 triggers
            if len(trigger_words) > 5:
                trigger_text += f" (+{len(trigger_words) - 5} more)"
            trigger_label = ctk.CTkLabel(info_frame, text=trigger_text, font=ctk.CTkFont(size=9), text_color="gray")
            trigger_label.grid(row=2, column=0, columnspan=2, padx=5, pady=2, sticky="w")
        
        # Buttons frame
        buttons_frame = ctk.CTkFrame(item_frame, fg_color="transparent")
        buttons_frame.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
        
        # Open folder button
        open_btn = ctk.CTkButton(
            buttons_frame,
            text="Open Folder",
            command=lambda d=download: self.open_model_folder(d),
            width=80,
            height=25
        )
        open_btn.grid(row=0, column=0, padx=2)
        
        # View report button
        report_btn = ctk.CTkButton(
            buttons_frame,
            text="View Report",
            command=lambda d=download: self.view_model_report(d),
            width=80,
            height=25
        )
        report_btn.grid(row=0, column=1, padx=2)
        
        # Delete button
        delete_btn = ctk.CTkButton(
            buttons_frame,
            text="Delete",
            command=lambda d=download: self.delete_model_entry(d),
            width=60,
            height=25,
            fg_color="red",
            hover_color="darkred"
        )
        delete_btn.grid(row=0, column=2, padx=2)
    
    def search_history(self):
        """Search through download history (legacy method - now redirects to enhanced search)."""
        # Use the new enhanced search method
        self._perform_filtered_search()
    
    def _on_search_changed(self, event=None):
        """Handle search entry changes with debouncing."""
        # Cancel any pending search
        if hasattr(self, '_search_after_id'):
            self.after_cancel(self._search_after_id)
        
        # Schedule a new search after 300ms of inactivity (reduced for faster response)
        self._search_after_id = self.after(300, self._perform_filtered_search)
    
    def _on_filter_changed(self, *args):
        """Handle filter changes with debouncing."""
        # Cancel any pending search
        if hasattr(self, '_search_after_id'):
            self.after_cancel(self._search_after_id)
        
        # Schedule a new search after 300ms of inactivity
        self._search_after_id = self.after(300, self._perform_filtered_search)
    
    def _on_sort_changed(self, value):
        """Handle sort order changes."""
        # Parse sort value (e.g., "Date ↓" -> "download_date", "desc")
        sort_mapping = {
            "Date ↓": ("download_date", "desc"),
            "Date ↑": ("download_date", "asc"),
            "Name ↓": ("model_name", "desc"),
            "Name ↑": ("model_name", "asc"),
            "Size ↓": ("file_size", "desc"),
            "Size ↑": ("file_size", "asc"),
            "Type ↓": ("model_type", "desc"),
            "Type ↑": ("model_type", "asc")
        }
        
        if value in sort_mapping:
            self.current_sort_by, self.current_sort_order = sort_mapping[value]
        
        # Trigger immediate search
        self._perform_filtered_search()
    
    def _perform_filtered_search(self):
        """Perform search with current filters and sorting."""
        query = self.search_entry.get().strip()
        
        # Build filter criteria
        filters = {}
        
        # Model type filter
        model_type = self.model_type_var.get()
        if model_type and model_type != "All":
            filters['model_type'] = model_type
        
        # Base model filter
        base_model = self.base_model_var.get()
        if base_model and base_model != "All":
            filters['base_model'] = base_model
        
        # Date range filters
        date_from = self.date_from_entry.get().strip()
        if date_from:
            filters['date_from'] = date_from
        
        date_to = self.date_to_entry.get().strip()
        if date_to:
            filters['date_to'] = date_to
        
        # File size range filters
        size_min = self.size_min_entry.get().strip()
        if size_min:
            try:
                filters['size_min'] = float(size_min) * 1024 * 1024  # Convert MB to bytes
            except ValueError:
                pass  # Invalid input, ignore
        
        size_max = self.size_max_entry.get().strip()
        if size_max:
            try:
                filters['size_max'] = float(size_max) * 1024 * 1024  # Convert MB to bytes
            except ValueError:
                pass  # Invalid input, ignore
        
        # Trigger words filter
        if self.triggers_var.get():
            filters['has_trigger_words'] = True
        
        # Store current filters
        self.current_filters = filters
        
        # Clear existing history items
        for widget in self.history_frame.winfo_children():
            widget.destroy()
        
        # Perform search with filters
        downloads = self.history_manager.search_downloads(
            query=query,
            filters=filters,
            sort_by=self.current_sort_by,
            sort_order=self.current_sort_order
        )
        
        # Update statistics
        if query or filters:
            self.stats_label.configure(text=f"Found {len(downloads)} matches")
        else:
            stats = self.history_manager.get_stats()
            total_size_mb = stats['total_size'] / (1024 * 1024)
            self.stats_label.configure(
                text=f"Total: {stats['total_downloads']} models, {total_size_mb:.1f} MB"
            )
        
        # Display results with highlighting
        for i, download in enumerate(downloads):
            self._create_history_item_with_highlight(download, i, query)
        
        # Preload thumbnails for visible items in background
        model_dirs = [download.get('download_path', '') for download in downloads if download.get('download_path')]
        if model_dirs:
            thumbnail_manager.preload_thumbnails(model_dirs, 'small')
        
        # Update active filters display
        self._update_active_filters_display()
    
    def _create_history_item_with_highlight(self, download, row, search_query=""):
        """Create a GUI item for a download history entry with search highlighting."""
        # Main frame for the history item
        item_frame = ctk.CTkFrame(self.history_frame)
        item_frame.grid(row=row, column=0, padx=5, pady=5, sticky="ew")
        item_frame.grid_columnconfigure(2, weight=1)  # Changed to accommodate thumbnail
        
        # Thumbnail widget
        thumbnail_widget = ThumbnailWidget(item_frame, size=(64, 64))
        thumbnail_widget.grid(row=0, column=0, rowspan=2, padx=5, pady=5, sticky="nw")
        
        # Load thumbnail for this model
        model_dir = download.get('download_path', '')
        thumbnail_path = thumbnail_manager.get_model_thumbnail(model_dir, 'small')
        fallback_path = thumbnail_manager.get_fallback_thumbnail('small')
        thumbnail_widget.set_thumbnail(thumbnail_path, fallback_path)
        
        # Set click callback to view full image
        def on_thumbnail_click(path):
            if path and os.path.exists(path):
                try:
                    import webbrowser
                    webbrowser.open(f"file://{os.path.abspath(path)}")
                except Exception as e:
                    print(f"Error opening image: {e}")
        
        thumbnail_widget.set_click_callback(on_thumbnail_click)
        
        # Model info frame (adjusted for thumbnail)
        info_frame = ctk.CTkFrame(item_frame)
        info_frame.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky="ew")
        info_frame.grid_columnconfigure(1, weight=1)
        
        # Model name and version with highlighting
        model_name = download.get('model_name', 'Unknown')
        version_name = download.get('version_name', 'Unknown')
        title_text = f"{model_name} - {version_name}"
        if len(title_text) > 60:
            title_text = title_text[:57] + "..."
        
        # Determine if this item matches the search query
        text_color = "yellow" if search_query and search_query.lower() in title_text.lower() else None
        
        title_label = ctk.CTkLabel(
            info_frame,
            text=title_text,
            font=ctk.CTkFont(weight="bold"),
            text_color=text_color
        )
        title_label.grid(row=0, column=0, columnspan=2, padx=5, pady=2, sticky="w")
        
        # Model details
        model_type = download.get('model_type', 'Unknown')
        base_model = download.get('base_model', 'Unknown')
        file_size_mb = download.get('file_size', 0) / (1024 * 1024)
        download_date = download.get('download_date', 'Unknown')
        
        # Format date
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(download_date.replace('Z', '+00:00'))
            formatted_date = dt.strftime('%Y-%m-%d %H:%M')
        except:
            formatted_date = download_date[:19] if len(download_date) > 19 else download_date
        
        details_text = f"Type: {model_type} | Base: {base_model} | Size: {file_size_mb:.1f} MB | Downloaded: {formatted_date}"
        
        # Highlight details if they match search
        details_color = "yellow" if search_query and (
            search_query.lower() in model_type.lower() or
            search_query.lower() in base_model.lower()
        ) else None
        
        details_label = ctk.CTkLabel(
            info_frame,
            text=details_text,
            font=ctk.CTkFont(size=10),
            text_color=details_color
        )
        details_label.grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky="w")
        
        # Trigger words with highlighting
        trigger_words = download.get('trigger_words', [])
        if trigger_words:
            trigger_text = "Triggers: " + ", ".join(trigger_words[:5])  # Show first 5 triggers
            if len(trigger_words) > 5:
                trigger_text += f" (+{len(trigger_words) - 5} more)"
            
            # Check if any trigger words match search
            trigger_color = "yellow" if search_query and any(
                search_query.lower() in trigger.lower() for trigger in trigger_words
            ) else "gray"
            
            trigger_label = ctk.CTkLabel(
                info_frame,
                text=trigger_text,
                font=ctk.CTkFont(size=9),
                text_color=trigger_color
            )
            trigger_label.grid(row=2, column=0, columnspan=2, padx=5, pady=2, sticky="w")
        
        # Buttons frame (adjusted for thumbnail)
        buttons_frame = ctk.CTkFrame(item_frame, fg_color="transparent")
        buttons_frame.grid(row=1, columnspan=2, padx=5, pady=5, sticky="ew")
        
        # Open folder button
        open_btn = ctk.CTkButton(
            buttons_frame,
            text="Open Folder",
            command=lambda d=download: self.open_model_folder(d),
            width=80,
            height=25
        )
        open_btn.grid(row=0, column=0, padx=2)
        
        # View report button
        report_btn = ctk.CTkButton(
            buttons_frame,
            text="View Report",
            command=lambda d=download: self.view_model_report(d),
            width=80,
            height=25
        )
        report_btn.grid(row=0, column=1, padx=2)
        
        # Delete button
        delete_btn = ctk.CTkButton(
            buttons_frame,
            text="Delete",
            command=lambda d=download: self.delete_model_entry(d),
            width=60,
            height=25,
            fg_color="red",
            hover_color="darkred"
        )
        delete_btn.grid(row=0, column=2, padx=2)
    
    def _update_active_filters_display(self):
        """Update the display of active filters."""
        # Clear existing filter chips
        for widget in self.active_filters_frame.winfo_children():
            widget.destroy()
        
        active_count = 0
        
        # Search query chip
        query = self.search_entry.get().strip()
        if query:
            chip = ctk.CTkLabel(
                self.active_filters_frame,
                text=f"Search: '{query}'",
                fg_color="blue",
                corner_radius=10,
                padx=8,
                pady=2
            )
            chip.grid(row=0, column=active_count, padx=2, pady=2)
            active_count += 1
        
        # Filter chips
        filter_labels = {
            'model_type': 'Type',
            'base_model': 'Base',
            'date_from': 'From',
            'date_to': 'To',
            'size_min': 'Min Size',
            'size_max': 'Max Size',
            'has_trigger_words': 'Has Triggers'
        }
        
        for filter_key, label in filter_labels.items():
            if filter_key in self.current_filters:
                value = self.current_filters[filter_key]
                if filter_key in ['size_min', 'size_max']:
                    # Convert bytes back to MB for display
                    value = f"{value / (1024 * 1024):.1f} MB"
                elif filter_key == 'has_trigger_words':
                    value = "Yes"
                
                chip = ctk.CTkLabel(
                    self.active_filters_frame,
                    text=f"{label}: {value}",
                    fg_color="green",
                    corner_radius=10,
                    padx=8,
                    pady=2
                )
                chip.grid(row=0, column=active_count, padx=2, pady=2)
                active_count += 1
        
        # Sort chip
        if hasattr(self, 'sort_var'):
            sort_text = self.sort_var.get()
            if sort_text != "Date ↓":  # Only show if not default
                chip = ctk.CTkLabel(
                    self.active_filters_frame,
                    text=f"Sort: {sort_text}",
                    fg_color="purple",
                    corner_radius=10,
                    padx=8,
                    pady=2
                )
                chip.grid(row=0, column=active_count, padx=2, pady=2)
                active_count += 1
        
        # Show "No filters" if no active filters
        if active_count == 0:
            no_filters_label = ctk.CTkLabel(
                self.active_filters_frame,
                text="No active filters",
                text_color="gray"
            )
            no_filters_label.grid(row=0, column=0, padx=5, pady=2)
    
    def _update_filter_options(self):
        """Update the dropdown options based on available data."""
        try:
            options = self.history_manager.get_filter_options()
            
            # Update model type dropdown
            model_types = ["All"] + options.get('model_types', [])
            self.model_type_menu.configure(values=model_types)
            
            # Update base model dropdown
            base_models = ["All"] + options.get('base_models', [])
            self.base_model_menu.configure(values=base_models)
            
        except Exception as e:
            print(f"Error updating filter options: {e}")
    
    def clear_filters(self):
        """Clear all filters and reset search."""
        # Clear search entry
        self.search_entry.delete(0, ctk.END)
        
        # Reset dropdown filters
        self.model_type_var.set("All")
        self.base_model_var.set("All")
        
        # Clear date filters
        self.date_from_entry.delete(0, ctk.END)
        self.date_to_entry.delete(0, ctk.END)
        
        # Clear size filters
        self.size_min_entry.delete(0, ctk.END)
        self.size_max_entry.delete(0, ctk.END)
        
        # Reset checkbox
        self.triggers_var.set(False)
        
        # Reset sort to default
        self.sort_var.set("Date ↓")
        self.current_sort_by = "download_date"
        self.current_sort_order = "desc"
        
        # Clear current filters
        self.current_filters = {}
        
        # Refresh history display
        self.refresh_history()
    
    def scan_downloads(self):
        """Scan the download directory to populate history."""
        download_path = self.download_path_entry.get()
        if not download_path:
            messagebox.showerror("Error", "Please set a download path first.")
            return
        
        if not os.path.exists(download_path):
            messagebox.showerror("Error", f"Download path does not exist: {download_path}")
            return
        
        # Show progress dialog
        progress_dialog = ctk.CTkToplevel(self)
        progress_dialog.title("Scanning Downloads")
        progress_dialog.geometry("300x100")
        progress_dialog.transient(self)
        progress_dialog.grab_set()
        
        progress_label = ctk.CTkLabel(progress_dialog, text="Scanning download directory...")
        progress_label.pack(pady=20)
        
        def scan_in_thread():
            try:
                self.history_manager.scan_and_populate_history(download_path)
                self.after(0, lambda: [progress_dialog.destroy(), self.refresh_history(),
                                     messagebox.showinfo("Scan Complete", "Download directory scan completed.")])
            except Exception as e:
                self.after(0, lambda: [progress_dialog.destroy(),
                                     messagebox.showerror("Scan Error", f"Error during scan: {e}")])
        
        scan_thread = threading.Thread(target=scan_in_thread, daemon=True)
        scan_thread.start()
    
    def export_history(self):
        """Export download history to a file."""
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export History"
        )
        
        if filename:
            if self.history_manager.export_history(filename):
                messagebox.showinfo("Export Success", f"History exported to {filename}")
            else:
                messagebox.showerror("Export Error", "Failed to export history")
    
    def import_history(self):
        """Import download history from a file."""
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import History"
        )
        
        if filename:
            merge = messagebox.askyesno(
                "Import Options",
                "Do you want to merge with existing history?\n\nYes = Merge (add new entries)\nNo = Replace (overwrite existing history)"
            )
            
            if self.history_manager.import_history(filename, merge=merge):
                self.refresh_history()
                messagebox.showinfo("Import Success", "History imported successfully")
            else:
                messagebox.showerror("Import Error", "Failed to import history")
    
    def open_model_folder(self, download):
        """Open the model's download folder."""
        download_path = download.get('download_path')
        if not download_path or not validate_path(download_path):
            messagebox.showerror("Error", "Model folder not found")
            return
        
        if not open_folder_cross_platform(download_path):
            messagebox.showerror("Error", "Could not open folder.")

    def view_model_report(self, download):
        """Open the model's HTML report."""
        html_report_path = download.get('html_report_path')
        if not html_report_path or not os.path.exists(html_report_path):
            messagebox.showerror("Error", "HTML report not found")
            return
        
        try:
            import webbrowser
            webbrowser.open(f"file://{os.path.abspath(html_report_path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open report: {e}")
    
    def delete_model_entry(self, download):
        """Delete a model entry with confirmation."""
        model_name = download.get('model_name', 'Unknown')
        version_name = download.get('version_name', 'Unknown')
        
        # Create custom dialog
        dialog = ctk.CTkToplevel(self)
        dialog.title("Delete Model")
        dialog.geometry("400x200")
        dialog.transient(self)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (dialog.winfo_screenheight() // 2) - (200 // 2)
        dialog.geometry(f"400x200+{x}+{y}")
        
        # Dialog content
        msg_label = ctk.CTkLabel(
            dialog,
            text=f"Delete '{model_name} - {version_name}'?",
            font=ctk.CTkFont(weight="bold")
        )
        msg_label.pack(pady=10)
        
        info_label = ctk.CTkLabel(dialog, text="Choose what to delete:")
        info_label.pack(pady=5)
        
        delete_files_var = ctk.BooleanVar(value=False)
        delete_files_cb = ctk.CTkCheckBox(
            dialog,
            text="Delete files from disk (WARNING: This cannot be undone!)",
            variable=delete_files_var
        )
        delete_files_cb.pack(pady=10)
        
        # Buttons frame
        buttons_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons_frame.pack(pady=20)
        
        def confirm_delete():
            dialog.destroy()
            delete_files = delete_files_var.get()
            
            if self.history_manager.delete_download_entry(download['id'], delete_files=delete_files):
                self.refresh_history()
                action_text = "and files " if delete_files else ""
                messagebox.showinfo("Deleted", f"Model entry {action_text}deleted successfully")
            else:
                messagebox.showerror("Error", "Failed to delete model entry")
        
        def cancel_delete():
            dialog.destroy()
        
        cancel_btn = ctk.CTkButton(buttons_frame, text="Cancel", command=cancel_delete)
        cancel_btn.pack(side="left", padx=5)
        
        delete_btn = ctk.CTkButton(
            buttons_frame,
            text="Delete",
            command=confirm_delete,
            fg_color="red",
            hover_color="darkred"
        )
        delete_btn.pack(side="right", padx=5)


if __name__ == "__main__":
    app = App()
    app.mainloop()
