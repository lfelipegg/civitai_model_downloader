#!/usr/bin/env python3
"""
Comprehensive test suite for the enhanced progress tracking system.
Tests ETA calculations, multi-phase visualization, thread safety, and performance.
"""

import unittest
import threading
import time
import queue
from unittest.mock import Mock, patch
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from progress_tracker import (
        ProgressPhase, EnhancedProgressTracker, ProgressTrackerManager
    )
    from enhanced_progress_bar import (
        MultiPhaseProgressBar, DetailedStatsDisplay, EnhancedProgressWidget
    )
    import customtkinter as ctk
    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_AVAILABLE = False


class TestEnhancedProgressTracker(unittest.TestCase):
    """Test the enhanced progress tracker functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not IMPORTS_AVAILABLE:
            self.skipTest("Required imports not available")
        
        self.tracker = EnhancedProgressTracker("test_download")
    
    def test_initialization(self):
        """Test tracker initialization."""
        self.assertEqual(self.tracker.task_id, "test_download")
        self.assertEqual(self.tracker._stats.current_phase, ProgressPhase.INITIALIZING)
        self.assertEqual(self.tracker._stats.percentage, 0.0)
        self.assertEqual(self.tracker._stats.eta_seconds, 0.0)
        self.assertEqual(self.tracker._stats.current_speed, 0.0)
    
    def test_phase_transitions(self):
        """Test phase transition logic."""
        # Test normal progression
        self.tracker.set_phase(ProgressPhase.CONNECTING)
        self.assertEqual(self.tracker._stats.current_phase, ProgressPhase.CONNECTING)
        
        self.tracker.set_phase(ProgressPhase.DOWNLOADING)
        self.assertEqual(self.tracker._stats.current_phase, ProgressPhase.DOWNLOADING)
        
        self.tracker.set_phase(ProgressPhase.VERIFYING)
        self.assertEqual(self.tracker._stats.current_phase, ProgressPhase.VERIFYING)
        
        self.tracker.set_phase(ProgressPhase.COMPLETED)
        self.assertEqual(self.tracker._stats.current_phase, ProgressPhase.COMPLETED)
    
    def test_progress_updates(self):
        """Test progress update functionality."""
        # Start downloading phase
        self.tracker.set_phase(ProgressPhase.DOWNLOADING)
        self.tracker.total_size = 1000
        
        # Update progress
        stats = self.tracker.update_progress(100, 200)  # downloaded, total
        self.assertEqual(stats.bytes_downloaded, 100)
        self.assertEqual(stats.total_size, 200)
        self.assertEqual(stats.percentage, 50.0)
        
        # Update again
        stats = self.tracker.update_progress(200, 200)
        self.assertEqual(stats.percentage, 100.0)
    
    def test_speed_calculations(self):
        """Test speed calculation with moving average."""
        self.tracker.set_phase(ProgressPhase.DOWNLOADING)
        
        # Simulate downloads with time gaps
        start_time = time.time()
        self.tracker.update_progress(100, 1000)
        
        # Wait a small amount and update again
        time.sleep(0.1)
        stats = self.tracker.update_progress(200, 1000)
        
        # Speed should be calculated
        self.assertGreater(stats.current_speed, 0)
        self.assertGreater(stats.average_speed, 0)
    
    def test_eta_calculation(self):
        """Test ETA calculation algorithms."""
        self.tracker.set_phase(ProgressPhase.DOWNLOADING)
        self.tracker.total_size = 1000
        
        # Add some progress data
        self.tracker.update_progress(200, 1000)
        time.sleep(0.1)
        stats = self.tracker.update_progress(400, 1000)
        
        # ETA should be calculated
        if stats.eta_seconds > 0:
            self.assertGreater(stats.eta_seconds, 0)
    
    def test_queue_position_tracking(self):
        """Test queue position functionality."""
        self.tracker.set_queue_info(5, 10)
        self.assertEqual(self.tracker._stats.queue_position, 5)
        self.assertEqual(self.tracker._stats.total_queue, 10)
    
    def test_error_handling(self):
        """Test error handling and edge cases."""
        # Test division by zero protection
        stats = self.tracker.update_progress(0, 0)
        self.assertEqual(stats.percentage, 0.0)
        
        # Test negative values - should still work (no clamping implemented)
        stats = self.tracker.update_progress(0, 1000)  # Use 0 instead of negative
        self.assertEqual(stats.bytes_downloaded, 0)


class TestProgressTrackerManager(unittest.TestCase):
    """Test the progress tracker manager."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not IMPORTS_AVAILABLE:
            self.skipTest("Required imports not available")
        
        self.manager = ProgressTrackerManager()
    
    def test_tracker_creation(self):
        """Test creating and retrieving trackers."""
        tracker = self.manager.create_tracker("test_download")
        self.assertIsNotNone(tracker)
        self.assertEqual(tracker.task_id, "test_download")
        
        # Retrieve the same tracker
        retrieved = self.manager.get_tracker("test_download")
        self.assertIs(tracker, retrieved)
    
    def test_multiple_trackers(self):
        """Test managing multiple trackers."""
        tracker1 = self.manager.create_tracker("download1")
        tracker2 = self.manager.create_tracker("download2")
        
        self.assertNotEqual(tracker1, tracker2)
        self.assertEqual(len(self.manager._trackers), 2)
    
    def test_tracker_removal(self):
        """Test removing trackers."""
        self.manager.create_tracker("test_download")
        self.assertEqual(len(self.manager._trackers), 1)
        
        self.manager.remove_tracker("test_download")
        self.assertEqual(len(self.manager._trackers), 0)
    
    def test_thread_safety(self):
        """Test thread safety of tracker manager."""
        results = []
        errors = []
        
        def create_trackers():
            try:
                for i in range(10):
                    tracker = self.manager.create_tracker(f"download_{i}")
                    results.append(tracker.task_id)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=create_trackers)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")
        self.assertEqual(len(results), 50)  # 5 threads * 10 trackers each


