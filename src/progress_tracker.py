"""
Enhanced Progress Tracker for Civitai Model Downloader

This module provides advanced progress tracking with improved ETA calculations,
detailed statistics, and multi-phase progress monitoring.
"""

import time
import threading
from collections import deque
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


class ProgressPhase(Enum):
    """Different phases of the download process"""
    INITIALIZING = "initializing"
    CONNECTING = "connecting"
    DOWNLOADING = "downloading" 
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class ProgressSnapshot:
    """A snapshot of progress at a specific time"""
    timestamp: float
    bytes_downloaded: int
    phase: ProgressPhase
    speed: float = 0.0


@dataclass
class ProgressStats:
    """Detailed progress statistics"""
    # Basic progress
    bytes_downloaded: int = 0
    total_size: int = 0
    percentage: float = 0.0
    
    # Speed tracking
    current_speed: float = 0.0
    average_speed: float = 0.0
    peak_speed: float = 0.0
    
    # Time tracking
    start_time: float = field(default_factory=time.time)
    elapsed_time: float = 0.0
    eta_seconds: float = 0.0
    
    # Phase information
    current_phase: ProgressPhase = ProgressPhase.INITIALIZING
    phase_start_time: float = field(default_factory=time.time)
    phase_elapsed: float = 0.0
    
    # Queue information
    queue_position: int = 0
    total_queue: int = 0
    files_completed: int = 0
    files_total: int = 0


