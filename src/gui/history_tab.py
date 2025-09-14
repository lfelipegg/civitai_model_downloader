"""
History tab component for the Civitai Model Downloader GUI.

This module contains all the history tab related functionality.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
from datetime import datetime
import threading
import time

# Import utilities
from src.gui.utils import (
    validate_path,
    open_folder_cross_platform
)

# Import other required components
from src.history_manager import HistoryManager
from src.thumbnail_manager import thumbnail_manager
from src.enhanced_progress_bar import ThumbnailWidget


class HistoryTab:
    """History tab component for the main application."""
    
    def __init__(self, parent_app, history_tab_frame):
        """
        Initialize the history tab component.
        
        Args:
            parent_app: The main application instance
            history_tab_frame: The tkinter frame for the history tab
        """
        self.parent_app = parent_app
        self.history_tab_frame = history_tab_frame
        
        # Initialize history tab specific attributes
        self.current_filters = {}
        self.current_sort_by = "download_date"
        self.current_sort_order = "desc"
        
        # Setup history tab
        self._setup_history_tab()
    
    def _setup_history_tab(self):
        """Setup the history tab UI components."""
        # Configure grid layout for history tab
        self.history_tab_frame.grid_columnconfigure(0, weight=1)
        self.history_tab_frame.grid_rowconfigure(3, weight=1)  # Updated for new filter frame
        
        # Search frame
        self.search_frame = ctk.CTkFrame(self.history_tab_frame)
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
        self.filters_frame = ctk.CTkFrame(self.history_tab_frame)
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
        self.history_controls_frame = ctk.CTkFrame(self.history_tab_frame)
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
        self.history_frame = ctk.CTkScrollableFrame(self.history_tab_frame, label_text="Download History")
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
    
    def search_history(self):
        """Search through download history (legacy method - now redirects to enhanced search)."""
        # Use the new enhanced search method
        self._perform_filtered_search()
    
    def _on_search_changed(self, event=None):
        """Handle search entry changes with debouncing."""
        # Cancel any pending search
        if hasattr(self.parent_app, '_search_after_id'):
            self.parent_app.after_cancel(self.parent_app._search_after_id)
        
        # Schedule a new search after 300ms of inactivity (reduced for faster response)
        self.parent_app._search_after_id = self.parent_app.after(300, self._perform_filtered_search)
    
    def _on_filter_changed(self, *args):
        """Handle filter changes with debouncing."""
        # Cancel any pending search
        if hasattr(self.parent_app, '_search_after_id'):
            self.parent_app.after_cancel(self.parent_app._search_after_id)
        
        # Schedule a new search after 300ms of inactivity
        self.parent_app._search_after_id = self.parent_app.after(300, self._perform_filtered_search)
    
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
        downloads = self.parent_app.history_manager.search_downloads(
            query=query,
            filters=filters,
            sort_by=self.current_sort_by,
            sort_order=self.current_sort_order
        )
        
        # Update statistics
        if query or filters:
            self.stats_label.configure(text=f"Found {len(downloads)} matches")
        else:
            stats = self.parent_app.history_manager.get_stats()
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
        buttons_frame.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="ew")
        
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
        if hasattr(self.parent_app, 'sort_var'):
            sort_text = self.parent_app.sort_var.get()
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
            options = self.parent_app.history_manager.get_filter_options()
            
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
    
    def scan_downloads(self):
        """Scan the download directory to populate history."""
        download_path = self.parent_app.download_path_entry.get()
        if not download_path:
            messagebox.showerror("Error", "Please set a download path first.")
            return
        
        if not os.path.exists(download_path):
            messagebox.showerror("Error", f"Download path does not exist: {download_path}")
            return
        
        # Show progress dialog
        progress_dialog = ctk.CTkToplevel(self.parent_app)
        progress_dialog.title("Scanning Downloads")
        progress_dialog.geometry("300x100")
        progress_dialog.transient(self.parent_app)
        progress_dialog.grab_set()
        
        progress_label = ctk.CTkLabel(progress_dialog, text="Scanning download directory...")
        progress_label.pack(pady=20)
        
        def scan_in_thread():
            try:
                self.parent_app.history_manager.scan_and_populate_history(download_path)
                self.parent_app.after(0, lambda: [progress_dialog.destroy(), self.refresh_history(),
                                     messagebox.showinfo("Scan Complete", "Download directory scan completed.")])
            except Exception as e:
                self.parent_app.after(0, lambda: [progress_dialog.destroy(),
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
            if self.parent_app.history_manager.export_history(filename):
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
            
            if self.parent_app.history_manager.import_history(filename, merge=merge):
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
        dialog = ctk.CTkToplevel(self.parent_app)
        dialog.title("Delete Model")
        dialog.geometry("400x200")
        dialog.transient(self.parent_app)
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
            
            if self.parent_app.history_manager.delete_download_entry(download['id'], delete_files=delete_files):
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


# This would be used by the main application to initialize the history tab
def create_history_tab(parent_app, history_tab_frame):
    """
    Factory function to create and initialize the history tab.
    
    Args:
        parent_app: The main application instance
        history_tab_frame: The tkinter frame for the history tab
        
    Returns:
        HistoryTab: Initialized history tab component
    """
    return HistoryTab(parent_app, history_tab_frame)