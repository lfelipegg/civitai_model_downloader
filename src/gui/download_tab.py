"""
Download tab UI and queue handling.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import os
import shutil
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
from src.services.downloader_service import DownloaderService
from src.services.url_service import UrlService


class DownloadTab:
    """Download tab UI and queue processing."""

    TASK_STATE_STYLES = {
        'queued': {'label': 'Queued', 'fg_color': '#6b7280', 'text_color': 'white'},
        'downloading': {'label': 'Downloading', 'fg_color': '#2563eb', 'text_color': 'white'},
        'paused': {'label': 'Paused', 'fg_color': '#f59e0b', 'text_color': 'black'},
        'failed': {'label': 'Failed', 'fg_color': '#dc2626', 'text_color': 'white'},
        'complete': {'label': 'Complete', 'fg_color': '#16a34a', 'text_color': 'white'},
        'cancelled': {'label': 'Cancelled', 'fg_color': '#b91c1c', 'text_color': 'white'},
    }
    TASK_PROGRESS_COLORS = {
        'queued': '#6b7280',
        'downloading': '#2563eb',
        'paused': '#f59e0b',
        'failed': '#dc2626',
        'complete': '#16a34a',
        'cancelled': '#b91c1c',
    }
    ACTIVE_STATES = {'queued', 'downloading', 'paused'}
    RETRY_BACKOFF_BASE_SECONDS = 2
    RETRY_BACKOFF_MAX_SECONDS = 60
    SLOW_PHASE_CONFIG = {
        'model_info_fetch': {
            'threshold': 5.0,
            'state': 'queued',
            'message': 'Metadata fetch taking longer than usual',
        },
        'model_download': {
            'threshold': 60.0,
            'state': 'downloading',
            'message': 'Model download taking longer than usual',
        },
        'asset_download': {
            'threshold': 20.0,
            'state': 'downloading',
            'message': 'Asset download taking longer than usual',
        },
    }
    PHASE_LOG_LABELS = {
        'model_info_fetch': 'Model info fetch',
        'model_download': 'Model download',
        'asset_download': 'Asset download',
        'html_report': 'HTML report generation',
    }

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
        self.queue_row_offset = 1
        self._task_display_order = []
        self.stop_event = threading.Event()
        self.queue_processor_threads = []
        self._current_max_parallel = 1
        self._current_retry_count = 2
        self._current_bandwidth_limit_bps = None

        self.progress_queue = queue.Queue(maxsize=200)
        self._progress_batch = {}
        self._progress_batch_lock = threading.Lock()
        self._progress_flush_interval_ms = 150
        self._progress_flush_job = None

        self._queue_reorder_job = None
        self._queue_state_job = None
        self._queue_cleanup_job = None
        self._queue_ui_debounce_ms = 120
        self._pending_task_cleanup = set()
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
                        task_id = update_data.get('task_id')
                        if task_id:
                            with self._progress_batch_lock:
                                self._progress_batch[task_id] = update_data
                        self.progress_queue.task_done()
                    except queue.Empty:
                        continue
            except Exception as e:
                print(f"Progress processor error: {e}")
        
        # Start progress processor thread
        self.progress_thread = threading.Thread(target=process_progress_updates, daemon=True)
        self.progress_thread.start()
        self._progress_flush_job = self.after(self._progress_flush_interval_ms, self._flush_progress_updates)


    def _flush_progress_updates(self):
        if self.stop_event.is_set():
            self._progress_flush_job = None
            return

        with self._progress_batch_lock:
            if not self._progress_batch:
                self._progress_flush_job = self.after(self._progress_flush_interval_ms, self._flush_progress_updates)
                return
            batch = self._progress_batch
            self._progress_batch = {}

        self._apply_progress_updates_batch(batch)
        self._progress_flush_job = self.after(self._progress_flush_interval_ms, self._flush_progress_updates)


    def _apply_progress_updates_batch(self, batch):
        global_update = None
        global_timestamp = -1

        for update_data in batch.values():
            task_id = update_data.get('task_id')
            task = self.download_tasks.get(task_id)
            if not task:
                continue
            pause_event = task.get('pause_event')
            if pause_event and pause_event.is_set():
                continue
            if task.get('status_state') != 'downloading':
                continue
            timestamp = update_data.get('timestamp', 0)
            if timestamp >= global_timestamp:
                global_timestamp = timestamp
                global_update = update_data

        for update_data in batch.values():
            self._apply_progress_update(update_data, update_global=(update_data is global_update))
    

    def _apply_progress_update(self, update_data, update_global=True):
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
                
                tracker = task.get('tracker')
                if tracker:
                    tracker.set_phase(ProgressPhase.DOWNLOADING)
                    stats = tracker.update_progress(bytes_downloaded, total_size)

                    progress_bar = task.get('progress_bar')
                    if progress_bar:
                        progress_bar.set(stats.percentage / 100)

                    formatted_stats = tracker.get_formatted_stats()
                    eta_label = task.get('eta_label')
                    if eta_label:
                        eta_label.configure(text=f"ETA: {formatted_stats.get('eta', 'Unknown')}")

                    if update_global:
                        self.speed_label.configure(text=f"Speed: {formatted_stats.get('current_speed', '0 B/s')}")
                        self.remaining_label.configure(text=f"ETA: {formatted_stats.get('eta', 'Unknown')}")
                else:
                    progress_bar = task.get('progress_bar')
                    if progress_bar:
                        if total_size > 0:
                            progress_percent = (bytes_downloaded / total_size) * 100
                            progress_bar.set(progress_percent / 100)
                        else:
                            progress_bar.set(0)

                    if speed > 0 and total_size > 0:
                        remaining_bytes = total_size - bytes_downloaded
                        remaining_time_sec = remaining_bytes / speed
                        mins, secs = divmod(remaining_time_sec, 60)
                        eta_text = f"{int(mins)}m {int(secs)}s"
                        eta_label = task.get('eta_label')
                        if eta_label:
                            eta_label.configure(text=f"ETA: {eta_text}")
                    else:
                        eta_label = task.get('eta_label')
                        if eta_label:
                            eta_label.configure(text="ETA: Calculating...")

                    if update_global:
                        if speed > 0 and total_size > 0:
                            self.remaining_label.configure(text=f"ETA: {eta_text}")
                        else:
                            self.remaining_label.configure(text="ETA: Calculating...")
                        self.speed_label.configure(text=f"Speed: {speed / 1024:.2f} KB/s")
                    
        except Exception as e:
            print(f"Error applying progress update: {e}")


    def _setup_download_tab(self):
        # Configure grid layout for download tab
        self.download_tab.grid_columnconfigure(1, weight=1)
        self.download_tab.grid_rowconfigure(6, weight=1)

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

        settings_frame = ctk.CTkFrame(self.input_frame, fg_color="transparent")
        settings_frame.grid(row=4, column=0, columnspan=3, padx=10, pady=(0, 10), sticky="ew")
        settings_frame.grid_columnconfigure(1, weight=0)
        settings_frame.grid_columnconfigure(3, weight=0)
        settings_frame.grid_columnconfigure(5, weight=1)

        max_parallel_label = ctk.CTkLabel(settings_frame, text="Max parallel:")
        max_parallel_label.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.max_parallel_entry = ctk.CTkEntry(settings_frame, width=60)
        self.max_parallel_entry.grid(row=0, column=1, sticky="w")

        retry_label = ctk.CTkLabel(settings_frame, text="Retry count:")
        retry_label.grid(row=0, column=2, sticky="w", padx=(12, 6))
        self.retry_count_entry = ctk.CTkEntry(settings_frame, width=60)
        self.retry_count_entry.grid(row=0, column=3, sticky="w")

        bandwidth_label = ctk.CTkLabel(settings_frame, text="Bandwidth KB/s:")
        bandwidth_label.grid(row=0, column=4, sticky="w", padx=(12, 6))
        self.bandwidth_limit_entry = ctk.CTkEntry(settings_frame, width=100, placeholder_text="0 = unlimited")
        self.bandwidth_limit_entry.grid(row=0, column=5, sticky="w")

        # Load environment variables
        load_dotenv()
        self.api_key_entry.insert(0, os.getenv("CIVITAI_API_KEY", ""))
        self.download_path_entry.insert(0, os.getenv("DOWNLOAD_PATH", os.getcwd()))
        self._current_max_parallel = self._read_env_int("MAX_PARALLEL_DOWNLOADS", 1, min_value=1, max_value=16)
        self._current_retry_count = self._read_env_int("DOWNLOAD_RETRY_COUNT", 2, min_value=0, max_value=10)
        bandwidth_default = self._read_env_float("BANDWIDTH_LIMIT_KBPS", 0, min_value=0)
        self._current_bandwidth_limit_bps = self._parse_bandwidth_kbps(bandwidth_default)
        self.max_parallel_entry.insert(0, str(self._current_max_parallel))
        self.retry_count_entry.insert(0, str(self._current_retry_count))
        if bandwidth_default:
            self.bandwidth_limit_entry.insert(0, str(bandwidth_default))

        # Download Button
        self.download_button = ctk.CTkButton(self.download_tab, text="Start Download", command=self.start_download_thread)
        self.download_button.grid(row=1, column=0, padx=(10, 5), pady=10, sticky="ew")

        # Open Download Folder Button
        self.open_folder_button = ctk.CTkButton(self.download_tab, text="Open Downloads Folder", command=self.open_download_folder)
        self.open_folder_button.grid(row=1, column=1, padx=(5, 10), pady=10, sticky="ew")

        # Download Stats Labels
        self.progress_label = ctk.CTkLabel(self.download_tab, text="Status: N/A")
        self.progress_label.grid(row=2, column=0, columnspan=2, padx=10, pady=(10, 0), sticky="w")
        self.speed_label = ctk.CTkLabel(self.download_tab, text="Speed: N/A")
        self.speed_label.grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 0), sticky="w")
        self.remaining_label = ctk.CTkLabel(self.download_tab, text="ETA: N/A")
        self.remaining_label.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")

        # Queue Actions
        self.queue_actions_frame = ctk.CTkFrame(self.download_tab, fg_color="transparent")
        self.queue_actions_frame.grid(row=5, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="ew")
        for i in range(4):
            self.queue_actions_frame.grid_columnconfigure(i, weight=0)
        self.queue_actions_frame.grid_columnconfigure(4, weight=1)

        action_width = 120
        action_height = 26
        self.pause_all_button = ctk.CTkButton(
            self.queue_actions_frame,
            text="Pause all",
            width=action_width,
            height=action_height,
            command=self.pause_all_downloads
        )
        self.pause_all_button.grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.resume_all_button = ctk.CTkButton(
            self.queue_actions_frame,
            text="Resume all",
            width=action_width,
            height=action_height,
            command=self.resume_all_downloads
        )
        self.resume_all_button.grid(row=0, column=1, padx=(0, 6), sticky="w")
        self.cancel_all_button = ctk.CTkButton(
            self.queue_actions_frame,
            text="Cancel all",
            width=action_width,
            height=action_height,
            command=self.cancel_all_downloads
        )
        self.cancel_all_button.grid(row=0, column=2, padx=(0, 6), sticky="w")
        self.clear_completed_button = ctk.CTkButton(
            self.queue_actions_frame,
            text="Clear completed",
            width=action_width,
            height=action_height,
            command=self.clear_completed_tasks
        )
        self.clear_completed_button.grid(row=0, column=3, padx=(0, 6), sticky="w")

        # Download Queue Display
        self.queue_frame = ctk.CTkScrollableFrame(self.download_tab, label_text="Download Queue")
        self.queue_frame.grid(row=6, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.queue_frame.grid_columnconfigure(0, weight=1)

        # Empty state
        self.empty_state_frame = ctk.CTkFrame(self.queue_frame, fg_color="transparent")
        self.empty_state_frame.grid(row=0, column=0, padx=10, pady=20, sticky="nsew")
        self.empty_state_frame.grid_columnconfigure(0, weight=1)

        self.empty_state_label = ctk.CTkLabel(
            self.empty_state_frame,
            text="No active downloads",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.empty_state_label.grid(row=0, column=0, pady=(0, 4))
        self.empty_state_hint = ctk.CTkLabel(
            self.empty_state_frame,
            text="Add URLs above to start a download.",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        self.empty_state_hint.grid(row=1, column=0)

        # Log Area
        self.log_label = ctk.CTkLabel(self.download_tab, text="Logs:")
        self.log_label.grid(row=7, column=0, padx=10, pady=(10, 0), sticky="w")
        self.log_text = ctk.CTkTextbox(self.download_tab, width=600, height=200)
        self.log_text.grid(row=8, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.log_text.configure(state="disabled") # Make it read-only

        # Clear/Reset Button
        self.clear_button = ctk.CTkButton(self.download_tab, text="Clear/Reset GUI", command=self.clear_gui)
        self.clear_button.grid(row=9, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        # Configure grid layout to expand queue and log area
        self.download_tab.grid_rowconfigure(6, weight=2) # Queue frame
        self.download_tab.grid_rowconfigure(8, weight=1) # Log area

        self._refresh_queue_ui_state()
    

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

    def _truncate_text(self, text, max_length):
        if not text:
            return ""
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."

    def _read_env_int(self, name, default, min_value=None, max_value=None):
        raw_value = os.getenv(name)
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return default
        if min_value is not None:
            parsed = max(min_value, parsed)
        if max_value is not None:
            parsed = min(max_value, parsed)
        return parsed

    def _read_env_float(self, name, default, min_value=None, max_value=None):
        raw_value = os.getenv(name)
        try:
            parsed = float(raw_value)
        except (TypeError, ValueError):
            return default
        if min_value is not None:
            parsed = max(min_value, parsed)
        if max_value is not None:
            parsed = min(max_value, parsed)
        return parsed

    def _parse_int_entry(self, entry, default, min_value=None, max_value=None):
        if not entry:
            return default
        raw_value = entry.get().strip()
        try:
            parsed = int(raw_value)
        except ValueError:
            return default
        if min_value is not None:
            parsed = max(min_value, parsed)
        if max_value is not None:
            parsed = min(max_value, parsed)
        return parsed

    def _parse_bandwidth_kbps(self, raw_value):
        if raw_value is None:
            return None
        value = str(raw_value).strip()
        if not value:
            return None
        try:
            parsed = float(value)
        except ValueError:
            return None
        if parsed <= 0:
            return None
        return int(parsed * 1024)

    def _format_bytes(self, size_bytes):
        if size_bytes is None:
            return "Unknown"
        size = float(size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def _format_duration(self, seconds):
        if seconds is None:
            return "Unknown"
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return "Unknown"
        if value < 0:
            value = 0
        return f"{value:.2f}s"

    def _schedule_slow_phase_warning(self, task_id, phase_key):
        config = self.SLOW_PHASE_CONFIG.get(phase_key)
        if not config:
            return
        task = self.download_tasks.get(task_id)
        if not task:
            return

        threshold_ms = int(config['threshold'] * 1000)

        def warn_if_slow():
            task_data = self.download_tasks.get(task_id)
            if not task_data:
                return
            if task_data.get('active_phase') != phase_key:
                return
            if task_data.get('status_state') != config['state']:
                return
            self._set_task_state(task_id, config['state'], detail=config['message'])

        slow_jobs = task.setdefault('slow_phase_jobs', {})
        existing_job = slow_jobs.get(phase_key)
        if existing_job is not None:
            try:
                self.after_cancel(existing_job)
            except Exception:
                pass
        slow_jobs[phase_key] = self.after(threshold_ms, warn_if_slow)

    def _cancel_slow_phase_warning(self, task_id, phase_key):
        task = self.download_tasks.get(task_id)
        if not task:
            return
        slow_jobs = task.get('slow_phase_jobs') or {}
        job = slow_jobs.pop(phase_key, None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass

    def _begin_task_phase(self, task_id, phase_key):
        task = self.download_tasks.get(task_id)
        if not task:
            return
        task['active_phase'] = phase_key
        self._schedule_slow_phase_warning(task_id, phase_key)

    def _end_task_phase(self, task_id, phase_key, duration=None, event_data=None):
        self._cancel_slow_phase_warning(task_id, phase_key)
        task = self.download_tasks.get(task_id)
        if not task:
            return
        if task.get('active_phase') == phase_key:
            task['active_phase'] = None

        config = self.SLOW_PHASE_CONFIG.get(phase_key)
        if (
            config
            and task.get('detail_text') == config.get('message')
            and task.get('status_state') == config.get('state')
        ):
            self._set_task_state(task_id, config['state'], detail=None)

        if duration is None:
            return

        phase_label = self.PHASE_LOG_LABELS.get(phase_key, phase_key.replace('_', ' ').title())
        duration_text = self._format_duration(duration)
        target_label = task.get('display_url') or task.get('url') or task_id

        details = ""
        data = event_data or {}
        assets_total = data.get('assets_total')
        assets_downloaded = data.get('assets_downloaded')
        if assets_total is not None:
            if assets_total == 0:
                details = " (no assets)"
            else:
                details = f" ({assets_downloaded}/{assets_total} assets)"

        error_message = data.get('error')
        if error_message:
            self.log_message(
                f"{phase_label} took {duration_text} before failing for {target_label}{details}."
            )
        else:
            self.log_message(
                f"{phase_label} completed in {duration_text} for {target_label}{details}."
            )

    def _handle_phase_event(self, task_id, event, phase, data=None):
        if event == "start":
            self._begin_task_phase(task_id, phase)
        elif event == "end":
            duration = None
            if data:
                duration = data.get('duration')
            self._end_task_phase(task_id, phase, duration=duration, event_data=data)

    def _sync_download_settings(self):
        self._current_max_parallel = self._parse_int_entry(
            self.max_parallel_entry,
            default=self._current_max_parallel or 1,
            min_value=1,
            max_value=16
        )
        self._current_retry_count = self._parse_int_entry(
            self.retry_count_entry,
            default=self._current_retry_count,
            min_value=0,
            max_value=10
        )
        bandwidth_kbps = None
        if hasattr(self, 'bandwidth_limit_entry'):
            bandwidth_kbps = self.bandwidth_limit_entry.get().strip()
        self._current_bandwidth_limit_bps = self._parse_bandwidth_kbps(bandwidth_kbps)

    def _get_task_bandwidth_limit(self, task_id):
        task = self.download_tasks.get(task_id)
        if not task:
            return self._current_bandwidth_limit_bps
        task_limit = task.get('bandwidth_limit_bps')
        if task_limit is not None:
            return task_limit
        return self._current_bandwidth_limit_bps

    def _calculate_backoff_delay(self, attempt):
        delay = self.RETRY_BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1))
        return min(delay, self.RETRY_BACKOFF_MAX_SECONDS)

    def _is_retryable_error(self, error_message):
        if not error_message:
            return False
        lowered = str(error_message).lower()
        if "insufficient disk space" in lowered:
            return False
        if "already downloaded" in lowered:
            return False
        if "invalid url" in lowered:
            return False
        if "interrupted by user" in lowered:
            return False
        return True

    def _wait_for_retry(self, delay_seconds, stop_event, pause_event=None):
        end_time = time.time() + delay_seconds
        while time.time() < end_time:
            if stop_event and stop_event.is_set():
                return False
            if pause_event and pause_event.is_set():
                time.sleep(0.2)
                continue
            time.sleep(0.2)
        return True

    def _run_on_ui_thread(self, func):
        done = threading.Event()
        result = {"value": None}

        def wrapper():
            result["value"] = func()
            done.set()

        self.after(0, wrapper)
        done.wait()
        return result["value"]

    def _ask_ok_cancel(self, title, message):
        return self._run_on_ui_thread(lambda: messagebox.askokcancel(title, message))

    def _get_model_size_bytes(self, model_info):
        if not model_info:
            return None
        for file_info in model_info.get('files', []):
            if file_info.get('type') == 'Model':
                size_kb = file_info.get('sizeKB')
                if size_kb:
                    return int(size_kb * 1024)
        return None

    def _precheck_disk_space_summary(self):
        with self._queue_lock:
            queued_tasks = list(self._download_queue_list)
        if not queued_tasks:
            return True

        download_path = queued_tasks[0].get('download_path') if queued_tasks else ""
        if not download_path:
            return True

        try:
            _, _, free_bytes = shutil.disk_usage(download_path)
        except Exception as e:
            self.log_message(f"Disk space check skipped: {e}")
            return True

        required_bytes = 0
        known_count = 0
        unknown_count = 0

        for task in queued_tasks:
            task_id = task.get('task_id')
            url = task.get('url')
            api_key = task.get('api_key')
            model_info = None

            if task_id in self.download_tasks:
                model_info = self.download_tasks[task_id].get('model_info')

            if not model_info:
                model_info, error = self.downloader_service.get_model_info(url, api_key)
                if error or not model_info:
                    unknown_count += 1
                    continue
                if task_id in self.download_tasks:
                    self.download_tasks[task_id]['model_info'] = model_info

            size_bytes = self._get_model_size_bytes(model_info)
            if size_bytes:
                required_bytes += size_bytes
                known_count += 1
                if task_id in self.download_tasks:
                    self.download_tasks[task_id]['model_size_bytes'] = size_bytes
            else:
                unknown_count += 1

        summary = (
            "Disk space check: "
            f"{len(queued_tasks)} tasks, "
            f"{known_count} sized, "
            f"{unknown_count} unknown. "
            f"Required: {self._format_bytes(required_bytes)}, "
            f"Available: {self._format_bytes(free_bytes)}."
        )
        self.log_message(summary)
        if hasattr(self, 'progress_label'):
            self.after(0, lambda: self.progress_label.configure(text=f"Status: {summary}"))

        if required_bytes > free_bytes:
            message = (
                f"{summary}\n\n"
                "There may not be enough disk space for this batch.\n"
                "Continue anyway?"
            )
            return self._ask_ok_cancel("Low Disk Space", message)

        return True

    def _get_display_order(self):
        with self._queue_lock:
            queued_ids = [
                item['task_id']
                for item in self._download_queue_list
                if item['task_id'] in self.download_tasks
            ]
        queued_set = set(queued_ids)
        active_ids = []
        finished_ids = []

        for task_id in self._task_display_order:
            task = self.download_tasks.get(task_id)
            if not task:
                continue
            state = task.get('status_state')
            if state in {'downloading', 'paused'}:
                if task_id not in active_ids and task_id not in queued_set:
                    active_ids.append(task_id)
            elif state == 'queued':
                if task_id not in queued_set and task_id not in active_ids:
                    active_ids.append(task_id)
                continue
            else:
                if task_id not in finished_ids:
                    finished_ids.append(task_id)

        return active_ids + queued_ids + finished_ids

    def _refresh_queue_ui_state(self):
        if not hasattr(self, 'queue_actions_frame'):
            return

        has_tasks = bool(self.download_tasks)
        has_active = any(
            task.get('status_state') in self.ACTIVE_STATES
            for task in self.download_tasks.values()
        )
        has_pauseable = any(
            task.get('status_state') in {'queued', 'downloading'}
            for task in self.download_tasks.values()
        )
        has_paused = any(
            task.get('status_state') == 'paused'
            for task in self.download_tasks.values()
        )
        has_completed = any(
            task.get('status_state') in {'complete', 'failed', 'cancelled'}
            for task in self.download_tasks.values()
        )

        if hasattr(self, 'empty_state_frame'):
            if has_tasks:
                self.empty_state_frame.grid_remove()
            else:
                self.empty_state_frame.grid()

        self.pause_all_button.configure(state="normal" if has_pauseable else "disabled")
        self.resume_all_button.configure(state="normal" if has_paused else "disabled")
        self.cancel_all_button.configure(state="normal" if has_active else "disabled")
        self.clear_completed_button.configure(state="normal" if has_completed else "disabled")

    def _schedule_queue_ui_order(self):
        if self._queue_reorder_job is not None:
            self.after_cancel(self._queue_reorder_job)
        self._queue_reorder_job = self.after(self._queue_ui_debounce_ms, self._apply_queue_ui_order)

    def _apply_queue_ui_order(self):
        self._queue_reorder_job = None
        self.__update_queue_ui_order_internal()

    def _schedule_queue_state_refresh(self):
        if not hasattr(self, 'queue_actions_frame'):
            return
        if self._queue_state_job is not None:
            self.after_cancel(self._queue_state_job)
        self._queue_state_job = self.after(self._queue_ui_debounce_ms, self._apply_queue_state_refresh)

    def _apply_queue_state_refresh(self):
        self._queue_state_job = None
        self._refresh_queue_ui_state()

    def _set_task_state(self, task_id, state, detail=None):
        task = self.download_tasks.get(task_id)
        if not task:
            return

        previous_state = task.get('status_state')
        if state not in self.TASK_STATE_STYLES:
            state = 'queued'
        previous_detail = task.get('detail_text')
        if state == previous_state and detail == previous_detail:
            return
        task['status_state'] = state
        task['detail_text'] = detail

        tracker = task.get('tracker')
        if tracker:
            if state == 'complete':
                tracker.complete()
            elif state == 'failed':
                tracker.fail()
            elif state == 'paused':
                tracker.pause()
            elif state == 'downloading':
                tracker.resume()
            elif state == 'cancelled':
                tracker.cancel()
            elif state == 'queued':
                tracker.set_phase(ProgressPhase.INITIALIZING)

        style = self.TASK_STATE_STYLES[state]
        status_chip = task.get('status_chip')
        if status_chip:
            status_chip.configure(
                text=style['label'],
                fg_color=style['fg_color'],
                text_color=style['text_color']
            )

        detail_label = task.get('detail_label')
        detail_text = task.get('detail_text')
        if detail_label:
            if detail_text:
                detail_label.configure(text=detail_text)
                detail_label.grid()
            else:
                detail_label.grid_remove()

        progress_bar = task.get('progress_bar')
        if progress_bar:
            progress_color = self.TASK_PROGRESS_COLORS.get(state)
            if progress_color:
                progress_bar.configure(progress_color=progress_color)
            if state == 'complete':
                progress_bar.set(1)
            elif state == 'queued':
                progress_bar.set(0)

        eta_label = task.get('eta_label')
        if eta_label:
            if state == 'paused':
                eta_label.configure(text="ETA: Paused")
            elif state in {'failed', 'cancelled'}:
                eta_label.configure(text="ETA: --")
            elif state == 'complete':
                eta_label.configure(text="ETA: Done")
            elif state == 'queued':
                eta_label.configure(text="ETA: Pending")

        pause_button = task.get('pause_button')
        resume_button = task.get('resume_button')
        cancel_button = task.get('cancel_button')
        move_up_button = task.get('move_up_button')
        move_down_button = task.get('move_down_button')

        if state in {'failed', 'complete', 'cancelled'}:
            for button in (pause_button, resume_button, cancel_button, move_up_button, move_down_button):
                if button:
                    button.configure(state="disabled")
        else:
            if move_up_button:
                move_up_button.configure(state="normal" if state == 'queued' else "disabled")
            if move_down_button:
                move_down_button.configure(state="normal" if state == 'queued' else "disabled")
            if state == 'paused':
                if pause_button:
                    pause_button.configure(state="disabled")
                if resume_button:
                    resume_button.configure(state="normal")
            else:
                if pause_button:
                    pause_button.configure(state="normal")
                if resume_button:
                    resume_button.configure(state="disabled")
            if cancel_button:
                cancel_button.configure(state="normal")

        if previous_state != state:
            self._schedule_queue_ui_order()
        self._schedule_queue_state_refresh()

    def pause_all_downloads(self):
        for task_id, task in list(self.download_tasks.items()):
            if task.get('status_state') in {'queued', 'downloading'}:
                self.pause_download(task_id)
        self._schedule_queue_state_refresh()

    def resume_all_downloads(self):
        for task_id, task in list(self.download_tasks.items()):
            if task.get('status_state') == 'paused':
                self.resume_download(task_id)
        self._schedule_queue_state_refresh()

    def cancel_all_downloads(self):
        for task_id, task in list(self.download_tasks.items()):
            if task.get('status_state') in {'queued', 'downloading', 'paused'}:
                self.cancel_download(task_id)
        self._schedule_queue_state_refresh()

    def clear_completed_tasks(self):
        completed_ids = [
            task_id
            for task_id, task in self.download_tasks.items()
            if task.get('status_state') in {'complete', 'failed', 'cancelled'}
        ]
        for task_id in completed_ids:
            self._cleanup_task_ui(task_id)
        self._schedule_queue_state_refresh()


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

        self._sync_download_settings()

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

        if not self._precheck_disk_space_summary():
            self.log_message("Download batch cancelled after disk space check.")
            self._cancel_pending_queue_tasks("Cancelled: insufficient disk space")
            return

        self._start_queue_workers()
        
        # This thread will wait for all tasks to be done and then re-enable the button
        # It should not be daemonized if we want to join it gracefully
        self.completion_watcher_thread = threading.Thread(target=self._watch_completion, args=(self.processing_and_completion_thread,), daemon=True)
        self.completion_watcher_thread.start()

        # The _initiate_download_process now just adds URLs and starts the queue processor.
        # The completion logic is moved to _watch_completion.
        # Removed premature completion messages from here.

    def _start_queue_workers(self):
        self.queue_processor_threads = [t for t in self.queue_processor_threads if t.is_alive()]
        target_workers = max(1, self._current_max_parallel)
        existing = len(self.queue_processor_threads)
        if existing >= target_workers:
            return

        for i in range(target_workers - existing):
            worker = threading.Thread(
                target=self._process_download_queue,
                daemon=True,
                name=f"queue_worker_{existing + i + 1}"
            )
            worker.start()
            self.queue_processor_threads.append(worker)

    def _cancel_pending_queue_tasks(self, reason):
        with self._queue_lock:
            queued_ids = [item.get('task_id') for item in self._download_queue_list]
            self._download_queue_list.clear()
        for task_id in queued_ids:
            if task_id in self.download_tasks:
                self.after_idle(lambda id=task_id: self._safe_update_status(id, "cancelled", reason))
        self._schedule_queue_ui_order()
        self._schedule_queue_state_refresh()


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
                "failed",
                "Invalid URL format"
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
            'eta_label': existing.get('eta_label'),
            'tracker': existing.get('tracker'),
            'status_chip': existing.get('status_chip'),
            'primary_label': existing.get('primary_label'),
            'secondary_label': existing.get('secondary_label'),
            'detail_label': existing.get('detail_label'),
            'cancel_button': existing.get('cancel_button'),
            'pause_button': existing.get('pause_button'),
            'resume_button': existing.get('resume_button'),
            'pause_resume_button': existing.get('pause_resume_button'),
            'context_button': existing.get('context_button'),
            'status_indicator': existing.get('status_indicator'),
            'status_state': initial_state,
            'detail_text': existing.get('detail_text'),
            'retry_count': existing.get('retry_count', self._current_retry_count),
            'bandwidth_limit_bps': existing.get('bandwidth_limit_bps'),
            'model_info': existing.get('model_info'),
            'model_size_bytes': existing.get('model_size_bytes'),
            'active_phase': existing.get('active_phase'),
            'slow_phase_jobs': existing.get('slow_phase_jobs', {})
        }
        self.download_tasks[task_id] = task_entry
        if task_id not in self._task_display_order:
            self._task_display_order.append(task_id)

        if enqueue:
            with self._queue_lock:
                self._download_queue_list.append({
                    'task_id': task_id,
                    'url': url,
                    'api_key': api_key,
                    'download_path': download_path
                })
                self._queue_condition.notify_all()

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
        row = self.queue_row_offset + self.queue_row_counter
        self.queue_row_counter += 1
        task_frame = ctk.CTkFrame(self.queue_frame)
        task_frame.grid(row=row, column=0, padx=6, pady=6, sticky="ew")
        task_frame.grid_columnconfigure(0, weight=1)

        existing = self.download_tasks.get(task_id, {})
        display_text = existing.get('display_url', existing.get('url', url))
        primary_text = self._truncate_text(display_text, 60)
        secondary_text = self._truncate_text(existing.get('url', url), 80)
        state = existing.get('status_state', 'queued')
        style = self.TASK_STATE_STYLES.get(state, self.TASK_STATE_STYLES['queued'])

        content_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
        content_frame.grid(row=0, column=0, padx=8, pady=6, sticky="nsew")
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=0)

        primary_label = ctk.CTkLabel(
            content_frame,
            text=primary_text,
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        primary_label.grid(row=0, column=0, sticky="w")

        status_chip = ctk.CTkLabel(
            content_frame,
            text=style['label'],
            fg_color=style['fg_color'],
            text_color=style['text_color'],
            corner_radius=10,
            font=ctk.CTkFont(size=10, weight="bold")
        )
        status_chip.grid(row=0, column=1, padx=(8, 0), sticky="e")

        secondary_label = ctk.CTkLabel(
            content_frame,
            text=secondary_text,
            anchor="w",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        secondary_label.grid(row=1, column=0, columnspan=2, sticky="w")

        detail_label = ctk.CTkLabel(
            content_frame,
            text="",
            anchor="w",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        detail_label.grid(row=2, column=0, columnspan=2, sticky="w")
        detail_label.grid_remove()

        progress_row = ctk.CTkFrame(content_frame, fg_color="transparent")
        progress_row.grid(row=3, column=0, columnspan=2, pady=(4, 0), sticky="ew")
        progress_row.grid_columnconfigure(0, weight=1)

        progress_bar = ctk.CTkProgressBar(progress_row, height=12)
        progress_bar.grid(row=0, column=0, sticky="ew")
        progress_bar.set(0)
        progress_color = self.TASK_PROGRESS_COLORS.get(state)
        if progress_color:
            progress_bar.configure(progress_color=progress_color)

        eta_label = ctk.CTkLabel(
            progress_row,
            text="ETA: Pending",
            anchor="e",
            font=ctk.CTkFont(size=10)
        )
        eta_label.grid(row=0, column=1, padx=(8, 0), sticky="e")

        limit_row = ctk.CTkFrame(content_frame, fg_color="transparent")
        limit_row.grid(row=4, column=0, columnspan=2, pady=(4, 0), sticky="w")

        limit_label = ctk.CTkLabel(
            limit_row,
            text="Limit KB/s:",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        limit_label.grid(row=0, column=0, sticky="w")

        existing_limit_bps = existing.get('bandwidth_limit_bps')
        limit_var = tk.StringVar()
        if existing_limit_bps:
            limit_var.set(str(int(existing_limit_bps / 1024)))
        limit_entry = ctk.CTkEntry(limit_row, width=90, textvariable=limit_var, placeholder_text="Global")
        limit_entry.grid(row=0, column=1, padx=(6, 0), sticky="w")

        def on_limit_change(*_args, tid=task_id, var=limit_var):
            task = self.download_tasks.get(tid)
            if task:
                task['bandwidth_limit_bps'] = self._parse_bandwidth_kbps(var.get())

        limit_var.trace_add("write", on_limit_change)

        tracker = progress_manager.create_tracker(task_id)
        tracker.set_phase(ProgressPhase.INITIALIZING)

        self.download_tasks[task_id] = {
            'frame': task_frame,
            'primary_label': primary_label,
            'secondary_label': secondary_label,
            'detail_label': detail_label,
            'status_chip': status_chip,
            'progress_bar': progress_bar,
            'eta_label': eta_label,
            'tracker': tracker,
            'display_url': display_text,
            'url': existing.get('url', url),
            'stop_event': existing.get('stop_event', threading.Event()),
            'pause_event': existing.get('pause_event', threading.Event()),
            'cancel_button': existing.get('cancel_button'),
            'pause_button': existing.get('pause_button'),
            'resume_button': existing.get('resume_button'),
            'pause_resume_button': existing.get('pause_resume_button'),
            'context_button': existing.get('context_button'),
            'status_indicator': existing.get('status_indicator'),
            'status_state': existing.get('status_state', 'queued'),
            'detail_text': existing.get('detail_text'),
            'retry_count': existing.get('retry_count', self._current_retry_count),
            'bandwidth_limit_bps': existing.get('bandwidth_limit_bps'),
            'bandwidth_limit_var': limit_var,
            'bandwidth_limit_entry': limit_entry,
            'model_info': existing.get('model_info'),
            'model_size_bytes': existing.get('model_size_bytes')
        }

        actions_frame = ctk.CTkFrame(task_frame, fg_color="transparent")
        actions_frame.grid(row=0, column=1, padx=8, pady=6, sticky="ne")

        button_width = 78
        button_height = 24
        primary_actions = ctk.CTkFrame(actions_frame, fg_color="transparent")
        primary_actions.grid(row=0, column=0, sticky="e")

        pause_button = ctk.CTkButton(
            primary_actions,
            text="Pause",
            width=button_width,
            height=button_height,
            command=lambda tid=task_id: self.pause_download(tid)
        )
        pause_button.grid(row=0, column=0, padx=2, pady=0)
        resume_button = ctk.CTkButton(
            primary_actions,
            text="Resume",
            width=button_width,
            height=button_height,
            command=lambda tid=task_id: self.resume_download(tid),
            state="disabled"
        )
        resume_button.grid(row=0, column=1, padx=2, pady=0)
        cancel_button = ctk.CTkButton(
            primary_actions,
            text="Cancel",
            width=button_width,
            height=button_height,
            command=lambda tid=task_id: self.cancel_download(tid)
        )
        cancel_button.grid(row=0, column=2, padx=2, pady=0)

        reorder_actions = ctk.CTkFrame(actions_frame, fg_color="transparent")
        reorder_actions.grid(row=1, column=0, pady=(4, 0), sticky="e")
        move_up_button = ctk.CTkButton(
            reorder_actions,
            text="Up",
            width=button_width,
            height=button_height,
            command=lambda tid=task_id: self.move_task_up(tid)
        )
        move_up_button.grid(row=0, column=0, padx=2, pady=0)
        move_down_button = ctk.CTkButton(
            reorder_actions,
            text="Down",
            width=button_width,
            height=button_height,
            command=lambda tid=task_id: self.move_task_down(tid)
        )
        move_down_button.grid(row=0, column=1, padx=2, pady=0)

        self.download_tasks[task_id]['pause_button'] = pause_button
        self.download_tasks[task_id]['resume_button'] = resume_button
        self.download_tasks[task_id]['cancel_button'] = cancel_button
        self.download_tasks[task_id]['move_up_button'] = move_up_button
        self.download_tasks[task_id]['move_down_button'] = move_down_button

        self._set_task_state(task_id, state, detail=self.download_tasks[task_id].get('detail_text'))


    def cancel_download(self, task_id):
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
            task['stop_event'].set()

            if 'tracker' in task:
                task['tracker'].cancel()

            # Clean up background thread if it exists
            if task_id in self.background_threads:
                del self.background_threads[task_id]

            self._set_task_state(task_id, "cancelled", detail="Cancelled by user")
            self.log_message(f"Cancellation requested for task: {task['url']}")

    def pause_download(self, task_id):
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
            task['pause_event'].set() # Set the event to signal pause
            
            if 'tracker' in task:
                task['tracker'].pause()
            
            self._set_task_state(task_id, "paused")
            self.log_message(f"Pause requested for task: {task['url']}")
            

    def resume_download(self, task_id):
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
            task['pause_event'].clear() # Clear the event to signal resume
            
            if 'tracker' in task:
                task['tracker'].resume()

            is_queued = any(item['task_id'] == task_id for item in self._download_queue_list)
            new_state = "queued" if is_queued else "downloading"
            self._set_task_state(task_id, new_state)
            self.log_message(f"Resume requested for task: {task['url']}")
 

    def _cleanup_task_ui(self, task_id):
        self._pending_task_cleanup.add(task_id)
        if self._queue_cleanup_job is None:
            self._queue_cleanup_job = self.after(0, self._process_pending_task_cleanup)

    def _process_pending_task_cleanup(self):
        self._queue_cleanup_job = None
        pending = list(self._pending_task_cleanup)
        self._pending_task_cleanup.clear()
        for task_id in pending:
            self.__cleanup_task_ui_internal(task_id)
        self._schedule_queue_ui_order()
        self._schedule_queue_state_refresh()

    def __cleanup_task_ui_internal(self, task_id):
        if task_id in self.download_tasks:
            try:
                slow_jobs = self.download_tasks[task_id].get('slow_phase_jobs') or {}
                for job in list(slow_jobs.values()):
                    try:
                        self.after_cancel(job)
                    except Exception:
                        pass
                slow_jobs.clear()

                # Clean up enhanced progress tracker
                if 'tracker' in self.download_tasks[task_id]:
                    progress_manager.remove_tracker(task_id)

                self.download_tasks[task_id]['frame'].destroy()  # Destroy UI frame
                del self.download_tasks[task_id]  # Remove from tracking
                if task_id in self._task_display_order:
                    self._task_display_order.remove(task_id)

                # Clean up background thread if it exists
                if task_id in self.background_threads:
                    del self.background_threads[task_id]

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
                self._schedule_queue_ui_order() # Update UI to reflect new order
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
                self._schedule_queue_ui_order() # Update UI to reflect new order
            else:
                self.log_message(f"Task {self.download_tasks[task_id]['url']} is already at the bottom of the queue.")

    def _update_queue_ui_order(self):
        self._schedule_queue_ui_order()

    def __update_queue_ui_order_internal(self):
        # Re-grid all task frames based on their display order
        display_order = self._get_display_order()
        for i, task_id in enumerate(display_order):
            if task_id in self.download_tasks:
                task_frame = self.download_tasks[task_id]['frame']
                task_frame.grid(row=i + self.queue_row_offset, column=0, padx=6, pady=6, sticky="ew")
        
        # After re-gridding, ensure the scrollable frame updates its view
        self.queue_frame.update_idletasks() # Force update layout

    def _watch_completion(self, processing_thread):
        processing_thread.join()  # Wait for all URLs to be added to the queue

        # Wait for all tasks to be processed
        while True:
            with self._queue_lock:
                current_queue_size = len(self._download_queue_list)

            # Check if queue is empty (all tasks have been taken for processing)
            queue_empty = (current_queue_size == 0)

            has_active = any(
                task.get('status_state') in self.ACTIVE_STATES
                for task in self.download_tasks.values()
            )

            if queue_empty and not has_active:
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
            self.after(0, lambda: self.progress_label.configure(text="Status: N/A"))
            self.after(0, lambda: self.speed_label.configure(text="Speed: N/A"))
            self.after(0, lambda: self.remaining_label.configure(text="ETA: N/A"))

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
                task_id = task.get('task_id')
                url = task.get('url')
                api_key = task.get('api_key')
                download_path = task.get('download_path')

                if not task_id:
                    continue
                
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
                task_data = self.download_tasks[task_id]
                task_stop_event = task_data['stop_event']
                pause_event = task_data.get('pause_event')
                retry_count = task_data.get('retry_count', self._current_retry_count)
                
                # Handle task cancelled before processing
                if task_stop_event.is_set():
                    self.after_idle(lambda id=task_id: self._safe_update_status(id, "cancelled", "Cancelled"))
                    self.log_message(f"Task {url} was cancelled before processing. Skipping.")
                    continue
                try:
                    self.after_idle(lambda id=task_id: self._safe_update_status(id, "queued", "Fetching info"))
                    self.log_message(f"\nProcessing URL: {url}")
                    
                    model_info = task_data.get('model_info')
                    if not model_info:
                        self.after_idle(lambda id=task_id: self._begin_task_phase(id, "model_info_fetch"))
                        info_start = time.monotonic()
                        model_info, error_message = self.downloader_service.get_model_info(url, api_key)
                        info_elapsed = time.monotonic() - info_start
                        event_data = {'error': error_message} if error_message else {}
                        self.after_idle(
                            lambda id=task_id, elapsed=info_elapsed, data=event_data: self._end_task_phase(
                                id,
                                "model_info_fetch",
                                duration=elapsed,
                                event_data=data,
                            )
                        )
                        if error_message:
                            self.after_idle(lambda id=task_id, msg=error_message: self._safe_update_status(id, "failed", msg))
                            self.log_message(f"Error retrieving model info for {url}: {error_message}")
                            self.after_idle(lambda msg=error_message, u=url: messagebox.showerror("Download Error", f"Could not retrieve model information for URL: {u}\nError: {msg}"))
                            continue
                        task_data['model_info'] = model_info
                    
                    # Check if model is already downloaded
                    if self.downloader_service.is_model_downloaded(model_info, download_path):
                        self.after_idle(lambda id=task_id: self._safe_update_status(id, "complete", "Already downloaded"))
                        self.log_message(f"Model {model_info['model']['name']} v{model_info['name']} already downloaded. Skipping.")
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
                                'speed': speed,
                                'timestamp': time.monotonic()
                            }
                            self.progress_queue.put_nowait(update_data)
                        except queue.Full:
                            pass  # Skip this update if queue is full (prevents memory buildup)
                    
                    bandwidth_limit = self._get_task_bandwidth_limit(task_id)
                    last_error = None

                    for attempt in range(retry_count + 1):
                        if task_stop_event.is_set():
                            self.after_idle(lambda id=task_id: self._safe_update_status(id, "cancelled", "Cancelled"))
                            self.log_message(f"Task {url} was cancelled during processing.")
                            last_error = None
                            break

                        if attempt > 0:
                            delay = self._calculate_backoff_delay(attempt)
                            detail = f"Retrying in {delay}s ({attempt}/{retry_count})"
                            self.after_idle(lambda id=task_id, msg=detail: self._safe_update_status(id, "queued", msg))
                            if not self._wait_for_retry(delay, task_stop_event, pause_event):
                                self.after_idle(lambda id=task_id: self._safe_update_status(id, "cancelled", "Cancelled"))
                                last_error = None
                                break

                        self.after_idle(lambda id=task_id: self._safe_update_status(id, "downloading"))
                        def phase_event_callback(event, phase, data, tid=task_id):
                            try:
                                self.after_idle(
                                    lambda e=event, p=phase, d=data, t=tid: self._handle_phase_event(t, e, p, d)
                                )
                            except Exception:
                                pass
                        download_error, bg_thread = self.downloader_service.download_model(
                            model_info,
                            download_path,
                            api_key,
                            progress_callback=task_progress_callback,
                            stop_event=task_stop_event,
                            pause_event=pause_event,
                            bandwidth_limit=bandwidth_limit,
                            event_callback=phase_event_callback,
                        )

                        if not download_error:
                            if bg_thread:
                                self.background_threads[task_id] = bg_thread

                            self.after_idle(lambda id=task_id: self._safe_update_status(id, "complete"))
                            self.log_message(f"Download complete for {url}")
                            last_error = None
                            break

                        last_error = download_error
                        if not self._is_retryable_error(download_error) or attempt >= retry_count:
                            break

                        self.log_message(f"Retrying {url} after error: {download_error}")

                    if last_error:
                        self.after_idle(lambda id=task_id, err=last_error: self._safe_update_status(id, "failed", err))
                        self.log_message(f"Download failed for {url}: {last_error}")
                        self.after_idle(lambda u=url, err=last_error: messagebox.showerror("Download Error", f"Download failed for {u}\nError: {err}"))
                    
                except Exception as e:
                    self.log_message(f"An unexpected error occurred during queue processing: {e}")
                    if 'task_id' in locals() and task_id in self.download_tasks:
                        self.after_idle(lambda id=task_id, err=e: self._safe_update_status(id, "failed", f"Unexpected error: {err}"))
        self.log_message("Download queue processing stopped.") # Log when the thread actually stops
    

    def _safe_update_status(self, task_id, state, detail=None):
        """Safely update task status with error handling"""
        try:
            self._set_task_state(task_id, state, detail=detail)
        except Exception as e:
            print(f"Error updating status for task {task_id}: {e}")
    
    # Note: _update_task_progress_ui method is now replaced by _apply_progress_update
    # which is called via the progress queue system for better performance
 

    def _on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit? Ongoing downloads will be interrupted."):
            self.stop_event.set() # Signal main queue processing thread to stop
            self.log_message("Shutdown initiated. Signalling individual downloads to stop...")
            for job_attr in ('_progress_flush_job', '_queue_reorder_job', '_queue_state_job', '_queue_cleanup_job'):
                job = getattr(self, job_attr, None)
                if job is not None:
                    try:
                        self.after_cancel(job)
                    except Exception:
                        pass
                    setattr(self, job_attr, None)
            
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
                slow_jobs = task_data.get('slow_phase_jobs') or {}
                for job in list(slow_jobs.values()):
                    try:
                        self.after_cancel(job)
                    except Exception:
                        pass
                slow_jobs.clear()
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
            
            # Wait for the queue processor threads to finish
            for worker in list(self.queue_processor_threads):
                if worker.is_alive():
                    worker.join(timeout=5)
                    if worker.is_alive():
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