class EnhancedProgressTracker:
    """
    Advanced progress tracker with improved ETA calculation and detailed statistics.
    
    Features:
    - Moving average speed calculation for smoother ETA
    - Multi-phase progress tracking
    - Detailed statistics collection
    - Thread-safe operations
    - Queue-aware progress reporting
    """
    
    def __init__(self, task_id: str, total_size: int = 0, window_size: int = 30):
        self.task_id = task_id
        self.total_size = total_size
        self.window_size = window_size  # Size of moving average window
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Progress tracking
        self._stats = ProgressStats(total_size=total_size)
        self._snapshots = deque(maxlen=window_size)
        self._last_update_time = 0.0
        
        # Speed calculation
        self._speed_samples = deque(maxlen=window_size)
        self._last_bytes = 0
        self._last_speed_update = time.time()
        
        # Phase tracking
        self._phase_history: Dict[ProgressPhase, float] = {}
        
        # Queue tracking
        self._queue_info = {"position": 0, "total": 0}
        
    def set_phase(self, phase: ProgressPhase):
        """Change the current progress phase"""
        with self._lock:
            current_time = time.time()
            
            # Record time spent in previous phase
            if self._stats.current_phase != phase:
                phase_duration = current_time - self._stats.phase_start_time
                self._phase_history[self._stats.current_phase] = phase_duration
                
                # Update phase
                self._stats.current_phase = phase
                self._stats.phase_start_time = current_time
                
    def set_queue_info(self, position: int, total: int, files_completed: int = 0, files_total: int = 0):
        """Update queue position information"""
        with self._lock:
            self._stats.queue_position = position
            self._stats.total_queue = total
            self._stats.files_completed = files_completed
            self._stats.files_total = files_total
            
    def update_progress(self, bytes_downloaded: int, total_size: Optional[int] = None) -> ProgressStats:
        """
        Update progress and calculate statistics.
        
        Args:
            bytes_downloaded: Current bytes downloaded
            total_size: Total file size (if known)
            
        Returns:
            Updated ProgressStats object
        """
        with self._lock:
            current_time = time.time()
            
            # Update total size if provided
            if total_size is not None and total_size > 0:
                self.total_size = total_size
                self._stats.total_size = total_size
            
            # Calculate elapsed time
            self._stats.elapsed_time = current_time - self._stats.start_time
            self._stats.phase_elapsed = current_time - self._stats.phase_start_time
            
            # Update basic progress
            self._stats.bytes_downloaded = bytes_downloaded
            if self._stats.total_size > 0:
                self._stats.percentage = (bytes_downloaded / self._stats.total_size) * 100
            
            # Calculate speeds with smoothing
            self._calculate_speeds(bytes_downloaded, current_time)
            
            # Calculate ETA
            self._calculate_eta()
            
            # Store snapshot for historical analysis
            snapshot = ProgressSnapshot(
                timestamp=current_time,
                bytes_downloaded=bytes_downloaded,
                phase=self._stats.current_phase,
                speed=self._stats.current_speed
            )
            self._snapshots.append(snapshot)
            
            self._last_update_time = current_time
            
            return self._get_stats_copy()
    
    def _calculate_speeds(self, bytes_downloaded: int, current_time: float):
        """Calculate current, average, and peak speeds with smoothing"""
        time_delta = current_time - self._last_speed_update
        
        if time_delta >= 0.1:  # Update speed every 100ms minimum
            bytes_delta = bytes_downloaded - self._last_bytes
            
            if time_delta > 0:
                instant_speed = bytes_delta / time_delta
                self._speed_samples.append(instant_speed)
                
                # Current speed (smoothed)
                if len(self._speed_samples) > 1:
                    # Use weighted average favoring recent samples
                    weights = [i + 1 for i in range(len(self._speed_samples))]
                    total_weight = sum(weights)
                    weighted_sum = sum(speed * weight for speed, weight in zip(self._speed_samples, weights))
                    self._stats.current_speed = weighted_sum / total_weight
                else:
                    self._stats.current_speed = instant_speed
                
                # Peak speed
                self._stats.peak_speed = max(self._stats.peak_speed, instant_speed)
            
            self._last_bytes = bytes_downloaded
            self._last_speed_update = current_time
        
        # Average speed over entire download
        if self._stats.elapsed_time > 0:
            self._stats.average_speed = self._stats.bytes_downloaded / self._stats.elapsed_time
    
    def _calculate_eta(self):
        """Calculate ETA using multiple methods for better accuracy"""
        if self._stats.total_size <= 0 or self._stats.bytes_downloaded <= 0:
            self._stats.eta_seconds = 0.0
            return
        
        remaining_bytes = self._stats.total_size - self._stats.bytes_downloaded
        
        if remaining_bytes <= 0:
            self._stats.eta_seconds = 0.0
            return
        
        # Method 1: Use current smoothed speed
        eta_current = 0.0
        if self._stats.current_speed > 0:
            eta_current = remaining_bytes / self._stats.current_speed
        
        # Method 2: Use average speed
        eta_average = 0.0
        if self._stats.average_speed > 0:
            eta_average = remaining_bytes / self._stats.average_speed
        
        # Method 3: Use recent trend analysis
        eta_trend = 0.0
        if len(self._snapshots) >= 3:
            recent_snapshots = list(self._snapshots)[-min(10, len(self._snapshots)):]
            if len(recent_snapshots) >= 2:
                time_span = recent_snapshots[-1].timestamp - recent_snapshots[0].timestamp
                bytes_span = recent_snapshots[-1].bytes_downloaded - recent_snapshots[0].bytes_downloaded
                
                if time_span > 0 and bytes_span > 0:
                    trend_speed = bytes_span / time_span
                    if trend_speed > 0:
                        eta_trend = remaining_bytes / trend_speed
        
        # Combine methods with weights
        valid_etas = []
        if eta_current > 0:
            valid_etas.append((eta_current, 0.4))  # 40% weight on current speed
        if eta_average > 0:
            valid_etas.append((eta_average, 0.3))  # 30% weight on average speed
        if eta_trend > 0:
            valid_etas.append((eta_trend, 0.3))    # 30% weight on trend analysis
        
        if valid_etas:
            total_weight = sum(weight for _, weight in valid_etas)
            weighted_eta = sum(eta * weight for eta, weight in valid_etas) / total_weight
            
            # Apply bounds to prevent unrealistic ETAs
            max_reasonable_eta = self._stats.elapsed_time * 5  # Max 5x current elapsed time
            min_reasonable_eta = 1.0  # Minimum 1 second
            
            self._stats.eta_seconds = max(min_reasonable_eta, min(weighted_eta, max_reasonable_eta))
        else:
            self._stats.eta_seconds = 0.0
    
    def _get_stats_copy(self) -> ProgressStats:
        """Get a copy of current statistics"""
        # Create a copy to avoid race conditions
        return ProgressStats(
            bytes_downloaded=self._stats.bytes_downloaded,
            total_size=self._stats.total_size,
            percentage=self._stats.percentage,
            current_speed=self._stats.current_speed,
            average_speed=self._stats.average_speed,
            peak_speed=self._stats.peak_speed,
            start_time=self._stats.start_time,
            elapsed_time=self._stats.elapsed_time,
            eta_seconds=self._stats.eta_seconds,
            current_phase=self._stats.current_phase,
            phase_start_time=self._stats.phase_start_time,
            phase_elapsed=self._stats.phase_elapsed,
            queue_position=self._stats.queue_position,
            total_queue=self._stats.total_queue,
            files_completed=self._stats.files_completed,
            files_total=self._stats.files_total
        )
    
    def get_formatted_stats(self) -> Dict[str, str]:
        """Get human-readable formatted statistics"""
        with self._lock:
            stats = self._get_stats_copy()
            
            def format_bytes(bytes_val: int) -> str:
                """Format bytes as human-readable string"""
                for unit in ['B', 'KB', 'MB', 'GB']:
                    if bytes_val < 1024:
                        return f"{bytes_val:.1f} {unit}"
                    bytes_val /= 1024
                return f"{bytes_val:.1f} TB"
            
            def format_speed(speed: float) -> str:
                """Format speed as human-readable string"""
                return f"{format_bytes(int(speed))}/s"
            
            def format_time(seconds: float) -> str:
                """Format time as human-readable string"""
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
                'peak_speed': format_speed(stats.peak_speed),
                'elapsed_time': format_time(stats.elapsed_time),
                'eta': format_time(stats.eta_seconds),
                'phase': stats.current_phase.value.title(),
                'queue_info': f"Position {stats.queue_position}/{stats.total_queue}" if stats.total_queue > 0 else "",
                'files_info': f"Files {stats.files_completed}/{stats.files_total}" if stats.files_total > 0 else ""
            }
    
    def pause(self):
        """Mark tracker as paused"""
        self.set_phase(ProgressPhase.PAUSED)
    
    def resume(self):
        """Resume from paused state"""
        self.set_phase(ProgressPhase.DOWNLOADING)
        
    def complete(self):
        """Mark tracker as completed"""
        self.set_phase(ProgressPhase.COMPLETED)
        
    def fail(self):
        """Mark tracker as failed"""
        self.set_phase(ProgressPhase.FAILED)
        
    def cancel(self):
        """Mark tracker as cancelled"""
        self.set_phase(ProgressPhase.CANCELLED)


