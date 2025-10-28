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

# Import memory monitor
from src.memory_monitor import memory_monitor, MemoryWarningLevel

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

# Import download tab component
from src.gui.download_tab import create_download_tab


# Assuming civitai_downloader functions are available
from src.civitai_downloader import get_model_info_from_url, download_civitai_model, download_file, is_model_downloaded
from src.progress_tracker import progress_manager, ProgressPhase, ProgressStats
from src.enhanced_progress_bar import EnhancedProgressWidget

class App(ctk.CTk):
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
        self.queue_session_totals = {'completed': 0, 'failed': 0}
        
        # Progress update queue for thread-safe UI updates
        self.progress_queue = queue.Queue()
        self._start_progress_processor()

        # History feature disabled
        self.history_manager = None
        
        # Initialize memory monitoring
        self._setup_memory_monitoring()

        self.protocol("WM_DELETE_WINDOW", self._on_closing) # Handle window close event

        # Create main notebook for tabs
        self.notebook = ctk.CTkTabview(self)
        self.notebook.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        # Configure grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Create tabs
        self.download_tab = self.notebook.add("Downloads")
        
        # Setup download tab using component
        self.download_tab_component = create_download_tab(self, self.download_tab)
        # Expose key widgets from the component for legacy methods
        self.url_entry = self.download_tab_component.url_entry
        self.download_path_entry = self.download_tab_component.download_path_entry
        self.api_key_entry = self.download_tab_component.api_key_entry
        self.download_button = self.download_tab_component.download_button
        self.open_folder_button = self.download_tab_component.open_folder_button
        self.clear_button = self.download_tab_component.clear_button
        self.queue_frame = self.download_tab_component.queue_frame
        self.log_text = self.download_tab_component.log_text
        self._refresh_queue_summary()
        
        # History tab removed
        
        # Start memory monitoring
        memory_monitor.start_monitoring()
        try:
            initial_stats = memory_monitor.get_current_stats()
        except Exception:
            initial_stats = None
        self._update_memory_indicator(initial_stats)
    
    def _setup_memory_monitoring(self):
        """Setup memory monitoring with warning callbacks"""
        def memory_warning_callback(stats):
            """Handle memory warnings"""
            try:
                self.after(0, lambda s=stats: self._update_memory_indicator(s))
                warning_message = (
                    f"Memory Warning ({stats.warning_level.value.title()}):\n"
                    f"Process: {stats.process_memory_mb:.1f} MB\n"
                    f"System: {stats.system_memory_percent:.1f}% used\n"
                    f"Available: {stats.available_memory_mb:.1f} MB"
                )
                
                # Use thread-safe UI updates
                self.after(0, lambda: self._show_memory_warning(warning_message, stats.warning_level))
                
                # Auto-cleanup for high/critical warnings
                if stats.warning_level in [MemoryWarningLevel.HIGH, MemoryWarningLevel.CRITICAL]:
                    self.after(0, self._perform_memory_cleanup)
                    
            except Exception as e:
                print(f"Error handling memory warning: {e}")
        
        # Set the warning callback
        memory_monitor.warning_callback = memory_warning_callback
    
    def _show_memory_warning(self, message, level):
        """Show memory warning dialog"""
        try:
            if level == MemoryWarningLevel.CRITICAL:
                messagebox.showerror("Critical Memory Warning",
                    f"{message}\n\nApplication may become unstable. Consider closing unused downloads or restarting the application.")
            elif level == MemoryWarningLevel.HIGH:
                messagebox.showwarning("High Memory Usage",
                    f"{message}\n\nConsider pausing downloads or clearing cache.")
            elif level == MemoryWarningLevel.MEDIUM:
                # Just log medium warnings to avoid too many popups
                self.log_message(f"Memory usage warning: {message}")
        except Exception as e:
            print(f"Error showing memory warning: {e}")
    
    def _perform_memory_cleanup(self):
        """Perform automatic memory cleanup"""
        try:
            self.log_message("Performing automatic memory cleanup...")
            
            # Force cleanup
            cleanup_successful = memory_monitor.force_cleanup()
            
            if cleanup_successful:
                self.log_message("Memory cleanup completed successfully.")
            else:
                self.log_message("Memory cleanup encountered some issues.")

            try:
                stats = memory_monitor.get_current_stats()
            except Exception:
                stats = None
            self.after(0, lambda s=stats: self._update_memory_indicator(s))
            
        except Exception as e:
            print(f"Error during memory cleanup: {e}")
            self.log_message(f"Error during memory cleanup: {e}")
    
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
                
                # Global progress labels removed - progress is shown per-task in enhanced widgets
                # No need to update global labels anymore
                    
        except Exception as e:
            print(f"Error applying progress update: {e}")

    def _refresh_queue_summary(self):
        """Update the summary cards in the download tab."""
        if not hasattr(self, 'download_tab_component') or not self.download_tab_component:
            return

        queued = len(self._download_queue_list)
        active = sum(
            1 for task in self.download_tasks.values()
            if task.get('status_state') in ('active', 'downloading')
        )
        completed = self.queue_session_totals.get('completed', 0)
        failed = self.queue_session_totals.get('failed', 0)

        def apply_summary():
            try:
                self.download_tab_component.update_summary(queued, active, completed, failed)
            except Exception as exc:
                print(f"Warning: failed to update summary: {exc}")

        self.after(0, apply_summary)

    def _set_task_state(self, task_id, new_state):
        """Track task state transitions for summary updates."""
        task = self.download_tasks.get(task_id)
        previous = None
        if task is not None:
            previous = task.get('status_state')
            task['status_state'] = new_state

        if new_state == 'completed' and previous != 'completed':
            self.queue_session_totals['completed'] += 1
        elif new_state in ('failed', 'cancelled') and previous not in ('failed', 'cancelled'):
            self.queue_session_totals['failed'] += 1

        self._refresh_queue_summary()

    def _update_memory_indicator(self, stats):
        """Push memory statistics into the status bar."""
        if not stats or not hasattr(self, 'download_tab_component') or not self.download_tab_component:
            return

        summary = f"Memory: {stats.process_memory_mb:.0f} MB | System {stats.system_memory_percent:.0f}% used"
        try:
            self.download_tab_component.update_memory(summary, stats.warning_level.value)
        except Exception as exc:
            print(f"Warning: failed to update memory indicator: {exc}")

    def _setup_download_tab(self):
        # Configure grid layout for download tab
        self.download_tab.grid_columnconfigure(1, weight=1)
        self.download_tab.grid_rowconfigure(4, weight=1)

        # Main Input Frame with Progressive Disclosure
        self.input_frame = ctk.CTkFrame(self.download_tab)
        self.input_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.input_frame.grid_columnconfigure(1, weight=1)

        # Essential Information Section (Always Visible)
        # URL Input - Most important field, prominently displayed
        self.url_label = ctk.CTkLabel(
            self.input_frame,
            text="Download URLs:",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.url_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        self.url_entry = ctk.CTkTextbox(self.input_frame, height=80, width=400)
        self.url_entry.grid(row=0, column=1, padx=10, pady=(10, 5), sticky="nsew")
        self.url_entry.insert("1.0", "Paste Civitai URLs here (one per line)")
        
        # Quick action buttons
        quick_actions_frame = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        quick_actions_frame.grid(row=0, column=2, padx=10, pady=(10, 5), sticky="ne")
        
        self.browse_button = ctk.CTkButton(
            quick_actions_frame,
            text="ðŸ“ Load File",
            command=self.browse_txt_file,
            width=100,
            height=28
        )
        self.browse_button.grid(row=0, column=0, pady=(0, 4))
        
        self.clear_urls_button = ctk.CTkButton(
            quick_actions_frame,
            text="ðŸ—‘ Clear",
            command=self.clear_urls,
            width=100,
            height=28,
            fg_color="transparent",
            text_color=("gray40", "gray60"),
            hover_color=("gray90", "gray20")
        )
        self.clear_urls_button.grid(row=1, column=0)

        # Download Path - Essential but secondary
        self.download_path_label = ctk.CTkLabel(self.input_frame, text="Download Folder:")
        self.download_path_label.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="w")
        
        download_path_frame = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        download_path_frame.grid(row=1, column=1, columnspan=2, padx=10, pady=(5, 10), sticky="ew")
        download_path_frame.grid_columnconfigure(0, weight=1)
        
        self.download_path_entry = ctk.CTkEntry(
            download_path_frame,
            placeholder_text="Select download directory"
        )
        self.download_path_entry.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        
        self.browse_path_button = ctk.CTkButton(
            download_path_frame,
            text="Browse",
            command=self.browse_download_path,
            width=80
        )
        self.browse_path_button.grid(row=0, column=1)

        # Advanced Settings Section (Collapsible)
        self.advanced_expanded = False
        self.advanced_toggle_button = ctk.CTkButton(
            self.input_frame,
            text="â–¼ Advanced Settings",
            command=self.toggle_advanced_settings,
            width=150,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            text_color=("gray40", "gray60"),
            hover_color=("gray90", "gray20")
        )
        self.advanced_toggle_button.grid(row=2, column=0, padx=10, pady=(0, 5), sticky="w")

        # Advanced Settings Frame (Initially Hidden)
        self.advanced_frame = ctk.CTkFrame(self.input_frame, fg_color=("gray95", "gray10"))
        self.advanced_frame.grid_columnconfigure(1, weight=1)
        
        # API Key Input (Advanced Setting)
        self.api_key_label = ctk.CTkLabel(
            self.advanced_frame,
            text="API Key:",
            font=ctk.CTkFont(size=11)
        )
        self.api_key_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")
        
        self.api_key_entry = ctk.CTkEntry(
            self.advanced_frame,
            placeholder_text="Optional: Enter Civitai API Key for private models",
            show="*",
            height=28
        )
        self.api_key_entry.grid(row=0, column=1, padx=10, pady=(10, 5), sticky="ew")
        
        # Help text for API key
        self.api_help_label = ctk.CTkLabel(
            self.advanced_frame,
            text="ðŸ’¡ API key enables downloading private models and increases rate limits",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        self.api_help_label.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="w")

        # Load environment variables with smart defaults
        load_dotenv()
        self.api_key_entry.insert(0, os.getenv("CIVITAI_API_KEY", ""))
        default_path = os.getenv("DOWNLOAD_PATH", os.path.join(os.getcwd(), "downloads"))
        self.download_path_entry.insert(0, default_path)
        
        # Initially hide advanced settings
        self.advanced_frame.grid_remove()

        # Download Button
        self.download_button = ctk.CTkButton(self.download_tab, text="Start Download", command=self.start_download_thread)
        self.download_button.grid(row=1, column=0, padx=(10, 5), pady=10, sticky="ew")

        # Open Download Folder Button
        self.open_folder_button = ctk.CTkButton(self.download_tab, text="Open Downloads Folder", command=self.open_download_folder)
        self.open_folder_button.grid(row=1, column=1, padx=(5, 10), pady=10, sticky="ew")

        # Clear/Reset Button
        self.clear_button = ctk.CTkButton(self.download_tab, text="Clear/Reset GUI", command=self.clear_gui)
        self.clear_button.grid(row=8, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        # Global progress labels removed - individual task progress is shown in enhanced progress widgets


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
        try:
            if hasattr(self, 'download_tab_component') and self.download_tab_component:
                self.download_tab_component.update_status_message(message)
        except Exception:
            pass

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
            # Parse URLs using utility function
            urls = parse_urls_from_text(url_input_content)
            if not urls:
                self.log_message("No URLs provided. Exiting.")
                messagebox.showinfo("Download Info", "No URLs provided.")
                # Re-enable download button immediately if no URLs
                self.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
                return
            
            # Add each URL as a task to the queue
            for url in urls:
                # Validate URL format using utility function
                if not validate_civitai_url(url):
                    self.log_message(f"Skipping invalid URL: {url}")
                    # Pre-register task to avoid race with queue processor
                    task_id = f"task_{hash(url)}_{self.queue_row_counter}"
                    if task_id not in self.download_tasks:
                        # Minimal placeholder; UI will enrich this entry on main thread
                        self.download_tasks[task_id] = {
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
                    self.after(0, self._add_download_task_ui, task_id, url)
                    # Attempt to set status once UI is ready; guard missing label
                    def _mark_invalid(tid=task_id):
                        try:
                            if tid in self.download_tasks and self.download_tasks[tid].get('status_label'):
                                self.download_tasks[tid]['status_label'].configure(text=f"Status: Failed - Invalid URL format", text_color="red")
                        except Exception:
                            pass
                    self.after(50, _mark_invalid)
                    continue
                # Create a unique ID for each download task
                task_id = f"task_{hash(url)}_{self.queue_row_counter}"
                # Pre-register task to avoid race with queue processor thread
                if task_id not in self.download_tasks:
                    self.download_tasks[task_id] = {
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
                with self._queue_lock:
                    self._download_queue_list.append({'task_id': task_id, 'url': url, 'api_key': api_key, 'download_path': download_path})
                    self._queue_condition.notify() # Signal that a new item has been added
                # Add GUI element for the new task
                self.after(0, self._add_download_task_ui, task_id, url)
        except Exception as e:
            self.log_message(f"An unexpected error occurred while adding URLs to queue: {e}")
            messagebox.showerror("Unexpected Error", f"An unexpected error occurred while adding URLs to queue: {e}")
        finally:
            # Re-enable the download button only after all URLs are added to the queue.
            # Actual download processing happens in _process_download_queue.
            self.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
    def _add_download_task_ui(self, task_id, url):
        row = self.queue_row_counter
        self.queue_row_counter += 1
        
        # Card-based layout with improved styling and hover effects
        task_frame = ctk.CTkFrame(
            self.queue_frame,
            corner_radius=12,
            border_width=1,
            border_color=("gray80", "gray20")
        )
        task_frame.grid(row=row, column=0, padx=10, pady=8, sticky="ew")
        task_frame.grid_columnconfigure(1, weight=1)
        
        # Add hover effects for better interactivity
        def on_enter(event):
            task_frame.configure(border_color=("#2196F3", "#1976D2"))
            
        def on_leave(event):
            task_frame.configure(border_color=("gray80", "gray20"))
            
        task_frame.bind("<Enter>", on_enter)
        task_frame.bind("<Leave>", on_leave)
        
        # Header section with URL and controls
        header_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, columnspan=3, sticky="ew", padx=12, pady=(12, 8))
        header_frame.grid_columnconfigure(1, weight=1)
        
        # Task status indicator (colored dot)
        status_indicator = ctk.CTkLabel(
            header_frame,
            text="â—",
            font=ctk.CTkFont(size=16),
            text_color="#ffa500",  # Orange for initializing
            width=20
        )
        status_indicator.grid(row=0, column=0, padx=(0, 8), sticky="w")
        
        # URL display with better formatting
        url_display = (url[:60] + '...') if len(url) > 63 else url
        task_label = ctk.CTkLabel(
            header_frame,
            text=url_display,
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        task_label.grid(row=0, column=1, padx=(0, 8), sticky="ew")
        
        # Status text (secondary information)
        status_label = ctk.CTkLabel(
            header_frame,
            text="Initializing...",
            anchor="e",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        status_label.grid(row=0, column=2, sticky="e")
        
        # Progress section
        progress_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
        progress_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 8))
        progress_frame.grid_columnconfigure(0, weight=1)
        
        # Enhanced progress widget
        enhanced_progress = EnhancedProgressWidget(progress_frame, task_id)
        enhanced_progress.grid(row=0, column=0, sticky="ew")
        
        # Create progress tracker
        tracker = progress_manager.create_tracker(task_id)
        tracker.set_phase(ProgressPhase.INITIALIZING)
        # Store references to update later. If a placeholder already exists (pre-registered
        # in _add_urls_to_queue), update it instead of overwriting to avoid races.
        existing = self.download_tasks.get(task_id, {})
        
        self.download_tasks[task_id] = {
            'frame': task_frame,
            'label': task_label,
            'progress_bar': enhanced_progress.progress_bar,  # For backward compatibility
            'enhanced_progress': enhanced_progress,
            'tracker': tracker,
            'status_label': status_label,  # Now properly created
            'url': existing.get('url', url), # Preserve original URL if set
            'stop_event': existing.get('stop_event', threading.Event()), # Per-task stop event
            'pause_event': existing.get('pause_event', threading.Event()), # Per-task pause event
            'cancel_button': existing.get('cancel_button'),
            'pause_button': existing.get('pause_button'),
            'resume_button': existing.get('resume_button')
        }
        # Actions section at bottom of card
        actions_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
        actions_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 12))
        actions_frame.grid_columnconfigure(0, weight=1)
        
        # Control buttons with card-appropriate styling
        button_container = ctk.CTkFrame(actions_frame, fg_color="transparent")
        button_container.grid(row=0, column=1, sticky="e")
        
        # Primary action button (Pause/Resume toggle) - larger and more prominent
        pause_resume_button = ctk.CTkButton(
            button_container,
            text="â¸ Pause",
            command=lambda tid=task_id: self.toggle_pause_resume(tid),
            width=90,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8
        )
        pause_resume_button.grid(row=0, column=0, padx=(0, 8))
        
        # Secondary action button (Cancel) - distinctive styling
        cancel_button = ctk.CTkButton(
            button_container,
            text="âœ•",
            command=lambda tid=task_id: self.cancel_download(tid),
            width=32,
            height=32,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#f44336",
            hover_color="#d32f2f",
            corner_radius=8
        )
        cancel_button.grid(row=0, column=1, padx=(0, 8))
        
        # Context menu button for advanced actions - subtle styling
        context_button = ctk.CTkButton(
            button_container,
            text="â‹¯",
            command=lambda tid=task_id: self.show_task_context_menu(tid, button_container),
            width=32,
            height=32,
            font=ctk.CTkFont(size=16),
            fg_color="transparent",
            text_color=("gray40", "gray60"),
            hover_color=("gray90", "gray20"),
            corner_radius=8,
            border_width=1,
            border_color=("gray60", "gray40")
        )
        context_button.grid(row=0, column=2)
        
        # Update task dictionary with all references
        self.download_tasks[task_id].update({
            'header_frame': header_frame,
            'progress_frame': progress_frame,
            'actions_frame': actions_frame,
            'status_indicator': status_indicator,
            'pause_resume_button': pause_resume_button,
            'cancel_button': cancel_button,
            'context_button': context_button,
            # Legacy references for compatibility
            'pause_button': pause_resume_button,
            'resume_button': pause_resume_button
        })
    
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
            if task.get('pause_resume_button'):
                task['pause_resume_button'].configure(state="disabled", text="Cancelled")
            self._set_task_state(task_id, 'cancelled')
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
            if task.get('pause_resume_button'):
                task['pause_resume_button'].configure(text="Resume")
            self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Paused", "gray"))
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
            if task.get('pause_resume_button'):
                task['pause_resume_button'].configure(text="Pause")
            self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Downloading...", "#2196F3"))
            self.log_message(f"Resume requested for task: {task['url']}")
    
    def toggle_pause_resume(self, task_id):
        """Toggle between pause and resume for a task"""
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
            button = task.get('pause_resume_button')
            
            if not button:
                return
                
            # Check current state by examining pause event
            if task['pause_event'].is_set():  # Currently paused
                # Resume the task
                self.resume_download(task_id)
            else:  # Currently running
                # Pause the task
                self.pause_download(task_id)
    
    def show_task_context_menu(self, task_id, parent_widget):
        """Show context menu for advanced task actions"""
        import tkinter as tk
        
        # Create context menu
        context_menu = tk.Menu(self, tearoff=0)
        context_menu.add_command(
            label="Move Up",
            command=lambda: self.move_task_up(task_id)
        )
        context_menu.add_command(
            label="Move Down",
            command=lambda: self.move_task_down(task_id)
        )
        context_menu.add_separator()
        context_menu.add_command(
            label="Remove from Queue",
            command=lambda: self.cancel_download(task_id)
        )
        
        # Show menu at cursor position
        try:
            x = parent_widget.winfo_rootx()
            y = parent_widget.winfo_rooty() + parent_widget.winfo_height()
            context_menu.post(x, y)
        except:
            # Fallback if positioning fails
            context_menu.post(parent_widget.winfo_rootx(), parent_widget.winfo_rooty())
 
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
                self._refresh_queue_summary()
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

        # Wait for all background threads to complete (HTML generation and other background tasks)
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
            # Global progress labels removed - no need to reset them
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
                    self._refresh_queue_summary()
                    continue
                self._set_task_state(task_id, 'active')
                task_stop_event = self.download_tasks[task_id]['stop_event']
                
                # Handle task cancelled before processing
                if task_stop_event.is_set():
                    self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Cancelled", "red"))
                    self.log_message(f"Task {url} was cancelled before processing. Skipping.")
                    self._set_task_state(task_id, 'cancelled')
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
                        self._set_task_state(task_id, 'failed')
                        self._cleanup_task_ui(task_id)
                        continue
                    
                    # Check if model is already downloaded
                    if is_model_downloaded(model_info, download_path):
                        self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Already Downloaded"))
                        self.log_message(f"Model {model_info['model']['name']} v{model_info['name']} already downloaded. Skipping.")
                        self._set_task_state(task_id, 'completed')
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
                        self._set_task_state(task_id, 'failed')
                        self._cleanup_task_ui(task_id)
                    else:
                        # Store background thread for completion tracking
                        if bg_thread:
                            self.background_threads[task_id] = bg_thread
                        self.after_idle(lambda id=task_id: self._safe_update_status(id, "Status: Complete", "green"))
                        self.log_message(f"Download complete for {url}")
                        self._set_task_state(task_id, 'completed')
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
                task = self.download_tasks[task_id]
                status_label = task.get('status_label')
                status_indicator = task.get('status_indicator')
                
                # Update status text
                if status_label is not None:
                    if text_color:
                        status_label.configure(text=status_text, text_color=text_color)
                    else:
                        status_label.configure(text=status_text)
                else:
                    print(f"Warning: status_label is None for task {task_id}")
                
                # Update status indicator color based on status
                if status_indicator is not None:
                    indicator_color = self._get_status_indicator_color(status_text)
                    try:
                        status_indicator.configure(fg_color=indicator_color)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error updating status for task {task_id}: {e}")
    
    def _get_status_indicator_color(self, status_text):
        """Get appropriate color for status indicator based on status text"""
        status_lower = status_text.lower()
        
        if "complete" in status_lower or "downloaded" in status_lower:
            return "#4CAF50"  # Green for success
        elif "failed" in status_lower or "error" in status_lower or "cancelled" in status_lower:
            return "#f44336"  # Red for errors
        elif "downloading" in status_lower:
            return "#2196F3"  # Blue for active
        elif "paused" in status_lower:
            return "#9E9E9E"  # Gray for paused
        elif "fetching" in status_lower or "connecting" in status_lower:
            return "#ffff00"  # Yellow for connecting
        else:
            return "#ffa500"  # Orange for initializing/unknown
    
    # Note: _update_task_progress_ui method is now replaced by _apply_progress_update
    # which is called via the progress queue system for better performance
 
    def _on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit? Ongoing downloads will be interrupted."):
            self.stop_event.set() # Signal main queue processing thread to stop
            self.log_message("Shutdown initiated. Signalling individual downloads to stop...")
            
            # Stop progress processor first
            try:
                self.progress_queue.put_nowait(None)  # Poison pill to stop progress processor
            except (queue.Full, AttributeError):
                pass
            
            # Signal all individual download threads to stop and clear pause events
            active_tasks = list(self.download_tasks.items())  # Iterate over a copy as dict might change
            for task_id, task_data in active_tasks:
                try:
                    if 'stop_event' in task_data and hasattr(task_data['stop_event'], 'set'):
                        task_data['stop_event'].set()
                    if 'pause_event' in task_data and hasattr(task_data['pause_event'], 'clear'):
                        task_data['pause_event'].clear()  # Clear pause event to unblock any waiting threads
                    
                    # Update UI elements safely
                    if task_data.get('cancel_button'):
                        try:
                            task_data['cancel_button'].configure(state="disabled", text="Stopping...")
                        except:
                            pass
                    if task_data.get('pause_button'):
                        try:
                            task_data['pause_button'].configure(state="disabled")
                        except:
                            pass
                    if task_data.get('resume_button'):
                        try:
                            task_data['resume_button'].configure(state="disabled")
                        except:
                            pass
                except Exception as e:
                    print(f"Error stopping task {task_id}: {e}")

            self.log_message("Waiting for threads to finish...")
            
            # Collect all threads that need to be waited for
            threads_to_wait = []
            
            # Progress processor thread
            if hasattr(self, 'progress_thread') and self.progress_thread.is_alive():
                threads_to_wait.append(('progress_thread', self.progress_thread, 2))
            
            # Queue processor thread
            if hasattr(self, 'queue_processor_thread') and self.queue_processor_thread.is_alive():
                threads_to_wait.append(('queue_processor_thread', self.queue_processor_thread, 5))
            
            # Completion watcher thread
            if hasattr(self, 'completion_watcher_thread') and self.completion_watcher_thread.is_alive():
                threads_to_wait.append(('completion_watcher_thread', self.completion_watcher_thread, 3))
            
            # Processing and completion thread
            if hasattr(self, 'processing_and_completion_thread') and self.processing_and_completion_thread.is_alive():
                threads_to_wait.append(('processing_and_completion_thread', self.processing_and_completion_thread, 3))
            
            # Wait for all background threads with proper timeouts
            background_threads_copy = dict(self.background_threads)  # Create copy to avoid modification during iteration
            for task_id, bg_thread in background_threads_copy.items():
                if bg_thread and bg_thread.is_alive():
                    threads_to_wait.append((f'background_thread_{task_id}', bg_thread, 2))
            
            # Wait for each thread with individual timeouts
            total_wait_start = time.time()
            for thread_name, thread, timeout in threads_to_wait:
                if time.time() - total_wait_start > 15:  # Total timeout of 15 seconds
                    self.log_message("Thread cleanup timeout exceeded, forcing shutdown...")
                    break
                    
                try:
                    thread.join(timeout=timeout)
                    if thread.is_alive():
                        self.log_message(f"{thread_name} did not terminate gracefully within {timeout}s.")
                    else:
                        self.log_message(f"{thread_name} terminated successfully.")
                except Exception as e:
                    self.log_message(f"Error waiting for {thread_name}: {e}")
            
            # Clear all thread references
            self.background_threads.clear()
            
            # Clean up progress manager resources
            try:
                if hasattr(self, 'download_tasks'):
                    for task_id in list(self.download_tasks.keys()):
                        try:
                            from src.progress_tracker import progress_manager
                            progress_manager.remove_tracker(task_id)
                        except:
                            pass
            except:
                pass
            
            # Stop memory monitoring
            try:
                memory_monitor.stop_monitoring()
                self.log_message("Memory monitoring stopped.")
            except:
                pass
            
            # Thumbnail cache cleanup skipped (feature disabled).
            
            self.log_message("Thread cleanup completed. Closing application...")
            self.destroy() # Close the main window
    def clear_gui(self):
        self.url_entry.delete("1.0", ctk.END)
        # Only clear the URL entry as requested

        # Clear background threads tracking
        self.background_threads.clear()

        self.log_message("URL input cleared.")
        # Do not reset other fields or download queue display
        # As per the new requirement, "Clear GUI" only clears the current URLs.

if __name__ == "__main__":
    app = App()
    app.mainloop()
