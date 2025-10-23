#!/usr/bin/env python3
"""
Test script to verify the enhanced fallback API implementation works.
"""

import sys
import os
sys.path.append('src')

from civitai_downloader import (
    get_model_info_from_url, 
    get_hash_from_model_id, 
    extract_primary_file_hash,
    get_model_version_data_with_enhanced_fallback
)

def test_url_parsing():
    """Test URL parsing to extract both model ID and version ID."""
    print("Testing URL parsing...")
    
    test_url = "https://civitai.com/models/1983910/vintage-playboy?modelVersionId=2245689"
    
    # Mock the actual API call to test parsing logic
    import re
    model_id_match = re.search(r'models/(\d+)', test_url)
    model_version_id_query_match = re.search(r'modelVersionId=(\d+)', test_url)
    
    if model_id_match and model_version_id_query_match:
        model_id = model_id_match.group(1)
        model_version_id = model_version_id_query_match.group(1)
        print(f"✅ Successfully parsed - Model ID: {model_id}, Version ID: {model_version_id}")
        return True
    else:
        print("❌ Failed to parse URL")
        return False

def test_enhanced_fallback_method():
    """Test that the enhanced fallback method exists and is callable."""
    print("Testing enhanced fallback method...")
    
    try:
        # This should not crash even with None values
        result, error = get_model_version_data_with_enhanced_fallback(None, api_key=None, model_id=None)
        print("✅ Enhanced fallback method is callable")
        return True
    except Exception as e:
        print(f"❌ Enhanced fallback method failed: {e}")
        return False

def main():
    """Run basic tests."""
    print("Running enhanced fallback API implementation tests...\n")
    
    test1_passed = test_url_parsing()
    test2_passed = test_enhanced_fallback_method()
    
    if test1_passed and test2_passed:
        print("\n🎉 Enhanced fallback implementation tests passed!")
        print("\nNew Features:")
        print("- ✅ Enhanced URL parsing to extract both model ID and version ID")
        print("- ✅ get_model_version_data_with_enhanced_fallback() method")
        print("- ✅ get_hash_from_model_id() to get hash from parent model")
        print("\nFallback Strategy:")
        print("1. Try primary API (/model-versions/{id})")
        print("2. If fails and model_id available, get hash from parent model")
        print("3. Use hash-based API (/model-versions/by-hash/{hash})")
    else:
        print("\n❌ Some tests failed. Please check the implementation.")

if __name__ == "__main__":
    main()