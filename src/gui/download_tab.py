"""
Download tab component for the Civitai Model Downloader GUI.

This module contains all the download tab related functionality.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import threading
import urllib.parse
import queue

# Import utilities
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

# Import other required components
from src.civitai_downloader import get_model_info_from_url, download_civitai_model, download_file, is_model_downloaded
from src.progress_tracker import progress_manager, ProgressPhase, ProgressStats
from src.thumbnail_manager import thumbnail_manager
from src.enhanced_progress_bar import EnhancedProgressWidget, ThumbnailWidget


class DownloadTab:
    """Download tab component for the main application."""
    
    def __init__(self, parent_app, download_tab_frame):
        """
        Initialize the download tab component.
        
        Args:
            parent_app: The main application instance
            download_tab_frame: The tkinter frame for the download tab
        """
        self.parent_app = parent_app
        self.download_tab_frame = download_tab_frame
        
        # Initialize download tab specific attributes
        self.setup_download_tab()
    
    def setup_download_tab(self):
        """Setup the download tab UI components."""
        # Configure grid layout for download tab
        self.download_tab_frame.grid_columnconfigure(1, weight=1)
        self.download_tab_frame.grid_rowconfigure(4, weight=1)

        # Input Frame
        self.input_frame = ctk.CTkFrame(self.download_tab_frame)
        self.input_frame.grid(row=0, columnspan=2, padx=10, pady=10, sticky="ew")
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

        # Load environment variables
        from dotenv import load_dotenv
        load_dotenv()
        self.api_key_entry.insert(0, os.getenv("CIVITAI_API_KEY", ""))
        self.download_path_entry.insert(0, os.getenv("DOWNLOAD_PATH", os.getcwd()))

        # Download Button
        self.download_button = ctk.CTkButton(self.download_tab_frame, text="Start Download", command=self.start_download_thread)
        self.download_button.grid(row=1, column=0, padx=(10, 5), pady=10, sticky="ew")

        # Open Download Folder Button
        self.open_folder_button = ctk.CTkButton(self.download_tab_frame, text="Open Downloads Folder", command=self.open_download_folder)
        self.open_folder_button.grid(row=1, column=1, padx=(5, 10), pady=10, sticky="ew")

        # Clear/Reset Button
        self.clear_button = ctk.CTkButton(self.download_tab_frame, text="Clear/Reset GUI", command=self.clear_gui)
        self.clear_button.grid(row=8, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        # Download Stats Labels
        self.progress_label = ctk.CTkLabel(self.download_tab_frame, text="Progress: N/A")
        self.progress_label.grid(row=2, column=0, columnspan=2, padx=10, pady=(10, 0), sticky="w")
        self.speed_label = ctk.CTkLabel(self.download_tab_frame, text="Speed: N/A")
        self.speed_label.grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 0), sticky="w")
        self.remaining_label = ctk.CTkLabel(self.download_tab_frame, text="Remaining: N/A")
        self.remaining_label.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")


        # Download Queue Display
        self.queue_frame = ctk.CTkScrollableFrame(self.download_tab_frame, label_text="Download Queue")
        self.queue_frame.grid(row=5, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.queue_frame.grid_columnconfigure(0, weight=1)

        # Log Area
        self.log_label = ctk.CTkLabel(self.download_tab_frame, text="Logs:")
        self.log_label.grid(row=6, column=0, padx=10, pady=(10, 0), sticky="w")
        self.log_text = ctk.CTkTextbox(self.download_tab_frame, width=600, height=200)
        self.log_text.grid(row=7, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.log_text.configure(state="disabled") # Make it read-only

        # Configure grid layout to expand queue and log area
        self.download_tab_frame.grid_rowconfigure(5, weight=2) # Queue frame
        self.download_tab_frame.grid_rowconfigure(7, weight=1) # Log area

    def browse_txt_file(self):
        """Browse for a text file containing URLs."""
        file_path = browse_text_file(self.parent_app)
        if file_path:
            with open(file_path, 'r') as f:
                content = f.read()
            self.url_entry.delete("1.0", ctk.END) # Clear existing content
            self.url_entry.insert("1.0", content) # Insert new content

    def browse_download_path(self):
        """Browse for download directory."""
        dir_path = browse_directory(self.parent_app)
        if dir_path:
            self.download_path_entry.delete(0, ctk.END)
            self.download_path_entry.insert(0, dir_path)

    def log_message(self, message):
        """Log a message to the GUI log area."""
        # Initialize logger if not already done
        if not hasattr(self, 'logger'):
            self.logger = ThreadSafeLogger(self.log_text)
        self.logger.log_message(message)

    def start_download_thread(self):
        """Start the download process in a separate thread."""
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
        """Initiate the download process."""
        # Add URLs to the queue
        self._add_urls_to_queue(url_input_content, api_key, download_path)

        # Start queue processing in a separate thread if not already running
        if not hasattr(self.parent_app, 'queue_processor_thread') or not self.parent_app.queue_processor_thread.is_alive():
            self.parent_app.queue_processor_thread = threading.Thread(target=self.parent_app._process_download_queue, daemon=True)
            self.parent_app.queue_processor_thread.start()
        
        # This thread will wait for all tasks to be done and then re-enable the button
        # It should not be daemonized if we want to join it gracefully
        self.parent_app.completion_watcher_thread = threading.Thread(target=self._watch_completion, args=(self.processing_and_completion_thread,), daemon=True)
        self.parent_app.completion_watcher_thread.start()

        # The _initiate_download_process now just adds URLs and starts the queue processor.
        # The completion logic is moved to _watch_completion.
        # Removed premature completion messages from here.

    def _update_progress(self, bytes_downloaded, total_size, speed):
        """Update the progress display."""
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
        """Open the download folder in the file explorer."""
        download_path = self.download_path_entry.get()
        if not download_path or not validate_path(download_path):
            messagebox.showerror("Error", "Download path is not valid or not set.")
            return

        if not open_folder_cross_platform(download_path):
            messagebox.showerror("Error", "Could not open folder.")

    def _add_urls_to_queue(self, url_input_content, api_key, download_path):
        """Add URLs to the download queue."""
        try:
            # Parse URLs using utility function
            urls = parse_urls_from_text(url_input_content)
            if not urls:
                self.log_message("No URLs provided. Exiting.")
                messagebox.showinfo("Download Info", "No URLs provided.")
                # Re-enable download button immediately if no URLs
                self.parent_app.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
                return
            
            # Add each URL as a task to the queue
            for url in urls:
                # Validate URL format using utility function
                if not validate_civitai_url(url):
                    self.log_message(f"Skipping invalid URL: {url}")
                    # Pre-register task to avoid race with queue processor
                    task_id = f"task_{hash(url)}_{self.parent_app.queue_row_counter}"
                    if task_id not in self.parent_app.download_tasks:
                        # Minimal placeholder; UI will enrich this entry on main thread
                        self.parent_app.download_tasks[task_id] = {
                            'url': url,
                            'stop_event': threading.Event(),
                            'pause_event': threading.Event(),
                            'frame': None,
                            'progress_bar': None,
                            'enhanced_progress': None,
                            'tracker': None,
                            'status_label': None,
                            'cancel_button': None,
                            'pause_button': None,
                            'resume_button': None,
                        }
                    # Add GUI element for the invalid task with a failed status
                    self.parent_app.after(0, self._add_download_task_ui, task_id, url)
                    # Attempt to set status once UI is ready; guard missing label
                    def _mark_invalid(tid=task_id):
                        try:
                            if tid in self.parent_app.download_tasks and self.parent_app.download_tasks[tid].get('status_label'):
                                self.parent_app.download_tasks[tid]['status_label'].configure(text=f"Status: Failed - Invalid URL format", text_color="red")
                        except Exception:
                            pass
                    self.parent_app.after(50, _mark_invalid)
                    continue
                # Create a unique ID for each download task
                task_id = f"task_{hash(url)}_{self.parent_app.queue_row_counter}"
                # Pre-register task to avoid race with queue processor thread
                if task_id not in self.parent_app.download_tasks:
                    self.parent_app.download_tasks[task_id] = {
                        'url': url,
                        'stop_event': threading.Event(),
                        'pause_event': threading.Event(),
                        'frame': None,
                        'progress_bar': None,
                        'enhanced_progress': None,
                        'tracker': None,
                        'status_label': None,
                        'cancel_button': None,
                        'pause_button': None,
                        'resume_button': None,
                    }
                with self.parent_app._queue_lock:
                    self.parent_app._download_queue_list.append({'task_id': task_id, 'url': url, 'api_key': api_key, 'download_path': download_path})
                    self.parent_app._queue_condition.notify() # Signal that a new item has been added
                # Add GUI element for the new task
                self.parent_app.after(0, self._add_download_task_ui, task_id, url)
        except Exception as e:
            self.log_message(f"An unexpected error occurred while adding URLs to queue: {e}")
            messagebox.showerror("Unexpected Error", f"An unexpected error occurred while adding URLs to queue: {e}")
        finally:
            # Re-enable the download button only after all URLs are added to the queue.
            # Actual download processing happens in _process_download_queue.
            self.parent_app.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))

    def _add_download_task_ui(self, task_id, url):
        """Add a download task to the UI."""
        row = self.parent_app.queue_row_counter
        self.parent_app.queue_row_counter += 1
        task_frame = ctk.CTkFrame(self.queue_frame)
        task_frame.grid(row=row, column=0, padx=5, pady=5, sticky="ew")
        task_frame.grid_columnconfigure(1, weight=1)
        
        # URL display
        url_display = (url[:50] + '...') if len(url) > 53 else url
        task_label = ctk.CTkLabel(task_frame, text=f"URL: {url_display}", anchor="w")
        task_label.grid(row=0, column=0, padx=5, pady=2, sticky="w")
        
        # Enhanced progress widget
        enhanced_progress = EnhancedProgressWidget(task_frame, task_id)
        enhanced_progress.grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky="ew")
        
        # Create progress tracker
        tracker = progress_manager.create_tracker(task_id)
        tracker.set_phase(ProgressPhase.INITIALIZING)
        # Store references to update later. If a placeholder already exists (pre-registered
        # in _add_urls_to_queue), update it instead of overwriting to avoid races.
        existing = self.parent_app.download_tasks.get(task_id, {})
        self.parent_app.download_tasks[task_id] = {
            'frame': task_frame,
            'label': task_label,
            'progress_bar': enhanced_progress.progress_bar,  # For backward compatibility
            'enhanced_progress': enhanced_progress,
            'tracker': tracker,
            'status_label': existing.get('status_label'),  # Might not exist; keep None
            'url': existing.get('url', url), # Preserve original URL if set
            'stop_event': existing.get('stop_event', threading.Event()), # Per-task stop event
            'pause_event': existing.get('pause_event', threading.Event()), # Per-task pause event
            'cancel_button': existing.get('cancel_button'),
            'pause_button': existing.get('pause_button'),
            'resume_button': existing.get('resume_button')
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
        pause_button = ctk.CTkButton(button_frame, text="Pause", command=lambda tid=task_id: self.parent_app.pause_download(tid))
        pause_button.grid(row=0, column=0, padx=2, pady=0, sticky="ew")
        self.parent_app.download_tasks[task_id]['pause_button'] = pause_button
        # Add Resume Button (initially disabled)
        resume_button = ctk.CTkButton(button_frame, text="Resume", command=lambda tid=task_id: self.parent_app.resume_download(tid), state="disabled")
        resume_button.grid(row=0, column=1, padx=2, pady=0, sticky="ew")
        self.parent_app.download_tasks[task_id]['resume_button'] = resume_button
        
        # Add Cancel Button
        cancel_button = ctk.CTkButton(button_frame, text="Cancel", command=lambda tid=task_id: self.parent_app.cancel_download(tid))
        cancel_button.grid(row=0, column=2, padx=2, pady=0, sticky="ew")
        self.parent_app.download_tasks[task_id]['cancel_button'] = cancel_button
        # Add Move Up Button
        move_up_button = ctk.CTkButton(button_frame, text="▲", command=lambda tid=task_id: self.parent_app.move_task_up(tid), width=30)
        move_up_button.grid(row=0, column=3, padx=2, pady=0, sticky="ew")
        self.parent_app.download_tasks[task_id]['move_up_button'] = move_up_button
        # Add Move Down Button
        move_down_button = ctk.CTkButton(button_frame, text="▼", command=lambda tid=task_id: self.parent_app.move_task_down(tid), width=30)
        move_down_button.grid(row=0, column=4, padx=2, pady=0, sticky="ew")
        self.parent_app.download_tasks[task_id]['move_down_button'] = move_down_button

    def clear_gui(self):
        """Clear the GUI input fields."""
        self.url_entry.delete("1.0", ctk.END)
        # Only clear the URL entry as requested

        # Clear background threads tracking
        self.parent_app.background_threads.clear()

        self.log_message("URL input cleared.")
        # Do not reset other fields or download queue display
        # As per the new requirement, "Clear GUI" only clears the current URLs.

    def _watch_completion(self, processing_thread):
        """Watch for completion of all downloads."""
        processing_thread.join()  # Wait for all URLs to be added to the queue

        # Track completion more robustly
        tasks_processed = 0
        total_tasks_expected = 0

        # Count total tasks that were added
        with self.parent_app._queue_lock:
            total_tasks_expected = len(self.parent_app._download_queue_list)

        # Wait for all tasks to be processed
        while True:
            with self.parent_app._queue_lock:
                current_queue_size = len(self.parent_app._download_queue_list)

            # Calculate tasks processed
            tasks_processed = total_tasks_expected - current_queue_size

            # Check if queue is empty (all tasks have been taken for processing)
            queue_empty = (current_queue_size == 0)

            # Check if queue processor is still alive and working
            queue_processor_running = (hasattr(self.parent_app, 'queue_processor_thread') and
                                      self.parent_app.queue_processor_thread.is_alive())

            # Completion condition: queue is empty AND either no processor running OR all tasks processed
            if queue_empty and (not queue_processor_running or len(self.parent_app.download_tasks) == 0):
                break

            # Failsafe: if we have processed expected tasks and queue is empty, complete
            if queue_empty and tasks_processed >= total_tasks_expected:
                break

            import time
            time.sleep(0.3)  # Reduced sleep time for more responsive completion detection

        # Wait for all background threads to complete (HTML generation, history updates, etc.)
        self.log_message("Waiting for background tasks to complete...")
        while self.parent_app.background_threads:
            # Remove completed threads
            completed_tasks = []
            for task_id, bg_thread in self.parent_app.background_threads.items():
                if not bg_thread.is_alive():
                    completed_tasks.append(task_id)

            # Clean up completed threads
            for task_id in completed_tasks:
                del self.parent_app.background_threads[task_id]

            # If there are still active background threads, wait
            if self.parent_app.background_threads:
                import time
                time.sleep(0.5)
            else:
                break

        # Wait a bit more to ensure all cleanup operations complete
        import time
        time.sleep(1.0)

        if not self.parent_app.stop_event.is_set():  # Only show completion if not shutting down
            self.parent_app.after(0, lambda: self.log_message("\nAll downloads finished."))
            self.parent_app.after(0, lambda: messagebox.showinfo("Download Complete", "All requested models have been processed."))

            # Reset main UI elements
            self.parent_app.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
            self.parent_app.after(0, lambda: self.progress_label.configure(text="Progress: N/A"))
            self.parent_app.after(0, lambda: self.speed_label.configure(text="Speed: N/A"))
            self.parent_app.after(0, lambda: self.remaining_label.configure(text="Remaining: N/A"))


# This would be used by the main application to initialize the download tab
def create_download_tab(parent_app, download_tab_frame):
    """
    Factory function to create and initialize the download tab.
    
    Args:
        parent_app: The main application instance
        download_tab_frame: The tkinter frame for the download tab
        
    Returns:
        DownloadTab: Initialized download tab component
    """
    return DownloadTab(parent_app, download_tab_frame)