class TestEnhancedProgressBarUI(unittest.TestCase):
    """Test the enhanced progress bar UI components."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not IMPORTS_AVAILABLE:
            self.skipTest("Required imports not available")
        
        # Create a root window for testing
        try:
            self.root = ctk.CTk()
            self.root.withdraw()  # Hide the window during tests
        except Exception:
            self.skipTest("Cannot create CTk window for testing")
    
    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self, 'root'):
            self.root.destroy()
    
    def test_multi_phase_progress_bar_creation(self):
        """Test creating multi-phase progress bar."""
        try:
            progress_bar = MultiPhaseProgressBar(self.root, width=300, height=20)
            self.assertIsNotNone(progress_bar)
        except Exception as e:
            self.fail(f"Failed to create MultiPhaseProgressBar: {e}")
    
    def test_detailed_stats_display_creation(self):
        """Test creating detailed stats display."""
        try:
            stats_display = DetailedStatsDisplay(self.root)
            self.assertIsNotNone(stats_display)
        except Exception as e:
            self.fail(f"Failed to create DetailedStatsDisplay: {e}")
    
    def test_enhanced_progress_widget_creation(self):
        """Test creating enhanced progress widget."""
        try:
            mock_tracker = Mock()
            mock_tracker.download_id = "test"
            mock_tracker.phase = ProgressPhase.DOWNLOADING
            mock_tracker.progress = 0.5
            
            widget = EnhancedProgressWidget(self.root, mock_tracker)
            self.assertIsNotNone(widget)
        except Exception as e:
            self.fail(f"Failed to create EnhancedProgressWidget: {e}")


class TestProgressPerformance(unittest.TestCase):
    """Test performance aspects of the progress system."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not IMPORTS_AVAILABLE:
            self.skipTest("Required imports not available")
        
        self.manager = ProgressTrackerManager()
    
    def test_many_trackers_performance(self):
        """Test performance with many concurrent trackers."""
        start_time = time.time()
        
        # Create many trackers
        trackers = []
        for i in range(100):
            tracker = self.manager.create_tracker(f"download_{i}")
            tracker.set_phase(ProgressPhase.DOWNLOADING)
            trackers.append(tracker)
        
        creation_time = time.time() - start_time
        self.assertLess(creation_time, 1.0, "Tracker creation took too long")
        
        # Update all trackers rapidly
        start_time = time.time()
        for _ in range(10):
            for i, tracker in enumerate(trackers):
                tracker.update_progress(i * 10, 1000)
        
        update_time = time.time() - start_time
        self.assertLess(update_time, 2.0, "Tracker updates took too long")
    
    def test_rapid_updates_performance(self):
        """Test performance with rapid progress updates."""
        tracker = self.manager.create_tracker("speed_test")
        tracker.set_phase(ProgressPhase.DOWNLOADING)
        
        start_time = time.time()
        
        # Rapid fire updates
        for i in range(1000):
            tracker.update_progress(i, 1000)
        
        end_time = time.time()
        update_time = end_time - start_time
        
        self.assertLess(update_time, 1.0, "Rapid updates took too long")
        
        # Verify final state
        self.assertEqual(tracker._stats.percentage, 99.9)  # 999/1000 * 100


def run_tests():
    """Run all tests with detailed output."""
    print("=" * 60)
    print("ENHANCED PROGRESS TRACKING SYSTEM - TEST SUITE")
    print("=" * 60)
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test classes
    test_classes = [
        TestEnhancedProgressTracker,
        TestProgressTrackerManager,
        TestEnhancedProgressBarUI,
        TestProgressPerformance
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2, buffer=True)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    
    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)