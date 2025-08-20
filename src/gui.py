import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
from dotenv import load_dotenv
import threading
import platform
import subprocess
import time

# Assuming civitai_downloader functions are available
from src.civitai_downloader import get_model_info_from_url, download_civitai_model, download_file, is_model_downloaded
import queue

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Civitai Model Downloader")
        self.geometry("800x800")

        self.download_queue = queue.Queue()
        self.download_tasks = {} # To hold references to download frames and progress bars
        self.queue_row_counter = 0 # To manage grid placement in the queue_frame

        # Configure grid layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # Input Frame
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.grid(row=0, column=0, columnspan=2, padx=20, pady=20, sticky="ew")
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
        self.download_button = ctk.CTkButton(self, text="Start Download", command=self.start_download_thread)
        self.download_button.grid(row=1, column=0, padx=(20, 10), pady=10, sticky="ew")

        # Open Download Folder Button
        self.open_folder_button = ctk.CTkButton(self, text="Open Downloads Folder", command=self.open_download_folder)
        self.open_folder_button.grid(row=1, column=1, padx=(10, 20), pady=10, sticky="ew")

        # Clear/Reset Button
        self.clear_button = ctk.CTkButton(self, text="Clear/Reset GUI", command=self.clear_gui)
        self.clear_button.grid(row=8, column=0, columnspan=2, padx=20, pady=10, sticky="ew")

        # Download Stats Labels
        self.progress_label = ctk.CTkLabel(self, text="Progress: N/A")
        self.progress_label.grid(row=2, column=0, columnspan=2, padx=20, pady=(10, 0), sticky="w")
        self.speed_label = ctk.CTkLabel(self, text="Speed: N/A")
        self.speed_label.grid(row=3, column=0, columnspan=2, padx=20, pady=(0, 0), sticky="w")
        self.remaining_label = ctk.CTkLabel(self, text="Remaining: N/A")
        self.remaining_label.grid(row=4, column=0, columnspan=2, padx=20, pady=(0, 10), sticky="w")


        # Download Queue Display
        self.queue_frame = ctk.CTkScrollableFrame(self, label_text="Download Queue")
        self.queue_frame.grid(row=5, column=0, columnspan=2, padx=20, pady=10, sticky="nsew")
        self.queue_frame.grid_columnconfigure(0, weight=1)

        # Log Area
        self.log_label = ctk.CTkLabel(self, text="Logs:")
        self.log_label.grid(row=6, column=0, padx=20, pady=(10, 0), sticky="w")
        self.log_text = ctk.CTkTextbox(self, width=600, height=200)
        self.log_text.grid(row=7, column=0, columnspan=2, padx=20, pady=10, sticky="nsew")
        self.log_text.configure(state="disabled") # Make it read-only

        # Configure grid layout to expand queue and log area
        self.grid_rowconfigure(5, weight=2) # Queue frame
        self.grid_rowconfigure(7, weight=1) # Log area

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
        processing_and_completion_thread = threading.Thread(target=self._initiate_download_process, args=(url_input_content, api_key, download_path), daemon=True)
        processing_and_completion_thread.start()

    def _initiate_download_process(self, url_input_content, api_key, download_path):
        # Add URLs to the queue
        self._add_urls_to_queue(url_input_content, api_key, download_path)

        # Start queue processing in a separate thread if not already running
        if not hasattr(self, 'queue_processor_thread') or not self.queue_processor_thread.is_alive():
            self.queue_processor_thread = threading.Thread(target=self._process_download_queue, daemon=True)
            self.queue_processor_thread.start()

        # Wait for all tasks in the queue to be processed
        self.download_queue.join()

        # All downloads are finished, display completion message
        self.after(0, lambda: self.log_message("\nAll downloads finished."))
        self.after(0, lambda: messagebox.showinfo("Download Complete", "All requested models have been processed."))
        
        # Reset main UI elements
        self.after(0, lambda: self.download_button.configure(state="normal", text="Start Download"))
        self.after(0, lambda: self.progress_label.configure(text="Progress: N/A"))
        self.after(0, lambda: self.speed_label.configure(text="Speed: N/A"))
        self.after(0, lambda: self.remaining_label.configure(text="Remaining: N/A"))

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
                    urls = [line.strip() for line in f if line.strip()]
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
                # Create a unique ID for each download task
                task_id = f"task_{hash(url)}_{self.queue_row_counter}"
                self.download_queue.put({'task_id': task_id, 'url': url, 'api_key': api_key, 'download_path': download_path})
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
            'url': url # Store original URL for full display if needed
        }
    
    def _process_download_queue(self):
        while True:
            try:
                task = self.download_queue.get(timeout=1) # Wait for 1 second for a task
                task_id = task['task_id']
                url = task['url']
                api_key = task['api_key']
                download_path = task['download_path']

                self.after(0, lambda id=task_id: self.download_tasks[id]['status_label'].configure(text="Status: Fetching Info..."))
                self.log_message(f"\nProcessing URL: {url}")
                
                model_info, error_message = get_model_info_from_url(url, api_key)
                if error_message:
                    self.after(0, lambda id=task_id, msg=error_message: self.download_tasks[id]['status_label'].configure(text=f"Status: Failed - {msg}"))
                    self.log_message(f"Error retrieving model info for {url}: {error_message}")
                    messagebox.showerror("Download Error", f"Could not retrieve model information for URL: {url}\nError: {error_message}")
                    self.download_queue.task_done()
                    continue

                # Check if model is already downloaded
                if is_model_downloaded(model_info, download_path):
                    self.after(0, lambda id=task_id: self.download_tasks[id]['status_label'].configure(text="Status: Already Downloaded"))
                    self.log_message(f"Model {model_info['model']['name']} v{model_info['name']} already downloaded. Skipping.")
                    self.download_queue.task_done()
                    continue


                # Define a specific progress callback for this task
                def task_progress_callback(bytes_downloaded, total_size, speed):
                    self.after(0, self._update_task_progress_ui, task_id, bytes_downloaded, total_size, speed)

                self.after(0, lambda id=task_id: self.download_tasks[id]['status_label'].configure(text="Status: Downloading..."))
                download_error = download_civitai_model(model_info, download_path, api_key, progress_callback=task_progress_callback)
                
                if download_error:
                    self.after(0, lambda id=task_id, err=download_error: self.download_tasks[id]['status_label'].configure(text=f"Status: Failed - {err}"))
                    self.log_message(f"Download failed for {url}: {download_error}")
                    messagebox.showerror("Download Error", f"Download failed for {url}\nError: {download_error}")
                else:
                    self.after(0, lambda id=task_id: self.download_tasks[id]['status_label'].configure(text="Status: Complete"))
                    self.log_message(f"Download complete for {url}")
                
                self.download_queue.task_done()
            except queue.Empty:
                # No tasks in queue, can add a sleep or break if no more tasks are expected
                # For a daemon thread, it will just keep looping and waiting
                time.sleep(1) # Sleep to prevent busy-waiting
            except Exception as e:
                self.log_message(f"An unexpected error occurred during queue processing: {e}")
                self.download_queue.task_done() # Mark task as done even if it failed unexpectedly
                # Optionally, update UI for the task to show unexpected error
                if 'task_id' in locals() and task_id in self.download_tasks:
                    self.after(0, lambda id=task_id, err=e: self.download_tasks[id]['status_label'].configure(text=f"Status: Unexpected Error - {err}"))
    
    def _update_task_progress_ui(self, task_id, bytes_downloaded, total_size, speed):
        if task_id in self.download_tasks:
            task = self.download_tasks[task_id]
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
 
    def clear_gui(self):
        self.url_entry.delete("1.0", ctk.END)
        # Only clear the URL entry as requested
        
        self.log_message("URL input cleared.")
        # Do not reset other fields or download queue display
        # As per the new requirement, "Clear GUI" only clears the current URLs.

if __name__ == "__main__":
    app = App()
    app.mainloop()