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

# Assuming civitai_downloader functions are available
from src.civitai_downloader import get_model_info_from_url, download_civitai_model, download_file, is_model_downloaded
from src.history_manager import HistoryManager

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Civitai Model Downloader")
        self.geometry("900x900")

        self._download_queue_list = [] # Replaced queue.Queue with a list
        self._queue_lock = threading.Lock() # Lock for thread-safe access to the queue list
        self._queue_condition = threading.Condition(self._queue_lock) # Condition for signaling queue changes
        self.download_tasks = {} # To hold references to download frames and progress bars
        self.queue_row_counter = 0 # To manage grid placement in the queue_frame
        self.stop_event = threading.Event() # Event to signal threads to stop

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
        self.history_tab.grid_rowconfigure(2, weight=1)
        
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
        
        # Control buttons frame
        self.history_controls_frame = ctk.CTkFrame(self.history_tab)
        self.history_controls_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        
        self.scan_button = ctk.CTkButton(self.history_controls_frame, text="Scan Downloads", command=self.scan_downloads)
        self.scan_button.grid(row=0, column=0, padx=5, pady=5)
        
        self.export_button = ctk.CTkButton(self.history_controls_frame, text="Export History", command=self.export_history)
        self.export_button.grid(row=0, column=1, padx=5, pady=5)
        
        self.import_button = ctk.CTkButton(self.history_controls_frame, text="Import History", command=self.import_history)
        self.import_button.grid(row=0, column=2, padx=5, pady=5)
        
        # Statistics label
        self.stats_label = ctk.CTkLabel(self.history_controls_frame, text="")
        self.stats_label.grid(row=0, column=3, padx=20, pady=5, sticky="e")
        
        # History display
        self.history_frame = ctk.CTkScrollableFrame(self.history_tab, label_text="Download History")
        self.history_frame.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")
        self.history_frame.grid_columnconfigure(0, weight=1)
        
        # Load initial history
        self.refresh_history()

    def browse_txt_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
        if file_path:
            with open(file_path, 'r') as f:
                content = f.read()
            self.url_entry.delete("1.0", ctk.END) # Clear existing content
            self.url_entry.insert("1.0", content) # Insert new content

    def browse_download_path(self):
        dir_path = filedialog.askdirectory()
        if dir_path:
            self.download_path_entry.delete(0, ctk.END)
            self.download_path_entry.insert(0, dir_path)

    def log_message(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert(ctk.END, message + "\n")
        self.log_text.see(ctk.END) # Scroll to the end
        self.log_text.configure(state="disabled")

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
            self.progress_label.configure(text=f"Progress: {bytes_downloaded / (1024*1024):.2f} MB / {total_size / (1024*1024):.2f} MB ({progress_percent:.2f}%)")
            self.speed_label.configure(text=f"Speed: {speed / 1024:.2f} KB/s")
            
            if speed > 0:
                remaining_bytes = total_size - bytes_downloaded
                remaining_time_sec = remaining_bytes / speed
                mins, secs = divmod(remaining_time_sec, 60)
                self.remaining_label.configure(text=f"Remaining: {int(mins)}m {int(secs)}s")
            else:
                self.remaining_label.configure(text="Remaining: Calculating...")
        else:
            self.progress_label.configure(text="Progress: Unknown size")
            self.speed_label.configure(text="Speed: N/A")
            self.remaining_label.configure(text="Remaining: N/A")

    def open_download_folder(self):
        download_path = self.download_path_entry.get()
        if not download_path or not os.path.isdir(download_path):
            messagebox.showerror("Error", "Download path is not valid or not set.")
            return

        try:
            if platform.system() == "Windows":
                os.startfile(download_path)
            elif platform.system() == "Darwin": # macOS
                subprocess.Popen(["open", download_path])
            else: # Linux and other Unix-like
                subprocess.Popen(["xdg-open", download_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder: {e}")

    def _add_urls_to_queue(self, url_input_content, api_key, download_path):
        try:
            urls = []
            if url_input_content.lower().endswith(".txt") and os.path.exists(url_input_content):
                with open(url_input_content, 'r') as f:
                    content = f.read()
                urls = [line.strip() for line in content.split('\n') if line.strip()]
            else:
                # Split URLs by new line for CTkTextbox input
                urls = [line.strip() for line in url_input_content.split('\n') if line.strip()]
            if not urls:
                self.log_message("No URLs provided. Exiting.")
                messagebox.showinfo("Download Info", "No URLs provided.")
                # Re-enable download button immediately if no URLs
                self.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
                return
            
            # Add each URL as a task to the queue
            for url in urls:
                # Validate URL format
                parsed_url = urllib.parse.urlparse(url)
                if not all([parsed_url.scheme, parsed_url.netloc]):
                    self.log_message(f"Skipping invalid URL: {url}")
                    # Add GUI element for the invalid task with a failed status
                    task_id = f"task_{hash(url)}_{self.queue_row_counter}"
                    self.after(0, self._add_download_task_ui, task_id, url)
                    self.after(0, lambda id=task_id, msg="Invalid URL format": self.download_tasks[id]['status_label'].configure(text=f"Status: Failed - {msg}", text_color="red"))
                    continue
                # Create a unique ID for each download task
                task_id = f"task_{hash(url)}_{self.queue_row_counter}"
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
        url_display = (url[:50] + '...') if len(url) > 53 else url
        task_label = ctk.CTkLabel(task_frame, text=f"URL: {url_display}", anchor="w")
        task_label.grid(row=0, column=0, padx=5, pady=2, sticky="w")
        progress_bar = ctk.CTkProgressBar(task_frame, orientation="horizontal")
        progress_bar.set(0)
        progress_bar.grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky="ew")
        status_label = ctk.CTkLabel(task_frame, text="Status: Pending", anchor="w")
        status_label.grid(row=2, column=0, padx=5, pady=2, sticky="w")
        # Store references to update later
        self.download_tasks[task_id] = {
            'frame': task_frame,
            'label': task_label,
            'progress_bar': progress_bar,
            'status_label': status_label,
            'url': url, # Store original URL for full display if needed
            'stop_event': threading.Event(), # Per-task stop event
            'pause_event': threading.Event(), # Per-task pause event
            'cancel_button': None, # Placeholder for cancel button reference
            'pause_button': None, # Placeholder for pause button reference
            'resume_button': None # Placeholder for resume button reference
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
            task['status_label'].configure(text="Status: Cancelling...", text_color="orange")
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
            task['status_label'].configure(text="Status: Paused", text_color="blue")
            if task['pause_button']:
                task['pause_button'].configure(state="disabled")
            if task['resume_button']:
                task['resume_button'].configure(state="normal")
            self.log_message(f"Pause requested for task: {task['url']}")
    def resume_download(self, task_id):
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
            task['pause_event'].clear() # Clear the event to signal resume
            task['status_label'].configure(text="Status: Resuming...", text_color="green")
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
            self.download_tasks[task_id]['frame'].destroy() # Destroy UI frame
            del self.download_tasks[task_id] # Remove from tracking
            self._update_queue_ui_order() # Re-grid remaining tasks
 
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
        processing_thread.join() # Wait for all URLs to be added to the queue
        
        # Wait for the download queue to be empty
        while True:
            with self._queue_lock:
                # Check if there are no pending tasks in the list and no active tasks being processed
                # This assumes tasks are removed from download_tasks when they are truly done (Completed/Failed/Cancelled)
                if not self._download_queue_list and not self.download_tasks:
                    break
            time.sleep(0.5) # Wait a bit before re-checking
        if not self.stop_event.is_set(): # Only show completion if not shutting down
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
                if task_id not in self.download_tasks: # Should not happen if _add_download_task_ui is called first
                    self.log_message(f"Error: Task {task_id} not found in download_tasks dictionary. Skipping.")
                    continue
                task_stop_event = self.download_tasks[task_id]['stop_event']
                
                # Handle task cancelled before processing
                if task_stop_event.is_set():
                    self.after(0, lambda id=task_id: self.download_tasks[id]['status_label'].configure(text="Status: Cancelled", text_color="red"))
                    self.log_message(f"Task {url} was cancelled before processing. Skipping.")
                    self._cleanup_task_ui(task_id) # Call helper for cleanup
                    continue
                try:
                    self.after(0, lambda id=task_id: self.download_tasks[id]['status_label'].configure(text="Status: Fetching Info..."))
                    self.log_message(f"\nProcessing URL: {url}")
                    
                    model_info, error_message = get_model_info_from_url(url, api_key)
                    if error_message:
                        self.after(0, lambda id=task_id, msg=error_message: self.download_tasks[id]['status_label'].configure(text=f"Status: Failed - {msg}", text_color="red"))
                        self.log_message(f"Error retrieving model info for {url}: {error_message}")
                        messagebox.showerror("Download Error", f"Could not retrieve model information for URL: {url}\nError: {error_message}")
                        self._cleanup_task_ui(task_id) # Call helper for cleanup
                        continue
                    # Check if model is already downloaded
                    if is_model_downloaded(model_info, download_path):
                        self.after(0, lambda id=task_id: self.download_tasks[id]['status_label'].configure(text="Status: Already Downloaded"))
                        self.log_message(f"Model {model_info['model']['name']} v{model_info['name']} already downloaded. Skipping.")
                        self._cleanup_task_ui(task_id) # Call helper for cleanup
                        continue
                    # Define a specific progress callback for this task
                    def task_progress_callback(bytes_downloaded, total_size, speed):
                        self.after(0, self._update_task_progress_ui, task_id, bytes_downloaded, total_size, speed)
                    self.after(0, lambda id=task_id: self.download_tasks[id]['status_label'].configure(text="Status: Downloading..."))
                    download_error = download_civitai_model(model_info, download_path, api_key, progress_callback=task_progress_callback, stop_event=task_stop_event, pause_event=self.download_tasks[task_id]['pause_event'])
                    
                    if download_error:
                        self.after(0, lambda id=task_id, err=download_error: self.download_tasks[id]['status_label'].configure(text=f"Status: Failed - {err}", text_color="red"))
                        self.log_message(f"Download failed for {url}: {download_error}")
                        messagebox.showerror("Download Error", f"Download failed for {url}\nError: {download_error}")
                        self._cleanup_task_ui(task_id) # Call helper for cleanup
                    else:
                        self.after(0, lambda id=task_id: self.download_tasks[id]['status_label'].configure(text="Status: Complete", text_color="green"))
                        self.log_message(f"Download complete for {url}")
                        self._cleanup_task_ui(task_id) # Call helper for cleanup
                    
                except Exception as e:
                    self.log_message(f"An unexpected error occurred during queue processing: {e}")
                    if 'task_id' in locals() and task_id in self.download_tasks:
                        self.after(0, lambda id=task_id, err=e: self.download_tasks[id]['status_label'].configure(text=f"Status: Unexpected Error - {err}", text_color="red"))
                        self._cleanup_task_ui(task_id) # Call helper for cleanup
                finally:
                    # The cleanup is now handled explicitly in each branch (continue, if/else, except).
                    # This finally block is no longer needed for cleanup.
                    pass
        self.log_message("Download queue processing stopped.") # Log when the thread actually stops
    
    def _update_task_progress_ui(self, task_id, bytes_downloaded, total_size, speed):
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
            if task['pause_event'].is_set(): # Don't update progress if paused
                return
            if total_size > 0:
                progress_percent = (bytes_downloaded / total_size) * 100
                task['progress_bar'].set(progress_percent / 100)
                task['status_label'].configure(text=f"Status: Downloading... {bytes_downloaded / (1024*1024):.2f} MB / {total_size / (1024*1024):.2f} MB ({progress_percent:.2f}%)")
            else:
                task['progress_bar'].set(0) # Unknown size, reset progress
                task['status_label'].configure(text="Status: Downloading... (Unknown size)")
            
            # Update main speed/remaining labels with current task's info for user feedback
            # This can be made more sophisticated later to show overall progress
            self.speed_label.configure(text=f"Speed: {speed / 1024:.2f} KB/s")
            if speed > 0 and total_size > 0:
                remaining_bytes = total_size - bytes_downloaded
                remaining_time_sec = remaining_bytes / speed
                mins, secs = divmod(remaining_time_sec, 60)
                self.remaining_label.configure(text=f"Remaining: {int(mins)}m {int(secs)}s")
            else:
                self.remaining_label.configure(text="Remaining: Calculating...")
 
    def _on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit? Ongoing downloads will be interrupted."):
            self.stop_event.set() # Signal main queue processing thread to stop
            self.log_message("Shutdown initiated. Signalling individual downloads to stop...")
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
            self.log_message("Waiting for threads to finish...")
            
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
        
        self.log_message("URL input cleared.")
        # Do not reset other fields or download queue display
        # As per the new requirement, "Clear GUI" only clears the current URLs.
    
    # History management methods
    def refresh_history(self):
        """Refresh the history display."""
        # Clear existing history items
        for widget in self.history_frame.winfo_children():
            widget.destroy()
        
        # Get all downloads
        downloads = self.history_manager.get_all_downloads()
        
        # Update statistics
        stats = self.history_manager.get_stats()
        total_size_mb = stats['total_size'] / (1024 * 1024)
        self.stats_label.configure(
            text=f"Total: {stats['total_downloads']} models, {total_size_mb:.1f} MB"
        )
        
        # Display downloads
        for i, download in enumerate(downloads):
            self._create_history_item(download, i)
    
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
        """Search through download history."""
        query = self.search_entry.get().strip()
        
        # Clear existing history items
        for widget in self.history_frame.winfo_children():
            widget.destroy()
        
        if query:
            # Search for matches
            downloads = self.history_manager.search_downloads(query)
            self.stats_label.configure(text=f"Found {len(downloads)} matches")
        else:
            # Show all downloads
            downloads = self.history_manager.get_all_downloads()
            stats = self.history_manager.get_stats()
            total_size_mb = stats['total_size'] / (1024 * 1024)
            self.stats_label.configure(
                text=f"Total: {stats['total_downloads']} models, {total_size_mb:.1f} MB"
            )
        
        # Display results
        for i, download in enumerate(downloads):
            self._create_history_item(download, i)
    
    def _on_search_changed(self, event=None):
        """Handle search entry changes with debouncing."""
        # Cancel any pending search
        if hasattr(self, '_search_after_id'):
            self.after_cancel(self._search_after_id)
        
        # Schedule a new search after 500ms of inactivity
        self._search_after_id = self.after(500, self.search_history)
    
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
        if not download_path or not os.path.exists(download_path):
            messagebox.showerror("Error", "Model folder not found")
            return
        
        try:
            if platform.system() == "Windows":
                os.startfile(download_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", download_path])
            else:  # Linux and other Unix-like
                subprocess.Popen(["xdg-open", download_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder: {e}")
    
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