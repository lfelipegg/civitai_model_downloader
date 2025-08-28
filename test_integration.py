#!/usr/bin/env python3
"""
Integration test suite for the enhanced Civitai Model Downloader features.
Tests the complete integration of enhanced progress indicators and thumbnail previews.
"""

import unittest
import tempfile
import shutil
import os
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys
import json

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from progress_tracker import ProgressPhase, ProgressTrackerManager, progress_manager
    from thumbnail_manager import ThumbnailManager, thumbnail_manager
    from enhanced_progress_bar import EnhancedProgressWidget, ThumbnailWidget
    import customtkinter as ctk
    
    # Try to import PIL for full functionality
    try:
        from PIL import Image
        PIL_AVAILABLE = True
    except ImportError:
        PIL_AVAILABLE = False
    
    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_AVAILABLE = False
    PIL_AVAILABLE = False


class TestIntegratedFeatures(unittest.TestCase):
    """Test integrated enhanced features working together."""
    
    def setUp(self):
        """Set up test environment."""
        if not IMPORTS_AVAILABLE:
            self.skipTest("Required imports not available")
        
        # Create temporary directories
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = os.path.join(self.temp_dir, "models")
        self.thumbnails_dir = os.path.join(self.temp_dir, "thumbnails")
        os.makedirs(self.models_dir, exist_ok=True)
        os.makedirs(self.thumbnails_dir, exist_ok=True)
        
        # Create test model directories with mock data
        self.test_models = []
        for i in range(3):
            model_dir = os.path.join(self.models_dir, f"test_model_{i}")
            os.makedirs(model_dir, exist_ok=True)
            
            # Create mock model file
            model_file = os.path.join(model_dir, "model.safetensors")
            with open(model_file, 'w') as f:
                f.write(f"mock model data {i}")
            
            # Create mock preview image if PIL available
            if PIL_AVAILABLE:
                preview_file = os.path.join(model_dir, "preview.png")
                colors = [(255, 100, 100), (100, 255, 100), (100, 100, 255)]  # Red, Green, Blue
                test_image = Image.new('RGB', (512, 512), color=colors[i % len(colors)])
                test_image.save(preview_file)
            
            self.test_models.append(model_dir)
        
        # Initialize managers with test directories
        self.progress_manager = ProgressTrackerManager()
        self.thumbnail_manager = ThumbnailManager(cache_dir=self.thumbnails_dir)
    
    def tearDown(self):
        """Clean up test environment."""
        if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
            # Clean up thumbnail manager first
            if hasattr(self, 'thumbnail_manager'):
                try:
                    self.thumbnail_manager.cleanup()
                except:
                    pass
            
            # Force garbage collection to release file handles
            import gc
            gc.collect()
            
            # Windows-specific file cleanup with retries
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    shutil.rmtree(self.temp_dir)
                    break
                except (OSError, PermissionError) as e:
                    if attempt == max_attempts - 1:
                        print(f"Warning: Could not fully clean up temp directory: {e}")
                        # Try to clean up individual files
                        try:
                            for root, dirs, files in os.walk(self.temp_dir, topdown=False):
                                for name in files:
                                    try:
                                        os.remove(os.path.join(root, name))
                                    except:
                                        pass
                                for name in dirs:
                                    try:
                                        os.rmdir(os.path.join(root, name))
                                    except:
                                        pass
                            os.rmdir(self.temp_dir)
                        except:
                            pass
                    else:
                        time.sleep(0.1)  # Brief delay for Windows file handles
    
    def test_progress_tracker_with_thumbnails(self):
        """Test progress tracking and thumbnail generation working together."""
        if not PIL_AVAILABLE:
            self.skipTest("PIL not available for thumbnail generation")
        
        # Simulate downloading multiple models with progress tracking
        download_results = []
        
        for i, model_dir in enumerate(self.test_models):
            download_id = f"download_{i}"
            
            # Create progress tracker
            tracker = self.progress_manager.create_tracker(download_id, total_size=1024*1024)
            
            # Simulate download phases
            tracker.set_phase(ProgressPhase.CONNECTING)
            time.sleep(0.1)
            
            tracker.set_phase(ProgressPhase.DOWNLOADING)
            
            # Simulate progress updates
            for progress in [0, 256*1024, 512*1024, 768*1024, 1024*1024]:
                stats = tracker.update_progress(progress)
                self.assertIsNotNone(stats)
            
            # Complete download
            tracker.complete()
            
            # Generate thumbnail for the completed download
            thumbnail_path = self.thumbnail_manager.get_model_thumbnail(model_dir, 'medium')
            self.assertIsNotNone(thumbnail_path, f"Thumbnail generation failed for {model_dir}")
            self.assertTrue(os.path.exists(thumbnail_path))
            
            download_results.append({
                'download_id': download_id,
                'model_dir': model_dir,
                'thumbnail_path': thumbnail_path,
                'final_stats': tracker.get_formatted_stats()
            })
        
        # Verify all downloads completed successfully
        self.assertEqual(len(download_results), 3)
        
        # Verify thumbnails were generated for all models
        for result in download_results:
            self.assertIsNotNone(result['thumbnail_path'])
            self.assertTrue(os.path.exists(result['thumbnail_path']))
    
    def test_ui_components_integration(self):
        """Test UI components working together."""
        try:
            # Create a test root window
            root = ctk.CTk()
            root.withdraw()  # Hide during testing
            
            # Test creating enhanced progress widget
            progress_widget = EnhancedProgressWidget(root, task_id="test_download")
            self.assertIsNotNone(progress_widget)
            
            # Test creating thumbnail widget
            thumbnail_widget = ThumbnailWidget(root, size=(64, 64))
            self.assertIsNotNone(thumbnail_widget)
            
            # Test setting thumbnail if PIL available
            if PIL_AVAILABLE and self.test_models:
                thumbnail_path = self.thumbnail_manager.get_model_thumbnail(
                    self.test_models[0], 'small'
                )
                if thumbnail_path:
                    thumbnail_widget.set_thumbnail(thumbnail_path)
            
            # Test progress widget updates
            mock_tracker = self.progress_manager.create_tracker("ui_test", 1000)
            mock_tracker.set_phase(ProgressPhase.DOWNLOADING)
            stats = mock_tracker.update_progress(500)
            
            progress_widget.update_from_tracker(stats)
            
            # Clean up
            root.destroy()
            
        except Exception as e:
            self.fail(f"UI components integration test failed: {e}")
    
    def test_concurrent_operations(self):
        """Test concurrent progress tracking and thumbnail generation."""
        if not PIL_AVAILABLE:
            self.skipTest("PIL not available for thumbnail generation")
        
        results = []
        errors = []
        
        def simulate_download(model_idx):
            try:
                model_dir = self.test_models[model_idx]
                download_id = f"concurrent_download_{model_idx}"
                
                # Create tracker
                tracker = self.progress_manager.create_tracker(download_id, 1024)
                
                # Simulate download
                tracker.set_phase(ProgressPhase.DOWNLOADING)
                for i in range(10):
                    tracker.update_progress(i * 102)  # Simulate progress
                    time.sleep(0.01)  # Small delay
                
                tracker.complete()
                
                # Generate thumbnail concurrently
                thumbnail_path = self.thumbnail_manager.get_model_thumbnail(model_dir, 'small')
                
                results.append({
                    'download_id': download_id,
                    'model_dir': model_dir,
                    'thumbnail_path': thumbnail_path,
                    'success': True
                })
                
            except Exception as e:
                errors.append(e)
        
        # Start multiple concurrent downloads
        threads = []
        for i in range(len(self.test_models)):
            thread = threading.Thread(target=simulate_download, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify results
        self.assertEqual(len(errors), 0, f"Concurrent operation errors: {errors}")
        self.assertEqual(len(results), len(self.test_models))
        
        # Verify all operations succeeded
        for result in results:
            self.assertTrue(result['success'])
            if result['thumbnail_path']:
                self.assertTrue(os.path.exists(result['thumbnail_path']))
    
    def test_cache_performance_integration(self):
        """Test cache performance with both systems."""
        if not PIL_AVAILABLE:
            self.skipTest("PIL not available for thumbnail generation")
        
        # First pass - cache misses
        start_time = time.time()
        first_pass_results = []
        
        for model_dir in self.test_models:
            thumbnail_path = self.thumbnail_manager.get_model_thumbnail(model_dir, 'medium')
            first_pass_results.append(thumbnail_path)
        
        first_pass_time = time.time() - start_time
        
        # Second pass - cache hits
        start_time = time.time()
        second_pass_results = []
        
        for model_dir in self.test_models:
            thumbnail_path = self.thumbnail_manager.get_model_thumbnail(model_dir, 'medium')
            second_pass_results.append(thumbnail_path)
        
        second_pass_time = time.time() - start_time
        
        # Cache hits should be significantly faster
        self.assertLess(second_pass_time, first_pass_time * 0.5, 
                       "Cache hits not significantly faster than misses")
        
        # Results should be consistent
        self.assertEqual(first_pass_results, second_pass_results)
        
        # Get cache statistics
        cache_stats = self.thumbnail_manager.get_cache_stats()
        self.assertGreater(cache_stats['total_thumbnails'], 0)
        self.assertGreater(cache_stats['total_size_mb'], 0)
    
    def test_error_handling_integration(self):
        """Test error handling across integrated systems."""
        # Test progress tracker with invalid data
        tracker = self.progress_manager.create_tracker("error_test", 1000)
        
        # These should not crash
        tracker.update_progress(-100)  # Negative progress
        tracker.update_progress(2000, 1000)  # Progress > total
        stats = tracker.update_progress(0, 0)  # Zero division protection
        
        self.assertIsNotNone(stats)
        
        # Test thumbnail manager with non-existent directory
        thumbnail_path = self.thumbnail_manager.get_model_thumbnail("/non/existent/path", 'small')
        self.assertIsNone(thumbnail_path)
        
        # Test fallback thumbnail
        fallback_path = self.thumbnail_manager.get_fallback_thumbnail('medium')
        if PIL_AVAILABLE:
            self.assertIsNotNone(fallback_path)
    
    def test_memory_management(self):
        """Test memory management across both systems."""
        import gc
        
        # Create many trackers and thumbnails
        trackers = []
        thumbnail_paths = []
        
        for i in range(10):
            # Create tracker
            tracker = self.progress_manager.create_tracker(f"memory_test_{i}", 1000)
            tracker.set_phase(ProgressPhase.DOWNLOADING)
            tracker.update_progress(500)
            trackers.append(tracker)
            
            # Generate thumbnail if possible
            if PIL_AVAILABLE and self.test_models:
                model_dir = self.test_models[i % len(self.test_models)]
                thumbnail_path = self.thumbnail_manager.get_model_thumbnail(model_dir, 'small')
                if thumbnail_path:
                    thumbnail_paths.append(thumbnail_path)
        
        # Clean up trackers
        for i, tracker in enumerate(trackers):
            self.progress_manager.remove_tracker(f"memory_test_{i}")
        
        # Force garbage collection
        gc.collect()
        
        # Verify cleanup
        self.assertEqual(len(self.progress_manager.get_all_trackers()), 0)


def create_integration_demo():
    """Create a demo script showing the integrated features."""
    demo_content = '''#!/usr/bin/env python3
"""
Demo script showcasing the enhanced Civitai Model Downloader features.
Demonstrates enhanced progress indicators and thumbnail previews.
"""

import sys
import os
import time
import threading
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from progress_tracker import ProgressPhase, progress_manager
    from thumbnail_manager import thumbnail_manager
    import customtkinter as ctk
    from enhanced_progress_bar import EnhancedProgressWidget, ThumbnailWidget
    
    print("✓ All imports successful")
    
except ImportError as e:
    print(f"✗ Import error: {e}")
    print("Please ensure all dependencies are installed:")
    print("  pip install customtkinter Pillow")
    sys.exit(1)


class FeatureDemo:
    """Demo class showcasing enhanced features."""
    
    def __init__(self):
        self.root = None
        self.progress_widgets = []
        self.thumbnail_widgets = []
        
    def demo_progress_tracking(self):
        """Demonstrate enhanced progress tracking."""
        print("\\n" + "="*50)
        print("ENHANCED PROGRESS TRACKING DEMO")
        print("="*50)
        
        # Create multiple download simulations
        downloads = [
            {"id": "model_1", "name": "Realistic Vision V6", "size": 5.2 * 1024**3},  # 5.2 GB
            {"id": "model_2", "name": "DreamShaper 8", "size": 2.1 * 1024**3},       # 2.1 GB
            {"id": "model_3", "name": "Epic Realism", "size": 7.8 * 1024**3},        # 7.8 GB
        ]
        
        trackers = []
        for download in downloads:
            print(f"\\nStarting download: {download['name']}")
            
            # Create enhanced progress tracker
            tracker = progress_manager.create_tracker(
                download['id'], 
                total_size=download['size']
            )
            trackers.append(tracker)
            
            # Set queue position
            tracker.set_queue_info(
                position=len(trackers),
                total=len(downloads),
                files_completed=len(trackers)-1,
                files_total=len(downloads)
            )
        
        # Simulate concurrent downloads
        def simulate_download(tracker, name):
            # Connecting phase
            tracker.set_phase(ProgressPhase.CONNECTING)
            time.sleep(0.5)
            print(f"  📡 {name}: Connected to server")
            
            # Downloading phase
            tracker.set_phase(ProgressPhase.DOWNLOADING)
            
            # Simulate download progress with realistic speed variations
            total_size = tracker.total_size
            downloaded = 0
            
            while downloaded < total_size:
                # Simulate network speed variations
                chunk_size = random.randint(1024*50, 1024*200)  # 50-200 KB chunks
                downloaded = min(downloaded + chunk_size, total_size)
                
                # Update progress
                stats = tracker.update_progress(downloaded)
                
                # Print progress every 20%
                if stats.percentage > 0 and int(stats.percentage) % 20 == 0:
                    formatted = tracker.get_formatted_stats()
                    print(f"  📥 {name}: {formatted['downloaded']} - "
                          f"{formatted['current_speed']} - ETA: {formatted['eta']}")
                
                time.sleep(0.1)  # Simulate network delay
            
            # Verifying phase
            tracker.set_phase(ProgressPhase.VERIFYING)
            time.sleep(0.3)
            print(f"  ✅ {name}: Verification complete")
            
            # Complete
            tracker.complete()
            final_stats = tracker.get_formatted_stats()
            print(f"  🎉 {name}: Download completed in {final_stats['elapsed_time']}")
        
        # Start downloads concurrently
        threads = []
        for tracker, download in zip(trackers, downloads):
            thread = threading.Thread(
                target=simulate_download, 
                args=(tracker, download['name'])
            )
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        print("\\n✅ All downloads completed!")
        
        # Clean up
        for download in downloads:
            progress_manager.remove_tracker(download['id'])
    
    def demo_thumbnail_system(self):
        """Demonstrate thumbnail system."""
        print("\\n" + "="*50)
        print("THUMBNAIL PREVIEW SYSTEM DEMO")
        print("="*50)
        
        # Check if PIL is available
        try:
            from PIL import Image
            print("✓ PIL/Pillow available - Full thumbnail functionality enabled")
        except ImportError:
            print("✗ PIL/Pillow not available - Thumbnails will be disabled")
            return
        
        # Create demo model directories
        demo_dir = Path("demo_models")
        demo_dir.mkdir(exist_ok=True)
        
        # Create sample model directories with images
        models = ["realistic_vision", "dreamshaper", "epic_realism"]
        created_dirs = []
        
        for i, model_name in enumerate(models):
            model_dir = demo_dir / model_name
            model_dir.mkdir(exist_ok=True)
            
            # Create sample preview image
            colors = [(255, 100, 100), (100, 255, 100), (100, 100, 255)]  # Red, Green, Blue
            img = Image.new('RGB', (512, 512), color=colors[i % len(colors)])
            img.save(model_dir / "preview.jpg")
            
            # Create dummy model file
            (model_dir / "model.safetensors").write_text(f"Sample model data for {model_name}")
            
            created_dirs.append(str(model_dir))
            print(f"  📁 Created demo model: {model_name}")
        
        # Generate thumbnails
        print("\\n📸 Generating thumbnails...")
        
        for model_dir in created_dirs:
            model_name = Path(model_dir).name
            
            # Generate different sizes
            for size in ['small', 'medium', 'large']:
                thumbnail_path = thumbnail_manager.get_model_thumbnail(model_dir, size)
                if thumbnail_path:
                    print(f"  ✅ {model_name} ({size}): {thumbnail_path}")
                else:
                    print(f"  ✗ {model_name} ({size}): Failed to generate")
        
        # Show cache statistics
        cache_stats = thumbnail_manager.get_cache_stats()
        print(f"\\n📊 Cache Statistics:")
        print(f"  Total thumbnails: {cache_stats['total_thumbnails']}")
        print(f"  Total size: {cache_stats['total_size_mb']:.2f} MB")
        print(f"  Cache directory: {cache_stats['cache_directory']}")
        
        # Test preloading
        print("\\n🚀 Testing thumbnail preloading...")
        start_time = time.time()
        thumbnail_manager.preload_thumbnails(created_dirs, 'medium')
        preload_time = time.time() - start_time
        print(f"  Preloading initiated in {preload_time:.3f}s (runs in background)")
        
        # Clean up demo files
        print("\\n🧹 Cleaning up demo files...")
        import shutil
        shutil.rmtree(demo_dir)
        print("  Demo cleanup complete")
    
    def demo_ui_components(self):
        """Demonstrate UI components."""
        print("\\n" + "="*50)
        print("UI COMPONENTS DEMO")
        print("="*50)
        
        try:
            # Create main window
            self.root = ctk.CTk()
            self.root.title("Enhanced Progress & Thumbnails Demo")
            self.root.geometry("800x600")
            
            # Create demo frame
            demo_frame = ctk.CTkScrollableFrame(self.root)
            demo_frame.pack(fill="both", expand=True, padx=10, pady=10)
            
            # Add title
            title_label = ctk.CTkLabel(
                demo_frame, 
                text="Enhanced Civitai Model Downloader Features",
                font=ctk.CTkFont(size=20, weight="bold")
            )
            title_label.pack(pady=10)
            
            # Enhanced Progress Widgets Section
            progress_section = ctk.CTkLabel(
                demo_frame,
                text="Enhanced Progress Indicators",
                font=ctk.CTkFont(size=16, weight="bold")
            )
            progress_section.pack(pady=(20, 5))
            
            # Create sample progress widgets
            sample_downloads = [
                ("Realistic Vision V6", ProgressPhase.DOWNLOADING, 65.5),
                ("DreamShaper 8", ProgressPhase.VERIFYING, 100.0),
                ("Epic Realism", ProgressPhase.CONNECTING, 0.0),
            ]
            
            for name, phase, progress in sample_downloads:
                # Create enhanced progress widget
                progress_widget = EnhancedProgressWidget(demo_frame, task_id=name)
                progress_widget.pack(fill="x", padx=5, pady=5)
                
                # Create mock stats for demonstration
                mock_stats = {
                    'downloaded': f"{progress:.1f}% Complete",
                    'current_speed': "15.2 MB/s" if phase == ProgressPhase.DOWNLOADING else "0 B/s",
                    'average_speed': "12.8 MB/s" if progress > 0 else "0 B/s",
                    'elapsed_time': "2m 34s" if progress > 0 else "0s",
                    'eta': "1m 15s" if phase == ProgressPhase.DOWNLOADING else "Unknown",
                    'queue_info': f"Position 1/3" if phase != ProgressPhase.VERIFYING else ""
                }
                
                # Update widget
                progress_widget.update_from_formatted_stats(mock_stats, progress, phase)
                self.progress_widgets.append(progress_widget)
            
            # Thumbnail Widgets Section
            thumbnail_section = ctk.CTkLabel(
                demo_frame,
                text="Thumbnail Preview System",
                font=ctk.CTkFont(size=16, weight="bold")
            )
            thumbnail_section.pack(pady=(20, 5))
            
            # Create thumbnail grid
            thumbnail_frame = ctk.CTkFrame(demo_frame)
            thumbnail_frame.pack(fill="x", padx=5, pady=5)
            
            # Create sample thumbnail widgets
            for i in range(3):
                thumbnail_widget = ThumbnailWidget(thumbnail_frame, size=(128, 128))
                thumbnail_widget.grid(row=0, column=i, padx=10, pady=10)
                
                # Set click callback
                def on_thumbnail_click(path):
                    print(f"Thumbnail clicked: {path}")
                
                thumbnail_widget.set_click_callback(on_thumbnail_click)
                self.thumbnail_widgets.append(thumbnail_widget)
            
            # Add instructions
            instructions = ctk.CTkLabel(
                demo_frame,
                text="Instructions:\\n"
                     "• Click ▼ Details to expand progress statistics\\n"
                     "• Progress bars show different phases with colors\\n"
                     "• Thumbnails show hover effects and are clickable\\n"
                     "• All components are responsive and thread-safe",
                font=ctk.CTkFont(size=12),
                anchor="w",
                justify="left"
            )
            instructions.pack(pady=10, anchor="w")
            
            print("✅ UI Demo window created successfully")
            print("   Close the window to continue...")
            
            # Run the UI
            self.root.mainloop()
            
        except Exception as e:
            print(f"✗ UI Demo error: {e}")
            if self.root:
                self.root.destroy()


def main():
    """Run the complete feature demo."""
    print("🚀 Enhanced Civitai Model Downloader - Feature Demo")
    print("This demo showcases the new enhanced progress indicators and thumbnail previews.")
    
    demo = FeatureDemo()
    
    try:
        # Demo progress tracking
        demo.demo_progress_tracking()
        
        # Demo thumbnail system
        demo.demo_thumbnail_system()
        
        # Demo UI components
        print("\\nPress Enter to launch UI demo (close window to continue)...")
        input()
        demo.demo_ui_components()
        
        print("\\n🎉 Demo completed successfully!")
        print("The enhanced features are ready for use in the main application.")
        
    except KeyboardInterrupt:
        print("\\n⏹️ Demo interrupted by user")
    except Exception as e:
        print(f"\\n❌ Demo error: {e}")
    
    print("\\nThank you for trying the enhanced features!")


if __name__ == "__main__":
    import random  # For download simulation
    main()
'''
    
    with open('demo_enhanced_features.py', 'w', encoding='utf-8') as f:
        f.write(demo_content)
    
    print("✅ Integration demo script created: demo_enhanced_features.py")


def run_tests():
    """Run integration tests with detailed output."""
    print("=" * 70)
    print("ENHANCED CIVITAI MODEL DOWNLOADER - INTEGRATION TEST SUITE")
    print("=" * 70)
    
    if not IMPORTS_AVAILABLE:
        print("ERROR: Required imports not available. Please install dependencies:")
        print("  pip install customtkinter")
        print("  pip install Pillow  # For thumbnail functionality")
        return False
    
    if not PIL_AVAILABLE:
        print("WARNING: PIL not available. Thumbnail tests will be limited.")
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add integration tests
    test_class = TestIntegratedFeatures
    tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
    suite.addTests(tests)
    
    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2, buffer=True)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 70)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 70)
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
    
    # Create demo if tests pass
    if result.wasSuccessful():
        print("\n🎉 All integration tests passed!")
        print("\n" + "=" * 70)
        print("CREATING DEMONSTRATION MATERIALS")
        print("=" * 70)
        create_integration_demo()
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)