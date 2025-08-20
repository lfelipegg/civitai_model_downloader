#!/usr/bin/env python3
"""
Test script for the history manager functionality
"""

from src.history_manager import HistoryManager
import json
import os

def test_history_manager():
    print("Testing history manager...")
    
    # Initialize history manager
    hm = HistoryManager("test_history.json")
    
    # Load test metadata
    try:
        with open('test/metadata.json', 'r', encoding='utf-8') as f:
            test_model = json.load(f)
        print("✓ Loaded test metadata")
    except Exception as e:
        print(f"✗ Failed to load test metadata: {e}")
        return False
    
    # Test adding entry
    try:
        entry_id = hm.add_download_entry(test_model, './test_download_path')
        print(f"✓ Added entry with ID: {entry_id}")
    except Exception as e:
        print(f"✗ Failed to add entry: {e}")
        return False
    
    # Test retrieving all downloads
    try:
        downloads = hm.get_all_downloads()
        print(f"✓ Total downloads in history: {len(downloads)}")
    except Exception as e:
        print(f"✗ Failed to retrieve downloads: {e}")
        return False
    
    # Test search functionality
    try:
        search_results = hm.search_downloads('Retro')
        print(f"✓ Search results for 'Retro': {len(search_results)}")
        
        search_results2 = hm.search_downloads('LORA')
        print(f"✓ Search results for 'LORA': {len(search_results2)}")
    except Exception as e:
        print(f"✗ Failed to search: {e}")
        return False
    
    # Test stats
    try:
        stats = hm.get_stats()
        print(f"✓ Stats: Total={stats['total_downloads']}, Size={stats['total_size']} bytes")
        print(f"  Model types: {stats['model_types']}")
        print(f"  Base models: {stats['base_models']}")
    except Exception as e:
        print(f"✗ Failed to get stats: {e}")
        return False
    
    # Test delete functionality
    try:
        if hm.delete_download_entry(entry_id, delete_files=False):
            print("✓ Successfully deleted entry")
        else:
            print("✗ Failed to delete entry")
            return False
    except Exception as e:
        print(f"✗ Error during delete: {e}")
        return False
    
    # Clean up test file
    try:
        if os.path.exists("test_history.json"):
            os.remove("test_history.json")
        print("✓ Cleaned up test files")
    except Exception as e:
        print(f"⚠ Warning: Could not clean up test files: {e}")
    
    print("✓ All history manager tests passed!")
    return True

if __name__ == "__main__":
    success = test_history_manager()
    if not success:
        exit(1)
    print("\n🎉 History manager implementation is working correctly!")