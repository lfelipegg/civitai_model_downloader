"""
Enhanced Progress Bar Components for Civitai Model Downloader

This module provides custom progress bar widgets with multi-phase visualization,
detailed statistics display, and improved visual feedback.
"""

import customtkinter as ctk
import tkinter as tk
import os
from typing import Dict, Optional, Callable
from src.progress_tracker import ProgressPhase, ProgressStats

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class MultiPhaseProgressBar(ctk.CTkFrame):
    """
    Multi-phase progress bar with colored segments for different download phases.
    
    Features:
    - Color-coded phases (connecting, downloading, verifying)
    - Percentage overlay
    - Smooth transitions
    - Phase indicators
    """
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        
        # Progress bar container
        self.progress_container = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_container.grid(row=0, column=0, sticky="ew", padx=5, pady=2)
        self.progress_container.grid_columnconfigure(0, weight=1)
        
        # Main progress bar
        self.progress_bar = ctk.CTkProgressBar(self.progress_container, height=20)
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        self.progress_bar.set(0)
        
        # Percentage label overlay
        self.percentage_label = ctk.CTkLabel(
            self.progress_container,
            text="0%",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="white"
        )
        self.percentage_label.place(relx=0.5, rely=0.5, anchor="center")
        
        # Phase indicator
        self.phase_label = ctk.CTkLabel(
            self,
            text="Initializing",
            font=ctk.CTkFont(size=10),
            text_color="gray"
        )
        self.phase_label.grid(row=1, column=0, sticky="w", padx=5)
        
        # Phase color mapping
        self.phase_colors = {
            ProgressPhase.INITIALIZING: "#ffa500",  # Orange
            ProgressPhase.CONNECTING: "#ffff00",    # Yellow
            ProgressPhase.DOWNLOADING: "#4CAF50",   # Green
            ProgressPhase.VERIFYING: "#2196F3",     # Blue
            ProgressPhase.COMPLETED: "#4CAF50",     # Green
            ProgressPhase.FAILED: "#f44336",        # Red
            ProgressPhase.PAUSED: "#9E9E9E",        # Gray
            ProgressPhase.CANCELLED: "#795548"      # Brown
        }
        
        # Current values
        self.current_progress = 0.0
        self.current_phase = ProgressPhase.INITIALIZING
        
    def update_progress(self, progress: float, phase: ProgressPhase = None):
        """Update progress bar with new values"""
        self.current_progress = max(0.0, min(100.0, progress))
        
        if phase is not None:
            self.current_phase = phase
            
        # Update progress bar
        self.progress_bar.set(self.current_progress / 100.0)
        
        # Update percentage label
        self.percentage_label.configure(text=f"{self.current_progress:.1f}%")
        
        # Update phase indicator and color
        phase_name = self.current_phase.value.replace('_', ' ').title()
        self.phase_label.configure(text=f"Phase: {phase_name}")
        
        # Change progress bar color based on phase
        if self.current_phase in self.phase_colors:
            color = self.phase_colors[self.current_phase]
            self.progress_bar.configure(progress_color=color)
    
    def reset(self):
        """Reset progress bar to initial state"""
        self.update_progress(0.0, ProgressPhase.INITIALIZING)


