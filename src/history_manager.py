"""
History Manager for Civitai Model Downloader

This module handles the persistent storage and management of download history,
including adding entries, searching, and deleting downloaded models.
"""

import os
import json
import time
import uuid
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Any
import glob


class HistoryManager:
    def __init__(self, history_file_path: str = "download_history.json"):
        """
        Initialize the HistoryManager with the specified history file path.
        
        Args:
            history_file_path: Path to the JSON file storing download history
        """
        self.history_file_path = history_file_path
        self._ensure_history_file_exists()
    
    def _ensure_history_file_exists(self):
        """Create history file if it doesn't exist."""
        if not os.path.exists(self.history_file_path):
            self._save_history({"downloads": []})
    
    def _load_history(self) -> Dict[str, Any]:
        """Load history from JSON file."""
        try:
            with open(self.history_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            # Return empty history if file is corrupted or missing
            return {"downloads": []}
    
    def _save_history(self, history_data: Dict[str, Any]):
        """Save history to JSON file."""
        try:
            with open(self.history_file_path, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving history: {e}")
    
    def add_download_entry(self, model_info: Dict[str, Any], download_path: str) -> str:
        """
        Add a new download entry to history.
        
        Args:
            model_info: Model information from Civitai API
            download_path: Path where the model was downloaded
            
        Returns:
            str: Unique ID of the created entry
        """
        entry_id = str(uuid.uuid4())
        
        # Extract relevant information from model_info
        model_name = model_info.get('model', {}).get('name', 'Unknown Model')
        version_name = model_info.get('name', 'Unknown Version')
        model_type = model_info.get('model', {}).get('type', 'Unknown')
        base_model = model_info.get('baseModel', 'Unknown')
        model_id = model_info.get('modelId', 0)
        version_id = model_info.get('id', 0)
        
        # Calculate total file size
        total_size = 0
        files = model_info.get('files', [])
        for file in files:
            if file.get('type') == 'Model':
                total_size = file.get('sizeKB', 0) * 1024  # Convert to bytes
                break
        
        # Extract trigger words and tags
        trigger_words = model_info.get('trainedWords', [])
        
        # Create history entry
        entry = {
            "id": entry_id,
            "model_id": model_id,
            "version_id": version_id,
            "model_name": model_name,
            "version_name": version_name,
            "model_type": model_type,
            "base_model": base_model,
            "download_path": os.path.abspath(download_path),
            "download_date": datetime.now().isoformat(),
            "file_size": total_size,
            "trigger_words": trigger_words,
            "metadata_path": os.path.join(download_path, "metadata.json"),
            "html_report_path": os.path.join(download_path, "report.html")
        }
        
        # Load current history and add new entry
        history_data = self._load_history()
        history_data["downloads"].append(entry)
        self._save_history(history_data)
        
        return entry_id
    
    def get_all_downloads(self) -> List[Dict[str, Any]]:
        """Get all download entries."""
        history_data = self._load_history()
        return history_data.get("downloads", [])
    
    def search_downloads(self, query: str = "", search_fields: List[str] = None, filters: Dict[str, Any] = None, sort_by: str = "download_date", sort_order: str = "desc") -> List[Dict[str, Any]]:
        """
        Advanced search downloads with filtering and sorting.
        
        Args:
            query: Search query string
            search_fields: Fields to search in. If None, searches in all text fields
            filters: Dictionary of filter criteria
            sort_by: Field to sort by
            sort_order: "asc" or "desc"
            
        Returns:
            List of matching download entries
        """
        if search_fields is None:
            search_fields = ["model_name", "version_name", "model_type", "base_model", "trigger_words"]
        
        downloads = self.get_all_downloads()
        results = []
        
        # Apply text search
        for download in downloads:
            match_found = True
            
            # If query is provided, check text search
            if query.strip():
                query_lower = query.lower()
                text_match = False
                for field in search_fields:
                    value = download.get(field, "")
                    if isinstance(value, list):
                        # Handle list fields like trigger_words
                        if any(query_lower in str(item).lower() for item in value):
                            text_match = True
                            break
                    elif query_lower in str(value).lower():
                        text_match = True
                        break
                match_found = text_match
            
            # Apply filters
            if match_found and filters:
                match_found = self._apply_filters(download, filters)
            
            if match_found:
                results.append(download)
        
        # Apply sorting
        results = self._sort_downloads(results, sort_by, sort_order)
        
        return results
    
    def _apply_filters(self, download: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Apply filter criteria to a download entry."""
        
        # Model type filter
        model_types = filters.get("model_types")
        if not model_types and filters.get("model_type"):
            model_types = [filters.get("model_type")]
        if model_types and download.get("model_type") not in model_types:
            return False
            
        # Base model filter
        base_models = filters.get("base_models")
        if not base_models and filters.get("base_model"):
            base_models = [filters.get("base_model")]
        if base_models and download.get("base_model") not in base_models:
            return False
            
        # Date range filter
        date_from = self._parse_date_filter(filters.get("date_from"))
        date_to = self._parse_date_filter(filters.get("date_to"), is_end=True)
        if date_from or date_to:
            try:
                download_date = datetime.fromisoformat(download.get("download_date", "").replace('Z', '+00:00'))
                if date_from and download_date < date_from:
                    return False
                if date_to and download_date > date_to:
                    return False
            except:
                pass
        
        # File size filter
        size_min = filters.get("size_min")
        size_max = filters.get("size_max")
        if size_min is not None or size_max is not None:
            file_size_mb = download.get("file_size", 0) / (1024 * 1024)
            try:
                size_min_val = float(size_min) if size_min is not None else None
                size_max_val = float(size_max) if size_max is not None else None
            except (TypeError, ValueError):
                size_min_val = None
                size_max_val = None
            if size_min_val is not None and file_size_mb < size_min_val:
                return False
            if size_max_val is not None and file_size_mb > size_max_val:
                return False
        
        # Has trigger words filter
        if filters.get("has_trigger_words") is not None:
            has_triggers = bool(download.get("trigger_words", []))
            if filters["has_trigger_words"] != has_triggers:
                return False
                
        return True

    def _parse_date_filter(self, value, is_end: bool = False) -> Optional[datetime]:
        """Parse a date filter value into a datetime."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            value = value.replace('Z', '+00:00')
            try:
                dt = datetime.fromisoformat(value)
            except ValueError:
                try:
                    dt = datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    return None
            if is_end and len(value) <= 10:
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt
        return None
    
    def _sort_downloads(self, downloads: List[Dict[str, Any]], sort_by: str, sort_order: str) -> List[Dict[str, Any]]:
        """Sort downloads by specified criteria."""
        
        def get_sort_key(download):
            if sort_by == "download_date":
                try:
                    return datetime.fromisoformat(download.get("download_date", "").replace('Z', '+00:00'))
                except:
                    return datetime.min
            elif sort_by == "model_name":
                return download.get("model_name", "").lower()
            elif sort_by == "file_size":
                return download.get("file_size", 0)
            elif sort_by == "model_type":
                return download.get("model_type", "").lower()
            elif sort_by == "base_model":
                return download.get("base_model", "").lower()
            else:
                return download.get(sort_by, "")
        
        reverse = sort_order == "desc"
        return sorted(downloads, key=get_sort_key, reverse=reverse)
    
    def get_filter_options(self) -> Dict[str, List[str]]:
        """Get available filter options from existing downloads."""
        downloads = self.get_all_downloads()
        
        model_types = set()
        base_models = set()
        
        for download in downloads:
            if download.get("model_type"):
                model_types.add(download["model_type"])
            if download.get("base_model"):
                base_models.add(download["base_model"])
        
        return {
            "model_types": sorted(list(model_types)),
            "base_models": sorted(list(base_models))
        }
    
    def delete_download_entry(self, entry_id: str, delete_files: bool = False) -> bool:
        """
        Delete a download entry from history.
        
        Args:
            entry_id: ID of the entry to delete
            delete_files: Whether to also delete the associated files
            
        Returns:
            bool: True if entry was deleted successfully
        """
        history_data = self._load_history()
        downloads = history_data.get("downloads", [])
        
        # Find and remove the entry
        entry_to_delete = None
        for i, download in enumerate(downloads):
            if download.get("id") == entry_id:
                entry_to_delete = downloads.pop(i)
                break
        
        if entry_to_delete is None:
            return False
        
        # Delete files if requested
        if delete_files:
            download_path = entry_to_delete.get("download_path")
            if download_path and os.path.exists(download_path):
                try:
                    shutil.rmtree(download_path)
                    print(f"Deleted files at: {download_path}")
                except Exception as e:
                    print(f"Error deleting files: {e}")
        
        # Save updated history
        self._save_history(history_data)
        return True
    
    def get_download_by_id(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Get a download entry by its ID."""
        downloads = self.get_all_downloads()
        for download in downloads:
            if download.get("id") == entry_id:
                return download
        return None
    
    def scan_and_populate_history(self, base_download_path: str):
        """
        Scan existing download directories and populate history.
        
        Args:
            base_download_path: Base path where downloads are stored
        """
        if not os.path.exists(base_download_path):
            print(f"Download path does not exist: {base_download_path}")
            return
        
        print(f"Scanning for existing downloads in: {base_download_path}")
        
        # Find all metadata.json files in subdirectories
        metadata_files = glob.glob(os.path.join(base_download_path, "*", "*", "*", "*", "metadata.json"))
        
        existing_paths = {download.get("download_path") for download in self.get_all_downloads()}
        
        for metadata_file in metadata_files:
            download_dir = os.path.dirname(metadata_file)
            
            # Skip if already in history
            if download_dir in existing_paths:
                continue
            
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    model_info = json.load(f)
                
                # Add to history
                entry_id = self.add_download_entry(model_info, download_dir)
                print(f"Added to history: {model_info.get('model', {}).get('name', 'Unknown')} - {entry_id}")
                
            except Exception as e:
                print(f"Error processing {metadata_file}: {e}")
        
        print("History scan complete.")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about downloads."""
        downloads = self.get_all_downloads()
        
        if not downloads:
            return {
                "total_downloads": 0,
                "total_size": 0,
                "model_types": {},
                "base_models": {}
            }
        
        total_size = sum(download.get("file_size", 0) for download in downloads)
        
        # Count model types
        model_types = {}
        for download in downloads:
            model_type = download.get("model_type", "Unknown")
            model_types[model_type] = model_types.get(model_type, 0) + 1
        
        # Count base models
        base_models = {}
        for download in downloads:
            base_model = download.get("base_model", "Unknown")
            base_models[base_model] = base_models.get(base_model, 0) + 1
        
        return {
            "total_downloads": len(downloads),
            "total_size": total_size,
            "model_types": model_types,
            "base_models": base_models
        }
    
    def export_history(self, export_path: str) -> bool:
        """Export history to a JSON file."""
        try:
            history_data = self._load_history()
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error exporting history: {e}")
            return False
    
    def import_history(self, import_path: str, merge: bool = True) -> bool:
        """
        Import history from a JSON file.
        
        Args:
            import_path: Path to the JSON file to import
            merge: If True, merge with existing history. If False, replace it.
            
        Returns:
            bool: True if import was successful
        """
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                imported_data = json.load(f)
            
            if merge:
                current_history = self._load_history()
                current_downloads = current_history.get("downloads", [])
                imported_downloads = imported_data.get("downloads", [])
                
                # Create a set of existing IDs to avoid duplicates
                existing_ids = {download.get("id") for download in current_downloads}
                
                # Add only new downloads
                for download in imported_downloads:
                    if download.get("id") not in existing_ids:
                        current_downloads.append(download)
                
                self._save_history(current_history)
            else:
                self._save_history(imported_data)
            
            return True
        except Exception as e:
            print(f"Error importing history: {e}")
            return False
    
    def verify_files_exist(self) -> List[Dict[str, Any]]:
        """
        Verify that files referenced in history still exist.
        
        Returns:
            List of entries with missing files
        """
        downloads = self.get_all_downloads()
        missing_files = []
        
        for download in downloads:
            download_path = download.get("download_path")
            if download_path and not os.path.exists(download_path):
                missing_files.append(download)
        
        return missing_files
    
    def cleanup_missing_entries(self) -> int:
        """
        Remove history entries for files that no longer exist.
        
        Returns:
            int: Number of entries removed
        """
        missing_entries = self.verify_files_exist()
        count = 0
        
        for entry in missing_entries:
            if self.delete_download_entry(entry.get("id"), delete_files=False):
                count += 1
        
        return count
