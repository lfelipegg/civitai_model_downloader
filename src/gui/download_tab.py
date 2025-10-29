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
import uuid
import re

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
from src.civitai_downloader import get_model_info_from_url, download_civitai_model, download_file, is_model_downloaded, get_model_with_versions, get_collection_models
from src.progress_tracker import progress_manager, ProgressPhase, ProgressStats
from src.enhanced_progress_bar import EnhancedProgressWidget


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
        self.summary_labels = {}
        self.status_message_var = tk.StringVar(value="Ready")
        self.memory_message_var = tk.StringVar(value="Memory: --")
        self.download_mode_var = tk.StringVar(value="Current version only")

        self.download_tab_frame.grid_columnconfigure(0, weight=1)
        self.download_tab_frame.grid_columnconfigure(1, weight=1)

        # Input section
        self.input_frame = ctk.CTkFrame(self.download_tab_frame)
        self.input_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        self.input_frame.grid_columnconfigure(1, weight=1)

        self.url_label = ctk.CTkLabel(
            self.input_frame,
            text="Download URLs:",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.url_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

        self.url_entry = ctk.CTkTextbox(self.input_frame, height=90)
        self.url_entry.grid(row=0, column=1, padx=10, pady=(10, 5), sticky="nsew")

        quick_actions_frame = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        quick_actions_frame.grid(row=0, column=2, padx=10, pady=(10, 5), sticky="ne")
        quick_actions_frame.grid_columnconfigure(0, weight=1)

        self.paste_button = ctk.CTkButton(
            quick_actions_frame,
            text="Paste",
            command=self.paste_from_clipboard,
            width=120
        )
        self.paste_button.grid(row=0, column=0, pady=(0, 4), sticky="ew")

        self.browse_button = ctk.CTkButton(
            quick_actions_frame,
            text="Load From File",
            command=self.browse_txt_file,
            width=120
        )
        self.browse_button.grid(row=1, column=0, pady=(0, 4), sticky="ew")

        self.clear_urls_button = ctk.CTkButton(
            quick_actions_frame,
            text="Clear Input",
            command=self.clear_urls,
            width=120,
            fg_color="transparent",
            text_color=("gray40", "gray60"),
            hover_color=("gray90", "gray20")
        )
        self.clear_urls_button.grid(row=2, column=0, sticky="ew")

        # API key controls
        self.api_key_label = ctk.CTkLabel(self.input_frame, text="API Key:")
        self.api_key_label.grid(row=1, column=0, padx=10, pady=(5, 2), sticky="w")

        self.api_key_entry = ctk.CTkEntry(
            self.input_frame,
            placeholder_text="Optional: required for private models",
            show="*"
        )
        self.api_key_entry.grid(row=1, column=1, padx=10, pady=(5, 2), sticky="ew")

        self.api_hint_label = ctk.CTkLabel(
            self.input_frame,
            text="Tip: adding an API key enables private downloads and higher rate limits.",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        self.api_hint_label.grid(row=1, column=2, padx=10, pady=(5, 2), sticky="w")

        # Download path controls
        self.download_path_label = ctk.CTkLabel(self.input_frame, text="Download Folder:")
        self.download_path_label.grid(row=2, column=0, padx=10, pady=(2, 10), sticky="w")

        download_path_frame = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        download_path_frame.grid(row=2, column=1, columnspan=2, padx=10, pady=(2, 10), sticky="ew")
        download_path_frame.grid_columnconfigure(0, weight=1)

        self.download_path_entry = ctk.CTkEntry(
            download_path_frame,
            placeholder_text="Select download directory"
        )
        self.download_path_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.browse_path_button = ctk.CTkButton(
            download_path_frame,
            text="Browse",
            command=self.browse_download_path,
            width=90
        )
        self.browse_path_button.grid(row=0, column=1)

        # Download scope controls
        scope_frame = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        scope_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=(2, 10), sticky="ew")
        scope_frame.grid_columnconfigure(1, weight=1)

        self.download_scope_label = ctk.CTkLabel(scope_frame, text="Download scope:")
        self.download_scope_label.grid(row=0, column=0, padx=(0, 6), sticky="w")

        self.download_scope_menu = ctk.CTkOptionMenu(
            scope_frame,
            variable=self.download_mode_var,
            values=["Current version only", "All versions"]
        )
        self.download_scope_menu.grid(row=0, column=1, sticky="w")

        self.download_scope_hint = ctk.CTkLabel(
            scope_frame,
            text="Choose whether to download only the version referenced by each URL or every available version.",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        self.download_scope_hint.grid(row=1, column=0, columnspan=2, pady=(4, 0), sticky="w")

        # Load environment defaults
        from dotenv import load_dotenv
        load_dotenv()
        self.api_key_entry.insert(0, os.getenv("CIVITAI_API_KEY", ""))
        self.download_path_entry.insert(0, os.getenv("DOWNLOAD_PATH", os.getcwd()))

        # Primary actions
        self.download_button = ctk.CTkButton(
            self.download_tab_frame,
            text="Start Download",
            command=self.start_download_thread
        )
        self.download_button.grid(row=1, column=0, padx=(10, 5), pady=10, sticky="ew")

        self.open_folder_button = ctk.CTkButton(
            self.download_tab_frame,
            text="Open Downloads Folder",
            command=self.open_download_folder
        )
        self.open_folder_button.grid(row=1, column=1, padx=(5, 10), pady=10, sticky="ew")

        # Summary cards
        summary_frame = ctk.CTkFrame(self.download_tab_frame)
        summary_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        summary_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        for column, (key, label_text) in enumerate((
            ("queued", "Queued"),
            ("active", "Active"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        )):
            card = ctk.CTkFrame(summary_frame, corner_radius=10, fg_color=("gray94", "gray12"))
            card.grid(row=0, column=column, padx=6, pady=6, sticky="ew")
            title_label = ctk.CTkLabel(card, text=label_text, font=ctk.CTkFont(size=11))
            title_label.grid(row=0, column=0, padx=10, pady=(8, 0), sticky="w")
            value_label = ctk.CTkLabel(card, text="0", font=ctk.CTkFont(size=24, weight="bold"))
            value_label.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="w")
            self.summary_labels[key] = value_label

        # Download queue display
        self.queue_frame = ctk.CTkScrollableFrame(self.download_tab_frame, label_text="Download Queue")
        self.queue_frame.grid(row=4, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.queue_frame.grid_columnconfigure(0, weight=1)

        # Log area
        self.log_label = ctk.CTkLabel(self.download_tab_frame, text="Activity Log:")
        self.log_label.grid(row=5, column=0, padx=10, pady=(10, 0), sticky="w")
        self.log_text = ctk.CTkTextbox(self.download_tab_frame, width=600, height=200)
        self.log_text.grid(row=6, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.log_text.configure(state="disabled")

        # Status bar
        status_bar = ctk.CTkFrame(self.download_tab_frame, fg_color=("gray95", "gray10"))
        status_bar.grid(row=7, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        status_bar.grid_columnconfigure(0, weight=1)
        status_bar.grid_columnconfigure(1, weight=0)
        status_bar.grid_columnconfigure(2, weight=0)

        self.status_label = ctk.CTkLabel(status_bar, textvariable=self.status_message_var, anchor="w")
        self.status_label.grid(row=0, column=0, padx=10, pady=6, sticky="w")

        self.memory_label = ctk.CTkLabel(status_bar, textvariable=self.memory_message_var, anchor="e")
        self.memory_label.grid(row=0, column=1, padx=10, pady=6, sticky="e")

        self.clear_button = ctk.CTkButton(status_bar, text="Clear GUI", command=self.clear_gui, width=110)
        self.clear_button.grid(row=0, column=2, padx=(5, 10), pady=6, sticky="e")

        # Growth behaviour
        self.download_tab_frame.grid_rowconfigure(4, weight=2)
        self.download_tab_frame.grid_rowconfigure(6, weight=1)

        # Initialise indicators
        self.update_summary(0, 0, 0, 0)
        self.update_status_message("Ready")

    def clear_urls(self):
        """Clear only the URL input box."""
        self.url_entry.delete("1.0", ctk.END)
        self.update_status_message("URL input cleared.")

    def paste_from_clipboard(self):
        """Paste URLs from the system clipboard into the input box."""
        try:
            clipboard_text = self.download_tab_frame.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Clipboard", "No text available on the clipboard.")
            return

        if clipboard_text:
            self.url_entry.delete("1.0", ctk.END)
            self.url_entry.insert("1.0", clipboard_text.strip())
            self.update_status_message("URLs pasted from clipboard.")

    def update_summary(self, queued: int, active: int, completed: int, failed: int):
        """Update the queue summary cards."""
        if not self.summary_labels:
            return

        self.summary_labels["queued"].configure(text=str(max(queued, 0)))
        self.summary_labels["active"].configure(text=str(max(active, 0)))
        self.summary_labels["completed"].configure(text=str(max(completed, 0)))
        self.summary_labels["failed"].configure(text=str(max(failed, 0)))

    def update_memory(self, message: str, warning_level: str = "low"):
        """Update the memory indicator in the status bar."""
        level = (warning_level or "low").lower()
        color_map = {
            "critical": "#f44336",
            "high": "#fb8c00",
            "medium": "#fbc02d",
            "low": "gray60",
        }
        self.memory_message_var.set(message)
        self.memory_label.configure(text_color=color_map.get(level, "gray60"))

    def update_status_message(self, message: str):
        """Update the status bar message."""
        self.status_message_var.set(message or "")

    def browse_txt_file(self):
        """Browse for a text file containing URLs."""
        file_path = browse_text_file(self.parent_app)
        if file_path:
            with open(file_path, 'r') as f:
                content = f.read()
            self.url_entry.delete("1.0", ctk.END) # Clear existing content
            self.url_entry.insert("1.0", content) # Insert new content
            self.update_status_message(f"Loaded URLs from {os.path.basename(file_path)}.")

    def browse_download_path(self):
        """Browse for download directory."""
        dir_path = browse_directory(self.parent_app)
        if dir_path:
            self.download_path_entry.delete(0, ctk.END)
            self.download_path_entry.insert(0, dir_path)
            self.update_status_message(f"Download folder set to {dir_path}.")

    def log_message(self, message):
        """Log a message to the GUI log area."""
        # Initialize logger if not already done
        if not hasattr(self, 'logger'):
            self.logger = ThreadSafeLogger(self.log_text)
        self.logger.log_message(message)
        self.update_status_message(message)

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
        self.update_status_message("Preparing downloads...")
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
            urls = parse_urls_from_text(url_input_content)
            if not urls:
                self.log_message("No URLs provided. Exiting.")
                messagebox.showinfo("Download Info", "No URLs provided.")
                self.parent_app.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
                self.update_status_message("No URLs detected.")
                return

            download_all_versions = self.download_mode_var.get() == "All versions"

            for url in urls:
                collection_id = self._extract_collection_id(url)
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
            self.parent_app.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))

    def _queue_single_url(self, url, api_key, download_path):
        """Queue a single model version download."""
        if not validate_civitai_url(url):
            self.log_message(f"Skipping invalid URL: {url}")
            display_label = f"Invalid URL: {url}"
            task_id = self._enqueue_url_task(
                url,
                api_key,
                download_path,
                display_label=display_label,
                enqueue=False,
                initial_state='failed'
            )
            self.parent_app.after(50, lambda tid=task_id: self.parent_app._safe_update_status(
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
                self.update_status_message("Could not enumerate versions; using referenced version only.")
                return False
            model_id = str(
                version_info.get('modelId')
                or version_info.get('model', {}).get('id')
                or ""
            )
            if not model_id:
                self.log_message(f"Could not determine model ID from metadata for {url}.")
                self.update_status_message("Could not enumerate versions; using referenced version only.")
                return False

        model_data, error = get_model_with_versions(model_id, api_key)
        if error or not model_data:
            self.log_message(f"Failed to retrieve model metadata for {model_id}: {error or 'unknown error'}")
            self.update_status_message(f"Failed to enumerate versions for model {model_id}.")
            return False

        versions = model_data.get('modelVersions') or []
        if not versions:
            self.log_message(f"No versions available for model {model_id}.")
            self.update_status_message(f"No additional versions found for model {model_id}.")
            return False

        base_name = model_data.get('name') or f"Model {model_id}"
        queued = 0
        seen_version_ids = set()

        for version in versions:
            version_id = version.get('id')
            if not version_id:
                continue
            version_id = str(version_id)
            if version_id in seen_version_ids:
                continue
            seen_version_ids.add(version_id)

            version_url = self._build_version_url(url, model_id, version_id)
            version_name = version.get('name', f'Version {version_id}')
            display_label = f"{base_name} - {version_name}"

            self._enqueue_url_task(
                version_url,
                api_key,
                download_path,
                display_label=display_label
            )
            queued += 1

        if queued:
            message = f"Queued {queued} versions for {base_name}."
            self.log_message(message)
            self.update_status_message(message)
            return True

        self.log_message(f"No versions queued for model {model_id}.")
        return False

    def _queue_collection(self, original_url, collection_id, api_key, download_path):
        """Queue all models contained within a Civitai collection."""
        models, collection_name, error = get_collection_models(collection_id, api_key)
        if error or not models:
            self.log_message(f"Failed to load collection {collection_id}: {error or 'No items found.'}")
            self.update_status_message(f"Failed to queue collection {collection_id}.")
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

            version_url = self._build_version_url(original_url, model_id, version_id)
            display_label = f"{base_name} - {model.get('model_name', model_id)} - {model.get('version_name', version_id)}"

            self._enqueue_url_task(
                version_url,
                api_key,
                download_path,
                display_label=display_label
            )
            queued += 1

        if queued:
            message = f"Queued {queued} items from {base_name}."
            self.log_message(message)
            self.update_status_message(message)
            return True

        self.log_message(f"No items queued from collection {collection_id}.")
        return False

    def _enqueue_url_task(self, url, api_key, download_path, display_label=None, enqueue=True, initial_state='queued'):
        """Create or update a task entry and optionally enqueue it for processing."""
        task_id = f"task_{uuid.uuid4().hex}"
        existing = self.parent_app.download_tasks.get(task_id, {})

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
            'status_state': existing.get('status_state', 'queued'),
        }
        self.parent_app.download_tasks[task_id] = task_entry

        if enqueue:
            with self.parent_app._queue_lock:
                self.parent_app._download_queue_list.append({
                    'task_id': task_id,
                    'url': url,
                    'api_key': api_key,
                    'download_path': download_path
                })
                self.parent_app._queue_condition.notify()

        if hasattr(self.parent_app, '_set_task_state'):
            self.parent_app._set_task_state(task_id, initial_state)
        else:
            self.parent_app.download_tasks[task_id]['status_state'] = initial_state

        self.parent_app.after(0, self._add_download_task_ui, task_id, url)
        return task_id

    def _extract_model_id(self, url):
        """Extract the model ID from a Civitai URL."""
        match = re.search(r'/models/(\\d+)', url)
        return match.group(1) if match else None

    def _extract_collection_id(self, url):
        """Extract the collection ID from a Civitai URL."""
        match = re.search(r'/collections/(\\d+)', url)
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
        """Add a download task to the UI with enhanced card-based layout."""
        row = self.parent_app.queue_row_counter
        self.parent_app.queue_row_counter += 1
        
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
        status_indicator = ctk.CTkFrame(
            header_frame,
            width=12,
            height=12,
            fg_color="#ffa500",
            corner_radius=6
        )
        status_indicator.grid(row=0, column=0, padx=(0, 8), sticky="w")
        status_indicator.grid_propagate(False)
        
        # URL display with better formatting
        display_text = existing.get('display_url', existing.get('url', url))
        url_display = (display_text[:60] + '...') if len(display_text) > 63 else display_text
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
            text="Pause",
            command=lambda tid=task_id: self.parent_app.toggle_pause_resume(tid),
            width=90,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8
        )
        pause_resume_button.grid(row=0, column=0, padx=(0, 8))
        
        # Secondary action button (Cancel) - distinctive styling
        cancel_button = ctk.CTkButton(
            button_container,
            text="Cancel",
            command=lambda tid=task_id: self.parent_app.cancel_download(tid),
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
            text="...",
            command=lambda tid=task_id: self.parent_app.show_task_context_menu(tid, button_container),
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
        self.parent_app.download_tasks[task_id] = {
            'frame': task_frame,
            'header_frame': header_frame,
            'progress_frame': progress_frame,
            'actions_frame': actions_frame,
            'label': task_label,
            'status_indicator': status_indicator,
            'progress_bar': enhanced_progress.progress_bar,  # For backward compatibility
            'enhanced_progress': enhanced_progress,
            'tracker': tracker,
            'status_label': status_label,
            'display_url': display_text,
            'url': existing.get('url', url), # Preserve original URL if set
            'stop_event': existing.get('stop_event', threading.Event()), # Per-task stop event
            'pause_event': existing.get('pause_event', threading.Event()), # Per-task pause event
            'pause_resume_button': pause_resume_button,
            'cancel_button': cancel_button,
            'context_button': context_button,
            'status_state': existing.get('status_state', 'queued'),
            # Legacy references for compatibility
            'pause_button': pause_resume_button,
            'resume_button': pause_resume_button
        }

    def clear_gui(self):
        """Clear the GUI input fields."""
        self.clear_urls()
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
            # Global progress labels removed - no need to reset them


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


