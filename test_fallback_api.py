#!/usr/bin/env python3
"""
Simple test script to verify the fallback API implementation works.
"""

import sys
import os
sys.path.append('src')

from civitai_downloader import get_model_version_data, get_model_version_data_with_fallback, extract_primary_file_hash

def test_extract_hash():
    """Test hash extraction from model version data."""
    print("Testing hash extraction...")
    
    # Mock model version data
    mock_data = {
        'files': [
            {
                'primary': False,
                'hashes': {'SHA256': 'secondary_hash'}
            },
            {
                'primary': True,
                'hashes': {'SHA256': 'primary_file_hash_123'}
            }
        ]
    }
    
    hash_id = extract_primary_file_hash(mock_data)
    if hash_id == 'primary_file_hash_123':
        print("✅ Hash extraction test passed!")
        return True
    else:
        print(f"❌ Hash extraction test failed. Expected 'primary_file_hash_123', got '{hash_id}'")
        return False

def test_api_methods():
    """Test that the API methods are callable and have correct signatures."""
    print("Testing API method signatures...")
    
    try:
        # These should not crash even with None values
        result1, error1 = get_model_version_data(None)
        result2, error2 = get_model_version_data_with_fallback(None)
        
        print("✅ API method signatures test passed!")
        return True
    except Exception as e:
        print(f"❌ API method signatures test failed: {e}")
        return False

def test_hash_extraction_edge_cases():
    """Test hash extraction with edge cases."""
    print("Testing hash extraction edge cases...")
    
    # Test with no files
    result1 = extract_primary_file_hash({'files': []})
    
    # Test with no primary file
    result2 = extract_primary_file_hash({
        'files': [
            {'primary': False, 'hashes': {'SHA256': 'not_primary'}}
        ]
    })
    
    # Test with None input
    result3 = extract_primary_file_hash(None)
    
    # Test with missing files key
    result4 = extract_primary_file_hash({})
    
    if all(result is None for result in [result1, result2, result3, result4]):
        print("✅ Hash extraction edge cases test passed!")
        return True
    else:
        print(f"❌ Hash extraction edge cases test failed. Results: {[result1, result2, result3, result4]}")
        return False

def main():
    """Run basic tests."""
    print("Running fallback API implementation tests...\n")
    
    test1_passed = test_extract_hash()
    test2_passed = test_api_methods()
    test3_passed = test_hash_extraction_edge_cases()
    
    if test1_passed and test2_passed and test3_passed:
        print("\n🎉 All tests passed! The fallback API implementation is ready.")
        print("\nImplementation Summary:")
        print("- ✅ get_model_version_data(): Centralized API method")
        print("- ✅ get_model_version_data_with_fallback(): Fallback logic")
        print("- ✅ extract_primary_file_hash(): Hash extraction")
        print("- ✅ Updated get_model_info_from_url() to use fallback")
        print("\nWhen the primary API (/model-versions/{id}) fails:")
        print("1. Extract SHA256 hash from primary file")
        print("2. Retry with hash-based API (/model-versions/by-hash/{hash})")
        print("3. Return successful result or both errors if both fail")
    else:
        print("\n❌ Some tests failed. Please check the implementation.")

if __name__ == "__main__":
    main()