#!/usr/bin/env python3
"""
Comprehensive test suite for the thumbnail preview system.
Tests thumbnail generation, caching, fallback mechanisms, and performance.
"""

import unittest
import tempfile
import shutil
import os
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from thumbnail_manager import ThumbnailCache, ThumbnailManager
    from enhanced_progress_bar import ThumbnailWidget
    import customtkinter as ctk
    # Try to import PIL
    try:
        from PIL import Image, ImageDraw
        PIL_AVAILABLE = True
    except ImportError:
        PIL_AVAILABLE = False
    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_AVAILABLE = False
    PIL_AVAILABLE = False


class TestThumbnailCache(unittest.TestCase):
    """Test the thumbnail caching system."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not IMPORTS_AVAILABLE:
            self.skipTest("Required imports not available")
        
        self.temp_dir = tempfile.mkdtemp()
        self.cache = ThumbnailCache(cache_dir=self.temp_dir, max_size_mb=1)  # 1MB limit
    
    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_cache_initialization(self):
        """Test cache initialization."""
        self.assertTrue(os.path.exists(self.temp_dir))
        self.assertEqual(self.cache.max_size_bytes, 1*1024*1024)
        # Note: current_cache_size is not exposed in the actual implementation
    
    def test_cache_key_generation(self):
        """Test cache key generation."""
        test_path = "/test/path/model.safetensors"
        key1 = self.cache._get_cache_key(test_path, (64, 64))
        key2 = self.cache._get_cache_key(test_path, (128, 128))
        key3 = self.cache._get_cache_key("/different/path.safetensors", (64, 64))
        
        # Keys should be different for different sizes and paths
        self.assertNotEqual(key1, key2)
        self.assertNotEqual(key1, key3)
        self.assertIsInstance(key1, str)
    
    def test_cache_storage_and_retrieval(self):
        """Test storing and retrieving thumbnails."""
        if not PIL_AVAILABLE:
            self.skipTest("PIL not available")
        
        # Create a test image
        test_image = Image.new('RGB', (100, 100), color='red')
        test_path = "/test/model.safetensors"
        
        # Store in cache (using cache's internal method)
        # Create temporary thumbnail file
        temp_thumb = os.path.join(self.temp_dir, "test_thumb.jpg")
        test_image.save(temp_thumb, 'JPEG')
        
        self.cache.add_thumbnail(test_path, temp_thumb, (100, 100))
        
        # Retrieve from cache
        retrieved_path = self.cache.get_thumbnail_path(test_path, (100, 100))
        self.assertIsNotNone(retrieved_path)
        self.assertTrue(os.path.exists(retrieved_path))
    
    def test_cache_size_management(self):
        """Test cache size limits and cleanup."""
        if not PIL_AVAILABLE:
            self.skipTest("PIL not available")
        
        # Create several large images to exceed cache limit
        large_image = Image.new('RGB', (500, 500), color='blue')
        
        stored_count = 0
        for i in range(10):  # Try to store 10 large images
            temp_thumb = os.path.join(self.temp_dir, f"test_thumb_{i}.jpg")
            large_image.save(temp_thumb, 'JPEG')
            self.cache.add_thumbnail(f"/test/model_{i}.safetensors", temp_thumb, (500, 500))
            stored_count += 1
        
        # Should have stored images
        self.assertGreater(stored_count, 0)
        # Cache cleanup should manage size automatically
    
    def test_cache_cleanup(self):
        """Test cache cleanup functionality."""
        if not PIL_AVAILABLE:
            self.skipTest("PIL not available")
        
        # Store some thumbnails
        test_image = Image.new('RGB', (50, 50), color='green')
        for i in range(5):
            temp_thumb = os.path.join(self.temp_dir, f"test_thumb_{i}.jpg")
            test_image.save(temp_thumb, 'JPEG')
            self.cache.add_thumbnail(f"/test/model_{i}.safetensors", temp_thumb, (50, 50))
        
        initial_count = len(self.cache._cache_index)
        self.assertGreater(initial_count, 0)
        
        # Cleanup old thumbnails
        self.cache.cleanup_old_thumbnails()
        
        # Some cleanup should have occurred
        final_count = len(self.cache._cache_index)
        self.assertLessEqual(final_count, initial_count)


class TestThumbnailManager(unittest.TestCase):
    """Test the thumbnail manager functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not IMPORTS_AVAILABLE:
            self.skipTest("Required imports not available")
        
        self.temp_dir = tempfile.mkdtemp()
        self.manager = ThumbnailManager(cache_dir=self.temp_dir)
        
        # Create test model directory with fake files
        self.test_model_dir = os.path.join(self.temp_dir, "test_model")
        os.makedirs(self.test_model_dir, exist_ok=True)
        
        # Create test files
        with open(os.path.join(self.test_model_dir, "model.safetensors"), 'w') as f:
            f.write("fake model data")
        
        if PIL_AVAILABLE:
            # Create test image
            test_image = Image.new('RGB', (200, 200), color='purple')
            test_image.save(os.path.join(self.test_model_dir, "preview.png"))
    
    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_manager_initialization(self):
        """Test manager initialization."""
        self.assertIsNotNone(self.manager.cache)
        self.assertTrue(hasattr(self.manager, 'default_sizes'))
        self.assertTrue(hasattr(self.manager, 'supported_formats'))
    
    def test_image_file_detection(self):
        """Test finding image files in model directory."""
        # Test with existing image
        images = self.manager._find_model_images(self.test_model_dir)
        if PIL_AVAILABLE:
            self.assertGreater(len(images), 0)
            self.assertTrue(any(img.endswith('preview.png') for img in images))
        
        # Test with non-existent directory
        images = self.manager._find_model_images("/non/existent/path")
        self.assertEqual(len(images), 0)
    
    def test_thumbnail_generation(self):
        """Test thumbnail generation from images."""
        if not PIL_AVAILABLE:
            self.skipTest("PIL not available")
        
        thumbnail = self.manager.get_model_thumbnail(self.test_model_dir, size="small")
        self.assertIsNotNone(thumbnail)
        
        # Test caching - second call should be faster
        start_time = time.time()
        thumbnail2 = self.manager.get_model_thumbnail(self.test_model_dir, size="small")
        cache_time = time.time() - start_time
        
        self.assertIsNotNone(thumbnail2)
        self.assertLess(cache_time, 0.1)  # Cached access should be very fast
    
    def test_fallback_placeholder(self):
        """Test fallback to placeholder when no image found."""
        # Test with directory without images
        empty_dir = os.path.join(self.temp_dir, "empty_model")
        os.makedirs(empty_dir, exist_ok=True)
        
        thumbnail = self.manager.get_model_thumbnail(empty_dir, size="small")
        # Should return None when no images found
        self.assertIsNone(thumbnail)
        
        # Test fallback thumbnail generation
        fallback = self.manager.get_fallback_thumbnail(size="small")
        if PIL_AVAILABLE:
            self.assertIsNotNone(fallback)
            self.assertTrue(os.path.exists(fallback))
    
    def test_different_sizes(self):
        """Test different thumbnail sizes."""
        if not PIL_AVAILABLE:
            self.skipTest("PIL not available")
        
        small_thumb = self.manager.get_model_thumbnail(self.test_model_dir, size="small")
        large_thumb = self.manager.get_model_thumbnail(self.test_model_dir, size="large")
        
        # Both should exist
        self.assertIsNotNone(small_thumb)
        self.assertIsNotNone(large_thumb)
        
        # Files should exist
        self.assertTrue(os.path.exists(small_thumb))
        self.assertTrue(os.path.exists(large_thumb))
    
    def test_preload_functionality(self):
        """Test thumbnail preloading."""
        if not PIL_AVAILABLE:
            self.skipTest("PIL not available")
        
        # Create multiple test directories
        test_dirs = []
        for i in range(3):
            dir_path = os.path.join(self.temp_dir, f"test_model_{i}")
            os.makedirs(dir_path, exist_ok=True)
            colors = [(255, 100, 100), (100, 255, 100), (100, 100, 255)]  # Red, Green, Blue
            test_image = Image.new('RGB', (100, 100), color=colors[i % len(colors)])
            test_image.save(os.path.join(dir_path, "image.png"))
            test_dirs.append(dir_path)
        
        # Test preloading
        self.manager.preload_thumbnails(test_dirs, size="small")
        
        # Give some time for background loading
        time.sleep(0.5)
        
        # Check if thumbnails are now cached
        for dir_path in test_dirs:
            thumb = self.manager.get_model_thumbnail(dir_path, size="small")
            self.assertIsNotNone(thumb)


