"""
Thumbnail Manager for Civitai Model Downloader

This module handles thumbnail creation, caching, and management for model previews
in the history display. It extracts thumbnails from downloaded model images and
provides efficient caching and fallback mechanisms.
"""

import os
import json
import hashlib
import threading
from typing import Optional, Tuple, Dict, List
from dataclasses import dataclass
from pathlib import Path
import time

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("Warning: PIL/Pillow not available. Thumbnails will be disabled.")


@dataclass
class ThumbnailInfo:
    """Information about a thumbnail"""
    original_path: str
    thumbnail_path: str
    size: Tuple[int, int]
    created_time: float
    file_hash: str


class ThumbnailCache:
    """
    Manages thumbnail cache with size limits and cleanup
    """
    
    def __init__(self, cache_dir: str = "thumbnails", max_size_mb: int = 100):
        self.cache_dir = Path(cache_dir)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.cache_index_file = self.cache_dir / "cache_index.json"
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Cache index
        self._cache_index: Dict[str, ThumbnailInfo] = {}
        
        # Enhanced eviction settings
        self.cleanup_threshold = 0.8  # Start cleanup at 80% of max size
        self.target_size_after_cleanup = 0.6  # Clean down to 60% of max size
        self.min_access_interval = 3600  # 1 hour minimum between accesses to avoid constant cleanup
        
        # Access tracking
        self._access_times: Dict[str, float] = {}
        
        # Initialize cache directory and load index
        self._init_cache_directory()
        self._load_cache_index()
        
    def _init_cache_directory(self):
        """Initialize cache directory structure"""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Create subdirectories for different sizes
            for size in ['64x64', '128x128', '256x256']:
                (self.cache_dir / size).mkdir(exist_ok=True)
                
        except Exception as e:
            print(f"Error initializing thumbnail cache directory: {e}")
    
    def _load_cache_index(self):
        """Load cache index from disk"""
        try:
            if self.cache_index_file.exists():
                with open(self.cache_index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
                    
                self._cache_index = {
                    key: ThumbnailInfo(**info) for key, info in index_data.items()
                }
                
                # Clean up orphaned entries
                self._cleanup_orphaned_entries()
                
        except Exception as e:
            print(f"Error loading thumbnail cache index: {e}")
            self._cache_index = {}
    
    def _save_cache_index(self):
        """Save cache index to disk"""
        try:
            index_data = {
                key: {
                    'original_path': info.original_path,
                    'thumbnail_path': info.thumbnail_path,
                    'size': info.size,
                    'created_time': info.created_time,
                    'file_hash': info.file_hash
                }
                for key, info in self._cache_index.items()
            }
            
            with open(self.cache_index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, indent=2)
                
        except Exception as e:
            print(f"Error saving thumbnail cache index: {e}")
    
    def _cleanup_orphaned_entries(self):
        """Remove cache entries for files that no longer exist"""
        orphaned_keys = []
        
        for key, info in self._cache_index.items():
            if not os.path.exists(info.original_path) or not os.path.exists(info.thumbnail_path):
                orphaned_keys.append(key)
                # Try to remove the thumbnail file
                try:
                    if os.path.exists(info.thumbnail_path):
                        os.remove(info.thumbnail_path)
                except:
                    pass
        
        for key in orphaned_keys:
            del self._cache_index[key]
    
    def _get_cache_key(self, original_path: str, size: Tuple[int, int]) -> str:
        """Generate cache key for a file and size"""
        file_info = f"{original_path}_{size[0]}x{size[1]}"
        return hashlib.md5(file_info.encode()).hexdigest()
    
    def _get_file_hash(self, file_path: str) -> str:
        """Get hash of file for change detection"""
        try:
            stat = os.stat(file_path)
            return hashlib.md5(f"{stat.st_mtime}_{stat.st_size}".encode()).hexdigest()
        except:
            return ""
    
    def get_thumbnail_path(self, original_path: str, size: Tuple[int, int]) -> Optional[str]:
        """Get thumbnail path if it exists and is up to date"""
        with self._lock:
            cache_key = self._get_cache_key(original_path, size)
            
            if cache_key not in self._cache_index:
                return None
            
            info = self._cache_index[cache_key]
            
            # Check if original file has changed
            current_hash = self._get_file_hash(original_path)
            if current_hash != info.file_hash:
                # File has changed, remove from cache
                try:
                    os.remove(info.thumbnail_path)
                except:
                    pass
                del self._cache_index[cache_key]
                self._access_times.pop(cache_key, None)
                return None
            
            # Check if thumbnail file exists
            if not os.path.exists(info.thumbnail_path):
                del self._cache_index[cache_key]
                self._access_times.pop(cache_key, None)
                return None
            
            # Update access time for LRU tracking
            self._update_access_time(cache_key)
            
            return info.thumbnail_path
    
    def add_thumbnail(self, original_path: str, thumbnail_path: str, size: Tuple[int, int]):
        """Add thumbnail to cache index"""
        with self._lock:
            cache_key = self._get_cache_key(original_path, size)
            file_hash = self._get_file_hash(original_path)
            
            info = ThumbnailInfo(
                original_path=original_path,
                thumbnail_path=thumbnail_path,
                size=size,
                created_time=time.time(),
                file_hash=file_hash
            )
            
            self._cache_index[cache_key] = info
            self._save_cache_index()
    
    def cleanup_old_thumbnails(self, force_aggressive: bool = False):
        """Remove old thumbnails to keep cache size under limit with improved eviction strategy"""
        with self._lock:
            try:
                # Calculate current cache size and collect file info
                total_size = 0
                file_info = []
                current_time = time.time()
                
                for key, info in self._cache_index.items():
                    try:
                        if os.path.exists(info.thumbnail_path):
                            size = os.path.getsize(info.thumbnail_path)
                            total_size += size
                            
                            # Get last access time (default to creation time if never accessed)
                            last_access = self._access_times.get(key, info.created_time)
                            
                            # Calculate score for eviction (higher score = more likely to evict)
                            age_score = current_time - info.created_time  # Age since creation
                            access_score = current_time - last_access    # Time since last access
                            size_score = size / (1024 * 1024)           # Size in MB
                            
                            # Combined eviction score (weighted)
                            eviction_score = (age_score * 0.3) + (access_score * 0.5) + (size_score * 0.2)
                            
                            file_info.append({
                                'key': key,
                                'info': info,
                                'size': size,
                                'eviction_score': eviction_score,
                                'last_access': last_access
                            })
                    except Exception as e:
                        print(f"Error processing thumbnail {info.thumbnail_path}: {e}")
                        continue
                
                # Determine if cleanup is needed
                cleanup_threshold_bytes = self.max_size_bytes * self.cleanup_threshold
                target_size_bytes = self.max_size_bytes * self.target_size_after_cleanup
                
                if total_size > cleanup_threshold_bytes or force_aggressive:
                    # Sort by eviction score (highest first - most likely to evict)
                    file_info.sort(key=lambda x: x['eviction_score'], reverse=True)
                    
                    removed_count = 0
                    removed_size = 0
                    target_size = target_size_bytes if not force_aggressive else self.max_size_bytes * 0.3
                    
                    for item in file_info:
                        if total_size <= target_size:
                            break
                        
                        try:
                            # Remove the thumbnail file
                            os.remove(item['info'].thumbnail_path)
                            
                            # Update tracking
                            total_size -= item['size']
                            removed_size += item['size']
                            removed_count += 1
                            
                            # Remove from index and access tracking
                            del self._cache_index[item['key']]
                            self._access_times.pop(item['key'], None)
                            
                        except Exception as e:
                            print(f"Error removing thumbnail {item['info'].thumbnail_path}: {e}")
                    
                    if removed_count > 0:
                        self._save_cache_index()
                        print(f"Thumbnail cache cleanup: removed {removed_count} files, "
                              f"freed {removed_size / (1024*1024):.1f} MB, "
                              f"cache size now {total_size / (1024*1024):.1f} MB")
                
                return total_size
                
            except Exception as e:
                print(f"Error during thumbnail cache cleanup: {e}")
                return 0
    
    def _update_access_time(self, cache_key: str):
        """Update access time for a cache entry"""
        current_time = time.time()
        last_access = self._access_times.get(cache_key, 0)
        
        # Only update if enough time has passed to avoid excessive updates
        if current_time - last_access > self.min_access_interval / 10:  # Update every 6 minutes max
            self._access_times[cache_key] = current_time
    
    def get_cache_usage_info(self) -> Dict[str, any]:
        """Get detailed cache usage information"""
        with self._lock:
            total_size = 0
            file_count = 0
            oldest_file_age = 0
            newest_file_age = float('inf')
            current_time = time.time()
            
            for info in self._cache_index.values():
                try:
                    if os.path.exists(info.thumbnail_path):
                        size = os.path.getsize(info.thumbnail_path)
                        total_size += size
                        file_count += 1
                        
                        age = current_time - info.created_time
                        oldest_file_age = max(oldest_file_age, age)
                        newest_file_age = min(newest_file_age, age)
                except:
                    pass
            
            return {
                'total_size_mb': total_size / (1024 * 1024),
                'total_size_bytes': total_size,
                'max_size_mb': self.max_size_bytes / (1024 * 1024),
                'usage_percent': (total_size / self.max_size_bytes) * 100 if self.max_size_bytes > 0 else 0,
                'file_count': file_count,
                'oldest_file_age_hours': oldest_file_age / 3600,
                'newest_file_age_hours': newest_file_age / 3600 if newest_file_age != float('inf') else 0,
                'cleanup_threshold_mb': (self.max_size_bytes * self.cleanup_threshold) / (1024 * 1024),
                'needs_cleanup': total_size > (self.max_size_bytes * self.cleanup_threshold)
            }


class ThumbnailManager:
    """
    Main thumbnail manager that handles creation and retrieval of thumbnails
    """
    
    def __init__(self, cache_dir: str = "thumbnails"):
        self.cache = ThumbnailCache(cache_dir)
        self._generation_lock = threading.Lock()
        
        # Default thumbnail sizes
        self.default_sizes = {
            'small': (64, 64),
            'medium': (128, 128),
            'large': (256, 256)
        }
        
        # Supported image formats
        self.supported_formats = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
        
    def _is_image_file(self, file_path: str) -> bool:
        """Check if file is a supported image format"""
        return Path(file_path).suffix.lower() in self.supported_formats
    
    def _find_model_images(self, model_dir: str) -> List[str]:
        """Find all image files in a model directory"""
        if not os.path.exists(model_dir):
            return []
        
        images = []
        try:
            for file in os.listdir(model_dir):
                file_path = os.path.join(model_dir, file)
                if os.path.isfile(file_path) and self._is_image_file(file_path):
                    images.append(file_path)
            
            # Sort by filename for consistent ordering
            images.sort()
            
        except Exception as e:
            print(f"Error finding images in {model_dir}: {e}")
        
        return images
    
    def _create_thumbnail(self, image_path: str, output_path: str, size: Tuple[int, int]) -> bool:
        """Create thumbnail from image file"""
        if not PIL_AVAILABLE:
            return False
        
        try:
            with Image.open(image_path) as img:
                # Convert to RGB if necessary (handles PNG with alpha, etc.)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Create thumbnail with good quality
                img.thumbnail(size, Image.Resampling.LANCZOS)
                
                # If image is smaller than target size, center it on white background
                if img.size != size:
                    background = Image.new('RGB', size, (255, 255, 255))
                    paste_x = (size[0] - img.size[0]) // 2
                    paste_y = (size[1] - img.size[1]) // 2
                    background.paste(img, (paste_x, paste_y))
                    img = background
                
                # Save thumbnail
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                img.save(output_path, 'JPEG', quality=85, optimize=True)
                
                return True
                
        except Exception as e:
            print(f"Error creating thumbnail for {image_path}: {e}")
            return False
    
    def get_model_thumbnail(self, model_dir: str, size: str = 'medium') -> Optional[str]:
        """
        Get thumbnail for a model directory.
        
        Args:
            model_dir: Path to model directory
            size: Thumbnail size ('small', 'medium', 'large')
            
        Returns:
            Path to thumbnail file or None if not available
        """
        if not PIL_AVAILABLE:
            return None
        
        if size not in self.default_sizes:
            size = 'medium'
        
        target_size = self.default_sizes[size]
        
        # Find the first image in the model directory
        images = self._find_model_images(model_dir)
        if not images:
            return None
        
        # Use the first image as the thumbnail source
        source_image = images[0]
        
        # Check if thumbnail already exists in cache
        existing_thumbnail = self.cache.get_thumbnail_path(source_image, target_size)
        if existing_thumbnail:
            return existing_thumbnail
        
        # Generate new thumbnail
        with self._generation_lock:
            # Double-check cache (another thread might have created it)
            existing_thumbnail = self.cache.get_thumbnail_path(source_image, target_size)
            if existing_thumbnail:
                return existing_thumbnail
            
            # Create thumbnail
            size_str = f"{target_size[0]}x{target_size[1]}"
            filename = f"{hashlib.md5(source_image.encode()).hexdigest()}.jpg"
            output_path = self.cache.cache_dir / size_str / filename
            
            if self._create_thumbnail(source_image, str(output_path), target_size):
                self.cache.add_thumbnail(source_image, str(output_path), target_size)
                return str(output_path)
        
        return None
    
    def get_fallback_thumbnail(self, size: str = 'medium') -> Optional[str]:
        """
        Get path to fallback thumbnail for models without images.
        
        Creates a simple placeholder image if it doesn't exist.
        """
        if not PIL_AVAILABLE:
            return None
        
        if size not in self.default_sizes:
            size = 'medium'
        
        target_size = self.default_sizes[size]
        size_str = f"{target_size[0]}x{target_size[1]}"
        fallback_path = self.cache.cache_dir / size_str / "fallback.jpg"
        
        # Create fallback thumbnail if it doesn't exist
        if not fallback_path.exists():
            try:
                # Create simple placeholder
                img = Image.new('RGB', target_size, (240, 240, 240))
                
                # Add some visual elements if possible
                try:
                    from PIL import ImageDraw, ImageFont
                    draw = ImageDraw.Draw(img)
                    
                    # Draw border
                    draw.rectangle([2, 2, target_size[0]-3, target_size[1]-3], outline=(200, 200, 200), width=2)
                    
                    # Add text
                    text = "No\nImage"
                    text_bbox = draw.textbbox((0, 0), text, align="center")
                    text_width = text_bbox[2] - text_bbox[0]
                    text_height = text_bbox[3] - text_bbox[1]
                    
                    x = (target_size[0] - text_width) // 2
                    y = (target_size[1] - text_height) // 2
                    
                    draw.text((x, y), text, fill=(160, 160, 160), align="center")
                    
                except ImportError:
                    # If ImageDraw/ImageFont not available, just use plain background
                    pass
                
                # Save fallback
                fallback_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(str(fallback_path), 'JPEG', quality=85)
                
            except Exception as e:
                print(f"Error creating fallback thumbnail: {e}")
                return None
        
        return str(fallback_path) if fallback_path.exists() else None
    
    def cleanup_cache(self, force_aggressive: bool = False):
        """Clean up old thumbnails to free space"""
        return self.cache.cleanup_old_thumbnails(force_aggressive=force_aggressive)
    
    def preload_thumbnails(self, model_dirs: List[str], size: str = 'medium'):
        """
        Preload thumbnails for multiple model directories in background.
        
        Args:
            model_dirs: List of model directory paths
            size: Thumbnail size to generate
        """
        def preload_worker():
            for model_dir in model_dirs:
                try:
                    self.get_model_thumbnail(model_dir, size)
                except Exception as e:
                    print(f"Error preloading thumbnail for {model_dir}: {e}")
        
        # Run in background thread
        thread = threading.Thread(target=preload_worker, daemon=True)
        thread.start()
    
    def get_memory_usage(self) -> float:
        """Get estimated memory usage of thumbnail cache in MB"""
        try:
            cache_info = self.cache.get_cache_usage_info()
            return cache_info.get('total_size_mb', 0)
        except:
            return 0
    
    def should_cleanup(self) -> bool:
        """Check if cache cleanup is recommended"""
        try:
            cache_info = self.cache.get_cache_usage_info()
            return cache_info.get('needs_cleanup', False)
        except:
            return False
        
    def get_cache_stats(self) -> Dict[str, any]:
        """Get comprehensive thumbnail cache statistics"""
        try:
            # Get basic cache info
            cache_info = self.cache.get_cache_usage_info()
            
            # Add additional PIL availability info
            cache_info.update({
                'cache_directory': str(self.cache.cache_dir),
                'pil_available': PIL_AVAILABLE,
                'total_thumbnails': len(self.cache._cache_index)
            })
            
            return cache_info
        except Exception as e:
            print(f"Error getting cache stats: {e}")
            return {
                'total_thumbnails': 0,
                'total_size_mb': 0,
                'cache_directory': str(self.cache.cache_dir) if hasattr(self, 'cache') else 'unknown',
                'pil_available': PIL_AVAILABLE,
                'usage_percent': 0,
                'needs_cleanup': False
            }


# Global thumbnail manager instance
thumbnail_manager = ThumbnailManager()