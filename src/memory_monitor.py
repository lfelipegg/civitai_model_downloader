"""
Memory Monitor for Civitai Model Downloader

This module provides memory usage monitoring and warning capabilities
to help manage application memory consumption.
"""

import os
import threading
import time
import psutil
from typing import Dict, Callable, Optional
from dataclasses import dataclass
from enum import Enum


class MemoryWarningLevel(Enum):
    """Memory warning levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class MemoryStats:
    """Memory statistics"""
    process_memory_mb: float
    process_memory_percent: float
    system_memory_mb: float
    system_memory_percent: float
    available_memory_mb: float
    warning_level: MemoryWarningLevel
    timestamp: float


class MemoryMonitor:
    """
    Monitor memory usage and provide warnings when usage gets too high
    """
    
    def __init__(self, warning_callback: Optional[Callable[[MemoryStats], None]] = None):
        self.warning_callback = warning_callback
        self.process = psutil.Process()
        
        # Monitoring thread
        self._monitor_thread = None
        self._stop_monitoring = threading.Event()
        self._lock = threading.Lock()
        
        # Configuration
        self.check_interval = 5.0  # Check every 5 seconds
        self.warning_thresholds = {
            MemoryWarningLevel.LOW: 50.0,      # 50% of system memory
            MemoryWarningLevel.MEDIUM: 70.0,   # 70% of system memory
            MemoryWarningLevel.HIGH: 85.0,     # 85% of system memory
            MemoryWarningLevel.CRITICAL: 95.0  # 95% of system memory
        }
        
        # Process-specific thresholds (MB)
        self.process_thresholds = {
            MemoryWarningLevel.LOW: 200.0,      # 200 MB
            MemoryWarningLevel.MEDIUM: 500.0,   # 500 MB
            MemoryWarningLevel.HIGH: 1000.0,    # 1 GB
            MemoryWarningLevel.CRITICAL: 2000.0 # 2 GB
        }
        
        # Last stats and warning state
        self._last_stats: Optional[MemoryStats] = None
        self._last_warning_level = MemoryWarningLevel.LOW
        self._warning_cooldown = {}  # Track when warnings were last sent
        self._warning_cooldown_time = 60.0  # 1 minute between same-level warnings
    
    def start_monitoring(self):
        """Start background memory monitoring"""
        with self._lock:
            if self._monitor_thread and self._monitor_thread.is_alive():
                return
            
            self._stop_monitoring.clear()
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop background memory monitoring"""
        with self._lock:
            self._stop_monitoring.set()
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=2)
    
    def get_current_stats(self) -> MemoryStats:
        """Get current memory statistics"""
        try:
            # Process memory info
            process_memory = self.process.memory_info()
            process_memory_mb = process_memory.rss / (1024 * 1024)
            
            # System memory info
            system_memory = psutil.virtual_memory()
            system_memory_mb = system_memory.total / (1024 * 1024)
            system_memory_percent = system_memory.percent
            available_memory_mb = system_memory.available / (1024 * 1024)
            
            # Process memory as percentage of system
            process_memory_percent = (process_memory_mb / system_memory_mb) * 100
            
            # Determine warning level
            warning_level = self._determine_warning_level(
                process_memory_mb, system_memory_percent
            )
            
            stats = MemoryStats(
                process_memory_mb=process_memory_mb,
                process_memory_percent=process_memory_percent,
                system_memory_mb=system_memory_mb,
                system_memory_percent=system_memory_percent,
                available_memory_mb=available_memory_mb,
                warning_level=warning_level,
                timestamp=time.time()
            )
            
            self._last_stats = stats
            return stats
            
        except Exception as e:
            print(f"Error getting memory stats: {e}")
            # Return default stats
            return MemoryStats(
                process_memory_mb=0.0,
                process_memory_percent=0.0,
                system_memory_mb=0.0,
                system_memory_percent=0.0,
                available_memory_mb=0.0,
                warning_level=MemoryWarningLevel.LOW,
                timestamp=time.time()
            )
    
    def _determine_warning_level(self, process_memory_mb: float, system_memory_percent: float) -> MemoryWarningLevel:
        """Determine warning level based on memory usage"""
        # Check system memory first
        for level in [MemoryWarningLevel.CRITICAL, MemoryWarningLevel.HIGH, 
                     MemoryWarningLevel.MEDIUM, MemoryWarningLevel.LOW]:
            if system_memory_percent >= self.warning_thresholds[level]:
                return level
        
        # Check process memory
        for level in [MemoryWarningLevel.CRITICAL, MemoryWarningLevel.HIGH,
                     MemoryWarningLevel.MEDIUM, MemoryWarningLevel.LOW]:
            if process_memory_mb >= self.process_thresholds[level]:
                return level
        
        return MemoryWarningLevel.LOW
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        while not self._stop_monitoring.wait(self.check_interval):
            try:
                stats = self.get_current_stats()
                
                # Check if we need to send a warning
                if self._should_send_warning(stats):
                    self._send_warning(stats)
                    
            except Exception as e:
                print(f"Error in memory monitoring loop: {e}")
    
    def _should_send_warning(self, stats: MemoryStats) -> bool:
        """Check if a warning should be sent"""
        # Don't warn for LOW level
        if stats.warning_level == MemoryWarningLevel.LOW:
            return False
        
        # Check if we're in cooldown for this warning level
        current_time = time.time()
        last_warning_time = self._warning_cooldown.get(stats.warning_level, 0)
        
        if current_time - last_warning_time < self._warning_cooldown_time:
            return False
        
        # Send warning if level increased or enough time has passed
        return True
    
    def _send_warning(self, stats: MemoryStats):
        """Send memory warning"""
        self._warning_cooldown[stats.warning_level] = time.time()
        self._last_warning_level = stats.warning_level
        
        if self.warning_callback:
            try:
                self.warning_callback(stats)
            except Exception as e:
                print(f"Error in memory warning callback: {e}")
    
    def get_memory_summary(self) -> str:
        """Get a formatted memory usage summary"""
        if not self._last_stats:
            stats = self.get_current_stats()
        else:
            stats = self._last_stats
        
        return (
            f"Memory Usage:\n"
            f"  Process: {stats.process_memory_mb:.1f} MB ({stats.process_memory_percent:.1f}%)\n"
            f"  System: {stats.system_memory_percent:.1f}% used\n"
            f"  Available: {stats.available_memory_mb:.1f} MB\n"
            f"  Warning Level: {stats.warning_level.value.title()}"
        )
    
    def force_cleanup(self):
        """Force memory cleanup operations"""
        try:
            import gc
            
            # Force garbage collection
            collected = gc.collect()
            print(f"Garbage collection freed {collected} objects")
            
            # Thumbnail cache feature disabled; skip cleanup steps.
            return True
        except Exception as e:
            print(f"Error during forced cleanup: {e}")
            return False
    
    def get_detailed_memory_info(self) -> Dict[str, any]:
        """Get detailed memory information including cache usage"""
        try:
            stats = self.get_current_stats()
            
            # Thumbnail cache feature disabled; report zeros.
            cache_info = {
                'thumbnail_cache_mb': 0,
                'thumbnail_cache_needs_cleanup': False,
                'thumbnail_cache_stats': {}
            }
            
            return {
                'process_memory_mb': stats.process_memory_mb,
                'process_memory_percent': stats.process_memory_percent,
                'system_memory_mb': stats.system_memory_mb,
                'system_memory_percent': stats.system_memory_percent,
                'available_memory_mb': stats.available_memory_mb,
                'warning_level': stats.warning_level.value,
                'timestamp': stats.timestamp,
                **cache_info
            }
        except Exception as e:
            print(f"Error getting detailed memory info: {e}")
            return {
                'process_memory_mb': 0,
                'process_memory_percent': 0,
                'system_memory_mb': 0,
                'system_memory_percent': 0,
                'available_memory_mb': 0,
                'warning_level': 'low',
                'timestamp': time.time(),
                'thumbnail_cache_mb': 0,
                'thumbnail_cache_needs_cleanup': False,
                'thumbnail_cache_stats': {}
            }


# Global memory monitor instance
memory_monitor = MemoryMonitor()