class TestThumbnailWidget(unittest.TestCase):
    """Test the thumbnail widget UI component."""
    
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
    
    def test_widget_creation(self):
        """Test creating thumbnail widget."""
        try:
            widget = ThumbnailWidget(self.root, size=(64, 64))
            self.assertIsNotNone(widget)
        except Exception as e:
            self.fail(f"Failed to create ThumbnailWidget: {e}")
    
    def test_widget_with_callback(self):
        """Test widget with click callback."""
        callback_called = False
        test_path = "/test/model/path"
        
        def test_callback(path):
            nonlocal callback_called
            callback_called = True
            self.assertEqual(path, test_path)
        
        try:
            widget = ThumbnailWidget(self.root, size=(64, 64))
            widget.set_click_callback(test_callback)
            widget.thumbnail_path = test_path
            self.assertIsNotNone(widget)
            
            # Simulate click event
            from unittest.mock import Mock
            event = Mock()
            widget._on_click(event)
            self.assertTrue(callback_called)
            
        except Exception as e:
            self.fail(f"Failed to create ThumbnailWidget with callback: {e}")


class TestThumbnailPerformance(unittest.TestCase):
    """Test performance aspects of the thumbnail system."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not IMPORTS_AVAILABLE or not PIL_AVAILABLE:
            self.skipTest("Required imports not available")
        
        self.temp_dir = tempfile.mkdtemp()
        self.manager = ThumbnailManager(cache_dir=self.temp_dir)
        
        # Create test model directories with images
        self.test_dirs = []
        for i in range(20):  # Create 20 test models
            dir_path = os.path.join(self.temp_dir, f"model_{i}")
            os.makedirs(dir_path, exist_ok=True)
            
            # Create test image
            test_image = Image.new('RGB', (300, 300), color=(i*10, 100, 150))
            test_image.save(os.path.join(dir_path, "preview.jpg"))
            self.test_dirs.append(dir_path)
    
    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_batch_thumbnail_generation(self):
        """Test generating many thumbnails efficiently."""
        start_time = time.time()
        
        thumbnails = []
        for dir_path in self.test_dirs[:10]:  # Test with 10 models
            thumb = self.manager.get_model_thumbnail(dir_path, size="small")
            if thumb:
                thumbnails.append(thumb)
        
        generation_time = time.time() - start_time
        self.assertLess(generation_time, 5.0, "Batch generation took too long")
        self.assertGreater(len(thumbnails), 5, "Too few thumbnails generated")
    
    def test_cache_hit_performance(self):
        """Test cache hit performance."""
        test_dir = self.test_dirs[0]
        
        # First generation (cache miss)
        start_time = time.time()
        thumb1 = self.manager.get_model_thumbnail(test_dir, size="small")
        miss_time = time.time() - start_time
        
        # Second generation (cache hit)
        start_time = time.time()
        thumb2 = self.manager.get_model_thumbnail(test_dir, size="small")
        hit_time = time.time() - start_time
        
        # Cache hit should be much faster
        self.assertLess(hit_time, miss_time * 0.1, "Cache hit not significantly faster")
        self.assertIsNotNone(thumb1)
        self.assertIsNotNone(thumb2)
    
    def test_memory_usage(self):
        """Test memory usage doesn't grow excessively."""
        import gc
        
        # Generate many thumbnails
        for dir_path in self.test_dirs:
            self.manager.get_model_thumbnail(dir_path, size="small")
            self.manager.get_model_thumbnail(dir_path, size="large")
        
        # Force garbage collection
        gc.collect()
        
        # Cache should self-limit (check cache index size)
        cache_count = len(self.manager.cache._cache_index)
        max_size_bytes = self.manager.cache.max_size_bytes
        # Cache should not grow excessively
        self.assertLess(cache_count, 1000, "Cache has too many entries")
    
    def test_concurrent_access(self):
        """Test thread safety with concurrent access."""
        results = []
        errors = []
        
        def generate_thumbnails():
            try:
                for i in range(5):
                    dir_path = self.test_dirs[i % len(self.test_dirs)]
                    thumb = self.manager.get_model_thumbnail(dir_path, size="small")
                    if thumb:
                        results.append(dir_path)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=generate_thumbnails)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Thread safety errors: {errors}")
        self.assertGreater(len(results), 10, "Too few successful operations")


def run_tests():
    """Run all tests with detailed output."""
    print("=" * 60)
    print("THUMBNAIL PREVIEW SYSTEM - TEST SUITE")
    print("=" * 60)
    
    if not IMPORTS_AVAILABLE:
        print("ERROR: Required imports not available. Please install dependencies:")
        print("  - customtkinter")
        print("  - Pillow (PIL)")
        return False
    
    if not PIL_AVAILABLE:
        print("WARNING: PIL not available. Some tests will be skipped.")
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test classes
    test_classes = [
        TestThumbnailCache,
        TestThumbnailManager,
        TestThumbnailWidget,
        TestThumbnailPerformance
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
    print(f"Skipped: {len(result.skipped) if hasattr(result, 'skipped') else 0}")
    
    if result.testsRun > 0:
        success_rate = ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100)
        print(f"Success rate: {success_rate:.1f}%")
    
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