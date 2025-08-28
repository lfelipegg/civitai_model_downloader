#!/usr/bin/env python3
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
        print("\n" + "="*50)
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
            print(f"\nStarting download: {download['name']}")
            
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
        
        print("\n✅ All downloads completed!")
        
        # Clean up
        for download in downloads:
            progress_manager.remove_tracker(download['id'])
    
    def demo_thumbnail_system(self):
        """Demonstrate thumbnail system."""
        print("\n" + "="*50)
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
        print("\n📸 Generating thumbnails...")
        
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
        print(f"\n📊 Cache Statistics:")
        print(f"  Total thumbnails: {cache_stats['total_thumbnails']}")
        print(f"  Total size: {cache_stats['total_size_mb']:.2f} MB")
        print(f"  Cache directory: {cache_stats['cache_directory']}")
        
        # Test preloading
        print("\n🚀 Testing thumbnail preloading...")
        start_time = time.time()
        thumbnail_manager.preload_thumbnails(created_dirs, 'medium')
        preload_time = time.time() - start_time
        print(f"  Preloading initiated in {preload_time:.3f}s (runs in background)")
        
        # Clean up demo files
        print("\n🧹 Cleaning up demo files...")
        import shutil
        shutil.rmtree(demo_dir)
        print("  Demo cleanup complete")
    
    def demo_ui_components(self):
        """Demonstrate UI components."""
        print("\n" + "="*50)
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
                text="Instructions:\n"
                     "• Click ▼ Details to expand progress statistics\n"
                     "• Progress bars show different phases with colors\n"
                     "• Thumbnails show hover effects and are clickable\n"
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
        print("\nPress Enter to launch UI demo (close window to continue)...")
        input()
        demo.demo_ui_components()
        
        print("\n🎉 Demo completed successfully!")
        print("The enhanced features are ready for use in the main application.")
        
    except KeyboardInterrupt:
        print("\n⏹️ Demo interrupted by user")
    except Exception as e:
        print(f"\n❌ Demo error: {e}")
    
    print("\nThank you for trying the enhanced features!")


if __name__ == "__main__":
    import random  # For download simulation
    main()