class DetailedStatsDisplay(ctk.CTkFrame):
    """
    Detailed statistics display with formatted metrics.
    
    Shows:
    - Download progress with sizes
    - Current/average/peak speeds
    - Time elapsed and ETA
    - Queue position
    """
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        # Create stats labels in a 2-column layout
        self.stats_labels = {}
        
        # Row 0: Download info
        self.stats_labels['downloaded'] = ctk.CTkLabel(
            self, text="Downloaded: 0 B / 0 B (0%)", 
            font=ctk.CTkFont(size=11), anchor="w"
        )
        self.stats_labels['downloaded'].grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=2)
        
        # Row 1: Speed info
        self.stats_labels['current_speed'] = ctk.CTkLabel(
            self, text="Current: 0 B/s", 
            font=ctk.CTkFont(size=10), anchor="w"
        )
        self.stats_labels['current_speed'].grid(row=1, column=0, sticky="ew", padx=5, pady=1)
        
        self.stats_labels['average_speed'] = ctk.CTkLabel(
            self, text="Average: 0 B/s", 
            font=ctk.CTkFont(size=10), anchor="w"
        )
        self.stats_labels['average_speed'].grid(row=1, column=1, sticky="ew", padx=5, pady=1)
        
        # Row 2: Time info
        self.stats_labels['elapsed_time'] = ctk.CTkLabel(
            self, text="Elapsed: 0s", 
            font=ctk.CTkFont(size=10), anchor="w"
        )
        self.stats_labels['elapsed_time'].grid(row=2, column=0, sticky="ew", padx=5, pady=1)
        
        self.stats_labels['eta'] = ctk.CTkLabel(
            self, text="ETA: Unknown", 
            font=ctk.CTkFont(size=10), anchor="w"
        )
        self.stats_labels['eta'].grid(row=2, column=1, sticky="ew", padx=5, pady=1)
        
        # Row 3: Queue info (if available)
        self.stats_labels['queue_info'] = ctk.CTkLabel(
            self, text="", 
            font=ctk.CTkFont(size=10), anchor="w"
        )
        self.stats_labels['queue_info'].grid(row=3, column=0, columnspan=2, sticky="ew", padx=5, pady=1)
    
    def update_stats(self, formatted_stats: Dict[str, str]):
        """Update display with formatted statistics"""
        for key, value in formatted_stats.items():
            if key in self.stats_labels:
                # Apply color coding for better readability
                text_color = "gray"  # Default color instead of None
                if key == 'current_speed' and 'MB/s' in value:
                    text_color = "green"
                elif key == 'eta' and value != "Unknown":
                    text_color = "blue"
                
                self.stats_labels[key].configure(
                    text=f"{key.replace('_', ' ').title()}: {value}",
                    text_color=text_color
                )
    
    def clear_stats(self):
        """Clear all statistics"""
        default_stats = {
            'downloaded': "0 B / 0 B (0%)",
            'current_speed': "0 B/s",
            'average_speed': "0 B/s",
            'elapsed_time': "0s",
            'eta': "Unknown",
            'queue_info': ""
        }
        self.update_stats(default_stats)


class EnhancedProgressWidget(ctk.CTkFrame):
    """
    Complete enhanced progress widget combining progress bar and statistics.
    
    This is the main widget that will replace the simple progress bars
    in the download queue display.
    """
    
    def __init__(self, master, task_id: str, **kwargs):
        super().__init__(master, **kwargs)
        
        self.task_id = task_id
        
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        
        # Multi-phase progress bar
        self.progress_bar = MultiPhaseProgressBar(self)
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=5, pady=2)
        
        # Detailed statistics display
        self.stats_display = DetailedStatsDisplay(self)
        self.stats_display.grid(row=1, column=0, sticky="ew", padx=5, pady=2)
        
        # Collapsible stats (starts collapsed for space)
        self.stats_expanded = False
        self.toggle_button = ctk.CTkButton(
            self,
            text="▼ Details",
            command=self.toggle_stats,
            width=80,
            height=20,
            font=ctk.CTkFont(size=10)
        )
        self.toggle_button.grid(row=2, column=0, sticky="e", padx=5, pady=2)
        
        # Initially hide detailed stats
        self.stats_display.grid_remove()
    
    def toggle_stats(self):
        """Toggle detailed statistics visibility"""
        if self.stats_expanded:
            self.stats_display.grid_remove()
            self.toggle_button.configure(text="▼ Details")
            self.stats_expanded = False
        else:
            self.stats_display.grid(row=1, column=0, sticky="ew", padx=5, pady=2)
            self.toggle_button.configure(text="▲ Hide")
            self.stats_expanded = True
    
    def update_from_tracker(self, stats: ProgressStats):
        """Update widget from progress tracker stats"""
        # Update progress bar
        self.progress_bar.update_progress(stats.percentage, stats.current_phase)
        
        # Format stats for display
        formatted_stats = self._format_stats(stats)
        self.stats_display.update_stats(formatted_stats)
    
    def update_from_formatted_stats(self, formatted_stats: Dict[str, str], 
                                  progress: float, phase: ProgressPhase):
        """Update widget from pre-formatted stats"""
        self.progress_bar.update_progress(progress, phase)
        self.stats_display.update_stats(formatted_stats)
    
    def _format_stats(self, stats: ProgressStats) -> Dict[str, str]:
        """Format ProgressStats for display"""
        def format_bytes(bytes_val: int) -> str:
            for unit in ['B', 'KB', 'MB', 'GB']:
                if bytes_val < 1024:
                    return f"{bytes_val:.1f} {unit}"
                bytes_val /= 1024
            return f"{bytes_val:.1f} TB"
        
        def format_speed(speed: float) -> str:
            return f"{format_bytes(int(speed))}/s"
        
        def format_time(seconds: float) -> str:
            if seconds <= 0:
                return "Unknown"
            
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            
            if hours > 0:
                return f"{hours}h {minutes}m {secs}s"
            elif minutes > 0:
                return f"{minutes}m {secs}s"
            else:
                return f"{secs}s"
        
        return {
            'downloaded': f"{format_bytes(stats.bytes_downloaded)} / {format_bytes(stats.total_size)} ({stats.percentage:.1f}%)",
            'current_speed': format_speed(stats.current_speed),
            'average_speed': format_speed(stats.average_speed),
            'elapsed_time': format_time(stats.elapsed_time),
            'eta': format_time(stats.eta_seconds),
            'queue_info': f"Position {stats.queue_position}/{stats.total_queue}" if stats.total_queue > 0 else ""
        }
    
    def reset(self):
        """Reset widget to initial state"""
        self.progress_bar.reset()
        self.stats_display.clear_stats()
        if self.stats_expanded:
            self.toggle_stats()  # Collapse stats


