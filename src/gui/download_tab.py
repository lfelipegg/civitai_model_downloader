"""
Download tab UI and queue handling.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import os
from dotenv import load_dotenv
import threading
import time
import queue
import uuid

from src.gui.utils import (
    browse_text_file,
    browse_directory,
    open_folder_cross_platform,
    ThreadSafeLogger,
    validate_path,
)
from src.progress_tracker import progress_manager, ProgressPhase
from src.enhanced_progress_bar import EnhancedProgressWidget
from src.services.downloader_service import DownloaderService
from src.services.url_service import UrlService


class DownloadTab:
    """Download tab UI and queue processing."""

    def __init__(self, root, frame, downloader_service=None, url_service=None):
        self.root = root
        self.download_tab = frame
        self.downloader_service = downloader_service or DownloaderService()
        self.url_service = url_service or UrlService()

        self._download_queue_list = []
        self._queue_lock = threading.Lock()
        self._queue_condition = threading.Condition(self._queue_lock)
        self.download_tasks = {}
        self.background_threads = {}
        self.queue_row_counter = 0
        self.stop_event = threading.Event()

        self.progress_queue = queue.Queue()
        self._start_progress_processor()

        self._setup_download_tab()

    def after(self, *args, **kwargs):
        return self.root.after(*args, **kwargs)

    def after_idle(self, *args, **kwargs):
        return self.root.after_idle(*args, **kwargs)

    def after_cancel(self, *args, **kwargs):
        return self.root.after_cancel(*args, **kwargs)

    def get_download_path(self):
        if hasattr(self, 'download_path_entry'):
            return self.download_path_entry.get().strip()
        return ""

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
    

    def browse_txt_file(self):
        file_path = browse_text_file(self.root)
        if file_path:
            with open(file_path, 'r') as f:
                content = f.read()
            self.url_entry.delete("1.0", ctk.END) # Clear existing content
            self.url_entry.insert("1.0", content) # Insert new content


    def browse_download_path(self):
        dir_path = browse_directory(self.root)
        if dir_path:
            self.download_path_entry.delete(0, ctk.END)
            self.download_path_entry.insert(0, dir_path)


    def log_message(self, message):
        # Initialize logger if not already done
        if not hasattr(self, 'logger'):
            self.logger = ThreadSafeLogger(self.log_text)
        self.logger.log_message(message)


    def update_status_message(self, message):
        self.log_message(message)
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(text=f"Status: {message}")


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


    def open_download_folder(self):
        download_path = self.download_path_entry.get()
        if not download_path or not validate_path(download_path):
            messagebox.showerror("Error", "Download path is not valid or not set.")
            return

        if not open_folder_cross_platform(download_path):
            messagebox.showerror("Error", "Could not open folder.")


    def _add_urls_to_queue(self, url_input_content, api_key, download_path):
        try:
            urls = self.url_service.parse_urls(url_input_content)
            if not urls:
                self.log_message("No URLs provided. Exiting.")
                messagebox.showinfo("Download Info", "No URLs provided.")
                self.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
                return

            download_all_versions = self.download_scope_var.get() == "All versions"

            for url in urls:
                collection_id = self.url_service.extract_collection_id(url)
                if collection_id:
                    handled = self._queue_collection(url, collection_id, api_key, download_path)
                    if handled:
                        continue
                    self.log_message(f"Failed to queue collection URL: {url}")
                    self.update_status_message(f"Unable to queue collection {collection_id}.")
                    continue

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
        if not self.url_service.validate_url(url):
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
        model_id = self.url_service.extract_model_id(url)

        if not model_id:
            version_info, error = self.downloader_service.get_model_info(url, api_key)
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

        model_data, error = self.downloader_service.get_model_versions(model_id, api_key)
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

            version_url = self.url_service.build_version_url(url, model_id, version_id)
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


    def _queue_collection(self, original_url, collection_id, api_key, download_path):
        """Queue all models contained within a Civitai collection."""
        models, collection_name, error = self.downloader_service.get_collection_models(collection_id, api_key)
        if error or not models:
            self.log_message(f"Failed to load collection {collection_id}: {error or 'No items found.'}")
            self.update_status_message(f"Failed to load collection {collection_id}.")
            return False

        base_name = collection_name or f"Collection {collection_id}"
        queued = 0
        seen = set()

        for model in models:
            model_id = model.get('model_id')
            version_id = model.get('version_id')
            if not model_id or not version_id:
                continue
            key = (model_id, version_id)
            if key in seen:
                continue
            seen.add(key)

            version_url = self.url_service.build_version_url(original_url, model_id, version_id)
            display_label = f"{base_name} - {model.get('model_name', model_id)} - {model.get('version_name', version_id)}"

            self._enqueue_url_task(
                version_url,
                api_key,
                download_path,
                display_label=display_label
            )
            queued += 1

        if queued:
            self.log_message(f"Queued {queued} items from {base_name}.")
            self.update_status_message(f"Queued {queued} items from {base_name}.")
            return True

        self.log_message(f"No items queued from collection {collection_id}.")
        return False


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
        enhanced_progress.grid(row=1, column=0, columnspan=2, padx=5, pady=(2, 0), sticky="ew")

        status_label = ctk.CTkLabel(task_frame, text="Status: Initializing...", anchor="w", font=ctk.CTkFont(size=11))
        status_label.grid(row=2, column=0, columnspan=2, padx=5, pady=(0, 2), sticky="w")
        
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
            'status_label': status_label,
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
        move_up_button = ctk.CTkButton(button_frame, text="â–²", command=lambda tid=task_id: self.move_task_up(tid), width=30)
        move_up_button.grid(row=0, column=3, padx=2, pady=0, sticky="ew")
        self.download_tasks[task_id]['move_up_button'] = move_up_button
        # Add Move Down Button
        move_down_button = ctk.CTkButton(button_frame, text="â–¼", command=lambda tid=task_id: self.move_task_down(tid), width=30)
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
                    
                    model_info, error_message = self.downloader_service.get_model_info(url, api_key)
                    if error_message:
                        self.after_idle(lambda id=task_id, msg=error_message: self._safe_update_status(id, f"Status: Failed - {msg}", "red"))
                        self.log_message(f"Error retrieving model info for {url}: {error_message}")
                        self.after_idle(lambda msg=error_message, u=url: messagebox.showerror("Download Error", f"Could not retrieve model information for URL: {u}\nError: {msg}"))
                        self._cleanup_task_ui(task_id)
                        continue
                    
                    # Check if model is already downloaded
                    if self.downloader_service.is_model_downloaded(model_info, download_path):
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
                    download_error, bg_thread = self.downloader_service.download_model(
                        model_info,
                        download_path,
                        api_key,
                        progress_callback=task_progress_callback,
                        stop_event=task_stop_event,
                        pause_event=self.download_tasks[task_id]['pause_event'],
                    )

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
            task = self.download_tasks.get(task_id)
            if not task:
                return

            status_label = task.get('status_label')
            if status_label is None:
                return

            if text_color:
                status_label.configure(text=status_text, text_color=text_color)
            else:
                status_label.configure(text=status_text)
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
            self.root.destroy() # Close the main window

    def clear_gui(self):
        self.url_entry.delete("1.0", ctk.END)
        # Only clear the URL entry as requested

        # Clear background threads tracking
        self.background_threads.clear()

        self.log_message("URL input cleared.")
        # Do not reset other fields or download queue display
        # As per the new requirement, "Clear GUI" only clears the current URLs.
    
    # History management methods
