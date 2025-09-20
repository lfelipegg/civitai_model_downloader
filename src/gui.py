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
        
        # History tab removed
        
        # Start memory monitoring
        memory_monitor.start_monitoring()
    
    def _setup_memory_monitoring(self):
        """Setup memory monitoring with warning callbacks"""
        def memory_warning_callback(stats):
            """Handle memory warnings"""
            try:
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
        existing = self.download_tasks.get(task_id, {})
        # Create status label
        status_label = ctk.CTkLabel(task_frame, text="Status: Initializing...", anchor="w")
        status_label.grid(row=2, column=0, columnspan=2, padx=5, pady=2, sticky="w")
        
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
        # Simplified Control Buttons Frame - Primary actions only
        button_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
        button_frame.grid(row=0, column=2, padx=5, pady=2, sticky="e")
        
        # Primary action button (Pause/Resume toggle)
        pause_resume_button = ctk.CTkButton(
            button_frame,
            text="⏸ Pause",
            command=lambda tid=task_id: self.toggle_pause_resume(tid),
            width=80,
            font=ctk.CTkFont(size=11)
        )
        pause_resume_button.grid(row=0, column=0, padx=2, pady=0)
        self.download_tasks[task_id]['pause_resume_button'] = pause_resume_button
        
        # Secondary action button (Cancel)
        cancel_button = ctk.CTkButton(
            button_frame,
            text="✕",
            command=lambda tid=task_id: self.cancel_download(tid),
            width=30,
            font=ctk.CTkFont(size=12),
            fg_color="#f44336",
            hover_color="#d32f2f"
        )
        cancel_button.grid(row=0, column=1, padx=2, pady=0)
        self.download_tasks[task_id]['cancel_button'] = cancel_button
        
        # Context menu button for advanced actions (move up/down)
        context_button = ctk.CTkButton(
            button_frame,
            text="⋯",
            command=lambda tid=task_id: self.show_task_context_menu(tid, button_frame),
            width=30,
            font=ctk.CTkFont(size=14)
        )
        context_button.grid(row=0, column=2, padx=2, pady=0)
        self.download_tasks[task_id]['context_button'] = context_button
        
        # Store legacy button references for compatibility (but they're combined now)
        self.download_tasks[task_id]['pause_button'] = pause_resume_button
        self.download_tasks[task_id]['resume_button'] = pause_resume_button  # Same button
    
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
                button.configure(text="⏸ Pause")
            else:  # Currently running
                # Pause the task
                self.pause_download(task_id)
                button.configure(text="▶ Resume")
    
    def show_task_context_menu(self, task_id, parent_widget):
        """Show context menu for advanced task actions"""
        import tkinter as tk
        
        # Create context menu
        context_menu = tk.Menu(self, tearoff=0)
        context_menu.add_command(
            label="Move Up ▲",
            command=lambda: self.move_task_up(task_id)
        )
        context_menu.add_command(
            label="Move Down ▼",
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
                status_label = self.download_tasks[task_id].get('status_label')
                if status_label is not None:
                    if text_color:
                        status_label.configure(text=status_text, text_color=text_color)
                    else:
                        status_label.configure(text=status_text)
                else:
                    print(f"Warning: status_label is None for task {task_id}")
        except Exception as e:
            print(f"Error updating status for task {task_id}: {e}")
    
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