class ThumbnailWidget(ctk.CTkLabel):
    """
    Custom thumbnail widget for displaying model preview images.
    
    Features:
    - Lazy loading
    - Fallback placeholder
    - Click to view full image
    - Hover effects
    """
    
    def __init__(self, master, size: tuple = (64, 64), **kwargs):
        super().__init__(master, text="", **kwargs)
        
        self.size = size
        self.thumbnail_path = None
        self.fallback_path = None
        self.click_callback = None
        
        # Configure appearance
        self.configure(
            width=size[0],
            height=size[1],
            fg_color=("gray90", "gray20"),
            corner_radius=4,
            text="Loading..."
        )
        
        # Bind click event
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
    
    def set_thumbnail(self, thumbnail_path: Optional[str], fallback_path: Optional[str] = None):
        """Set thumbnail image path"""
        self.thumbnail_path = thumbnail_path
        self.fallback_path = fallback_path
        
        try:
            if PIL_AVAILABLE and thumbnail_path and os.path.exists(thumbnail_path):
                # Load thumbnail image
                image = ctk.CTkImage(
                    light_image=Image.open(thumbnail_path),
                    dark_image=Image.open(thumbnail_path),
                    size=self.size
                )
                self.configure(image=image, text="")
            elif PIL_AVAILABLE and fallback_path and os.path.exists(fallback_path):
                # Load fallback image
                image = ctk.CTkImage(
                    light_image=Image.open(fallback_path),
                    dark_image=Image.open(fallback_path),
                    size=self.size
                )
                self.configure(image=image, text="")
            else:
                # Show placeholder text
                self.configure(image=None, text="No\nImage")
                
        except Exception as e:
            print(f"Error loading thumbnail: {e}")
            self.configure(image=None, text="Error")
    
    def set_click_callback(self, callback: Callable):
        """Set callback for click events"""
        self.click_callback = callback
    
    def _on_click(self, event):
        """Handle click events"""
        if self.click_callback:
            self.click_callback(self.thumbnail_path)
    
    def _on_enter(self, event):
        """Handle mouse enter (hover effect)"""
        self.configure(fg_color=("gray80", "gray30"))
    
    def _on_leave(self, event):
        """Handle mouse leave"""
        self.configure(fg_color=("gray90", "gray20"))