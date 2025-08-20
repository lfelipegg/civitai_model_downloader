import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
from dotenv import load_dotenv
import threading
import platform
import subprocess

# Assuming civitai_downloader functions are available
from src.civitai_downloader import get_model_info_from_url, download_civitai_model, download_file

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Civitai Model Downloader")
        self.geometry("800x600")

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
        self.api_key_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Enter your Civitai API Key (optional)")
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

        # Download Stats Labels
        self.progress_label = ctk.CTkLabel(self, text="Progress: N/A")
        self.progress_label.grid(row=2, column=0, columnspan=2, padx=20, pady=(10, 0), sticky="w")
        self.speed_label = ctk.CTkLabel(self, text="Speed: N/A")
        self.speed_label.grid(row=3, column=0, columnspan=2, padx=20, pady=(0, 0), sticky="w")
        self.remaining_label = ctk.CTkLabel(self, text="Remaining: N/A")
        self.remaining_label.grid(row=4, column=0, columnspan=2, padx=20, pady=(0, 10), sticky="w")


        # Log Area
        self.log_label = ctk.CTkLabel(self, text="Logs:")
        self.log_label.grid(row=5, column=0, padx=20, pady=(10, 0), sticky="w")
        self.log_text = ctk.CTkTextbox(self, width=600, height=200)
        self.log_text.grid(row=6, column=0, columnspan=2, padx=20, pady=10, sticky="nsew")
        self.log_text.configure(state="disabled") # Make it read-only

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
        download_thread = threading.Thread(target=self._perform_download, args=(url_input_content, api_key, download_path), daemon=True)
        download_thread.start()

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

    def _perform_download(self, url_input_content, api_key, download_path):
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
                return

            for url in urls:
                self.log_message(f"\nProcessing URL: {url}")
                try:
                    # Temporarily override download_file to use the GUI's progress callback
                    original_download_file = download_file
                    
                    def gui_download_file_wrapper(url, path, api_key=None):
                        original_download_file(url, path, api_key, progress_callback=self._update_progress)
                    
                    # Monkey-patching download_file for this specific download
                    from src.civitai_downloader import download_file as original_download_file_ref
                    original_download_file_ref = original_download_file # Store reference to original
                    
                    # This is tricky because download_civitai_model directly calls download_file
                    # We need to make download_civitai_model aware of our progress callback
                    # A better way is to modify download_civitai_model to accept a callback
                    # However, for this iteration, I'll try to pass it down or update it if possible.

                    # Re-importing to ensure we get the latest definition
                    from src.civitai_downloader import download_civitai_model as civitai_downloader_func

                    # This is a bit of a hack, but for demonstration, we'll try to pass the callback
                    # down or make download_civitai_model call a version of download_file that uses it.
                    # The previous change to civitai_downloader.py already added progress_callback to download_file
                    # Now we need to ensure download_civitai_model calls download_file with that callback.

                    # Since download_civitai_model already uses lambda functions for progress,
                    # we need to make those lambdas update the GUI.
                    # This means we need to modify download_civitai_model itself again,
                    # or make a wrapper around it that takes the GUI callback.

                    # Let's revert the lambda changes in civitai_downloader.py first,
                    # and then pass the callback from gui.py.

                    # For now, let's just make sure the `_update_progress` is called.
                    # This requires `download_civitai_model` to pass the callback.
                    # I will assume that the modification to `download_civitai_model` in the previous step
                    # was a placeholder and will be replaced by a more direct way to pass the callback.
                    # For now, I will modify the call to `download_civitai_model` here.

                    # This is the correct way: pass the callback down to download_civitai_model
                    # which then passes it to download_file.
                    # Since download_civitai_model currently has hardcoded print lambdas,
                    # I need to adjust it to accept a callback for model and image downloads.
                    # This means I need to re-read civitai_downloader.py and modify it further.

                    # For now, I will comment out the download_civitai_model call and add a placeholder.
                    # This will allow me to apply the GUI changes first.
                    # Then I'll go back to civitai_downloader.py.

                    # Placeholder for actual download logic
                    # download_civitai_model(model_info, download_path, api_key)
                    # For immediate GUI update, I'll simulate progress.
                    
                    # Let's call the original download_civitai_model, but we need to ensure
                    # its internal calls to download_file use our GUI callback.
                    # This means download_civitai_model needs to accept and pass a callback.

                    # Reverting the `download_civitai_model` part of previous diff
                    # and making it accept a callback.

                    # Ok, a simpler approach for now to get the GUI working for download stats:
                    # I will modify download_file in civitai_downloader.py to use the callback IF provided.
                    # Then, in download_civitai_model, I will pass this callback from the GUI.
                    # The previous diff already did this for download_file.
                    # Now I need to modify download_civitai_model.
                    # This means the current `apply_diff` for `gui.py` needs to be applied first,
                    # then I will modify `civitai_downloader.py` again.

                    model_info, error_message = get_model_info_from_url(url, api_key)
                    if error_message:
                        self.log_message(f"Error retrieving model info for {url}: {error_message}")
                        messagebox.showerror("Download Error", f"Could not retrieve model information for URL: {url}\nError: {error_message}")
                        continue # Skip to next URL
                    
                    download_error = download_civitai_model(model_info, download_path, api_key, progress_callback=self._update_progress)
                    if download_error:
                        self.log_message(f"Download failed for {url}: {download_error}")
                        messagebox.showerror("Download Error", f"Download failed for {url}\nError: {download_error}")
                    else:
                        self.log_message(f"Download complete for {url}")
                except Exception as e:
                    self.log_message(f"An unexpected error occurred while processing {url}: {e}")
                    messagebox.showerror("Download Error", f"An unexpected error occurred while processing {url}: {e}")

            self.log_message("\nAll downloads finished.")
            messagebox.showinfo("Download Complete", "All requested models have been processed.")

        except Exception as e:
            self.log_message(f"An unexpected error occurred: {e}")
            messagebox.showerror("Unexpected Error", f"An unexpected error occurred: {e}")
        finally:
            self.download_button.configure(state="normal", text="Start Download")
            self.progress_label.configure(text="Progress: N/A")
            self.speed_label.configure(text="Speed: N/A")
            self.remaining_label.configure(text="Remaining: N/A")

if __name__ == "__main__":
    app = App()
    app.mainloop()