class ProgressTrackerManager:
    """
    Manages multiple progress trackers for queue-based downloads
    """
    
    def __init__(self):
        self._trackers: Dict[str, EnhancedProgressTracker] = {}
        self._lock = threading.Lock()
        
    def create_tracker(self, task_id: str, total_size: int = 0) -> EnhancedProgressTracker:
        """Create a new progress tracker"""
        with self._lock:
            tracker = EnhancedProgressTracker(task_id, total_size)
            self._trackers[task_id] = tracker
            return tracker
    
    def get_tracker(self, task_id: str) -> Optional[EnhancedProgressTracker]:
        """Get existing progress tracker"""
        with self._lock:
            return self._trackers.get(task_id)
    
    def remove_tracker(self, task_id: str):
        """Remove progress tracker"""
        with self._lock:
            self._trackers.pop(task_id, None)
    
    def get_all_trackers(self) -> Dict[str, EnhancedProgressTracker]:
        """Get all active trackers"""
        with self._lock:
            return dict(self._trackers)
    
    def update_queue_positions(self):
        """Update queue positions for all trackers"""
        with self._lock:
            active_trackers = [
                (task_id, tracker) for task_id, tracker in self._trackers.items()
                if tracker._stats.current_phase in [ProgressPhase.INITIALIZING, ProgressPhase.CONNECTING, ProgressPhase.DOWNLOADING]
            ]
            
            for i, (task_id, tracker) in enumerate(active_trackers):
                tracker.set_queue_info(
                    position=i + 1,
                    total=len(active_trackers),
                    files_completed=len([t for t in self._trackers.values() if t._stats.current_phase == ProgressPhase.COMPLETED]),
                    files_total=len(self._trackers)
                )


# Global progress tracker manager instance
progress_manager = ProgressTrackerManager()