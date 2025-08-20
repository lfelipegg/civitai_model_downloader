import os
import requests
import re
import time
import hashlib
from functools import wraps
import shutil

CIVITAI_BASE_URL = "https://civitai.com/api/v1"

def retry(exceptions, tries=4, delay=3, backoff=2):
    """
    Retry calling the decorated function using an exponential backoff.
    Args:
        exceptions: An exception or tuple of exceptions to catch.
        tries: The maximum number of attempts.
        delay: Initial delay between retries in seconds.
        backoff: Multiplier applied to delay after each retry.
    """
    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except exceptions as e:
                    print(f"Error: {e}, Retrying in {mdelay} seconds...")
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs) # Last attempt
        return f_retry
    return deco_retry

def get_model_info_from_url(url, api_key):
    """
    Extracts model information from a Civitai URL.
    """
    model_id_match = re.search(r'models/(\d+)', url)
    model_version_id_path_match = re.search(r'model-versions/(\d+)', url)
    model_version_id_query_match = re.search(r'modelVersionId=(\d+)', url)

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    model_version_id = None

    if model_version_id_query_match:
        model_version_id = model_version_id_query_match.group(1)
    elif model_version_id_path_match:
        model_version_id = model_version_id_path_match.group(1)

    if model_version_id:
        endpoint = f"{CIVITAI_BASE_URL}/model-versions/{model_version_id}"
        print(f"Fetching specific model version info from: {endpoint}")
        try:
            @retry(exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException), tries=3, delay=2, backoff=2)
            def _get_response_with_retry(url, headers):
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                return response

            response = _get_response_with_retry(endpoint, headers)
            return response.json(), None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return None, "Unauthorized: Invalid API Key or missing authentication."
            elif e.response.status_code == 404:
                return None, f"Not Found: Model version with ID {model_version_id} not found."
            elif e.response.status_code == 429:
                return None, "Too Many Requests: Rate limit exceeded. Please wait and try again."
            else:
                return None, f"HTTP Error: {e.response.status_code} - {e.response.reason}"
        except requests.exceptions.RequestException as e:
            return None, f"Network Error: Could not connect to Civitai API. {e}"
    elif model_id_match:
        model_id = model_id_match.group(1)
        try:
            endpoint = f"{CIVITAI_BASE_URL}/models/{model_id}"
            print(f"Fetching model info from: {endpoint}")
            
            @retry(exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException), tries=3, delay=2, backoff=2)
            def _get_model_response_with_retry(url, headers):
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                return response

            response = _get_model_response_with_retry(endpoint, headers)
            model_info = response.json()
            if model_info and model_info.get('modelVersions'):
                # Find the latest version by checking the 'createdAt' or 'updatedAt' field,
                # or assume the first one is the latest if no specific ordering is guaranteed by the API
                # For now, keeping the existing logic of assuming the first is latest, as per original code.
                latest_version = model_info['modelVersions'][0]
                endpoint = f"{CIVITAI_BASE_URL}/model-versions/{latest_version['id']}"
                print(f"Fetching latest model version info from: {endpoint}")
                response = _get_model_response_with_retry(endpoint, headers) # Use retry for this call too
                return response.json(), None
            return None, f"No model versions found for model ID: {model_id}"
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return None, "Unauthorized: Invalid API Key or missing authentication."
            elif e.response.status_code == 404:
                return None, f"Not Found: Model with ID {model_id} not found."
            elif e.response.status_code == 429:
                return None, "Too Many Requests: Rate limit exceeded. Please wait and try again."
            else:
                return None, f"HTTP Error: {e.response.status_code} - {e.response.reason}"
        except requests.exceptions.RequestException as e:
            return None, f"Network Error: Could not connect to Civitai API. {e}"
    return None, "Invalid Civitai URL provided."

def download_file(url, path, api_key=None, progress_callback=None, expected_sha256=None, stop_event=None, pause_event=None):
    """Downloads a file from a URL to a specified path with progress updates and SHA256 verification."""
    print(f"Downloading {url} to {path}")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    file_mode = 'wb'
    current_size = 0

    if os.path.exists(path):
        current_size = os.path.getsize(path)
        headers['Range'] = f"bytes={current_size}-"
        file_mode = 'ab'
        print(f"Resuming download for {os.path.basename(path)} from {current_size} bytes.")
    else:
        print(f"Starting new download for {os.path.basename(path)}.")

    try:
        @retry(exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException), tries=3, delay=2, backoff=2)
        def _download_response_with_retry(url, headers, stream):
            response = requests.get(url, stream=stream, headers=headers)
            response.raise_for_status()
            return response
        
        response = _download_response_with_retry(url, headers, True)
    except requests.exceptions.HTTPError as e:
        # If server doesn't support Range and returns 416, restart download
        if e.response.status_code == 416: # Range Not Satisfiable
            print(f"Server does not support range requests or range is invalid. Restarting download for {os.path.basename(path)}.")
            os.remove(path) # Delete incomplete file
            return download_file(url, path, api_key, progress_callback, expected_sha256) # Restart without range header
        return f"HTTP Error during download: {e.response.status_code} - {e.response.reason}"
    except requests.exceptions.RequestException as e:
        return f"Network Error during download: {e}"

    total_size = int(response.headers.get('content-length', 0))
    # If resuming, total_size from header is the remaining size, add current_size to get actual total
    if file_mode == 'ab':
        total_size += current_size

    bytes_downloaded = current_size
    start_time = time.time()
    
    sha256_hash = hashlib.sha256()
    # If resuming, need to hash existing content first
    if current_size > 0 and file_mode == 'ab':
        with open(path, 'rb') as f_existing:
            for chunk in iter(lambda: f_existing.read(8192), b''):
                sha256_hash.update(chunk)

    with open(path, file_mode) as f:
        for chunk in response.iter_content(chunk_size=8192):
            if stop_event and stop_event.is_set():
                print(f"Download of {os.path.basename(path)} interrupted.")
                return "Download interrupted by user."
            
            if pause_event and pause_event.is_set():
                print(f"Download of {os.path.basename(path)} paused. Waiting to resume...")
                pause_event.wait() # Block until cleared
                print(f"Download of {os.path.basename(path)} resumed.")

            f.write(chunk)
            sha256_hash.update(chunk)
            bytes_downloaded += len(chunk)
            if progress_callback:
                elapsed_time = time.time() - start_time
                speed = (bytes_downloaded / elapsed_time) if elapsed_time > 0 else 0
                progress_callback(bytes_downloaded, total_size, speed)
    print(f"Downloaded {os.path.basename(path)}")

    if expected_sha256:
        actual_sha256 = sha256_hash.hexdigest()
        if actual_sha256.lower() != expected_sha256.lower():
            os.remove(path) # Delete the corrupted file
            return f"SHA256 mismatch for {os.path.basename(path)}: Expected {expected_sha256}, got {actual_sha256}. File deleted."
        print(f"SHA256 verification successful for {os.path.basename(path)}")
    return None # Indicate success

    if expected_sha256:
        actual_sha256 = sha256_hash.hexdigest()
        if actual_sha256.lower() != expected_sha256.lower():
            os.remove(path) # Delete the corrupted file
            raise ValueError(f"SHA256 mismatch for {os.path.basename(path)}: Expected {expected_sha256}, got {actual_sha256}. File deleted.")
        print(f"SHA256 verification successful for {os.path.basename(path)}")

def save_metadata(metadata, path):
    """Saves metadata to a JSON file."""
    import json
    print(f"Saving metadata to {path}")
    with open(path, 'w') as f:
        json.dump(metadata, f, indent=4)
    print(f"Metadata saved to {os.path.basename(path)}")

def is_model_downloaded(model_info, download_base_path):
    """
    Checks if a model and its metadata are already downloaded.
    """
    model_name = model_info['model']['name']
    model_version_name = model_info['name']
    base_model = model_info['baseModel']
    model_type = model_info['model']['type']

    safe_model_name = sanitize_filename(model_name)
    safe_model_version_name = sanitize_filename(model_version_name)
    safe_base_model = sanitize_filename(base_model)
    safe_model_type = sanitize_filename(model_type)

    target_dir = os.path.join(
        download_base_path,
        safe_base_model,
        safe_model_type,
        safe_model_name,
        safe_model_version_name
    )

    # Check for main model file
    model_file = None
    for file in model_info['files']:
        if file['type'] == 'Model':
            model_file = file
            break
    
    if not model_file:
        print(f"Warning: No main model file information found for {model_name} v{model_version_name}. Cannot verify download.")
        return False # Cannot verify if main file info is missing

    model_filepath = os.path.join(target_dir, model_file['name'])
    if not os.path.exists(model_filepath):
        return False
    
    # Basic size check (optional, but good for quick verification)
    # Be cautious with exact size match due to potential server differences or partial downloads
    # For now, just check if file exists and has some size
    if os.path.getsize(model_filepath) == 0:
        return False

    # Check for metadata file
    metadata_filepath = os.path.join(target_dir, "metadata.json")
    if not os.path.exists(metadata_filepath):
        return False
    
    # Optional: More rigorous SHA256 check for existing file
    expected_sha256 = model_file['hashes'].get('SHA256')
    if expected_sha256:
        try:
            with open(model_filepath, 'rb') as f:
                actual_sha256 = hashlib.sha256(f.read()).hexdigest()
            if actual_sha256.lower() != expected_sha256.lower():
                print(f"SHA256 mismatch for existing file {os.path.basename(model_filepath)}. Re-download is needed.")
                os.remove(model_filepath) # Remove the mismatched file to force re-download
                return False
        except Exception as e:
            print(f"Error verifying SHA256 for {os.path.basename(model_filepath)}: {e}. Re-download is needed.")
            return False

    print(f"Model {model_name} v{model_version_name} appears to be already downloaded.")
    return True

def check_disk_space(path, required_bytes):
    """
    Checks if there is enough disk space in the given path.
    Returns None if sufficient, or an error message if insufficient.
    """
    try:
        total, used, free = shutil.disk_usage(path)
        if free < required_bytes:
            return f"Insufficient disk space. Required: {required_bytes / (1024**3):.2f} GB, Available: {free / (1024**3):.2f} GB."
        return None
    except Exception as e:
        return f"Error checking disk space: {e}"

def download_civitai_model(model_info, download_base_path, api_key, progress_callback=None, stop_event=None, pause_event=None):
    """
    Downloads a Civitai model, its images, and saves metadata.
    Creates the directory structure: ./{{base_model}}/{{type}}/{{Model_name}}/{{Model_version}}/
    """
    model_name = model_info['model']['name']
    model_version_name = model_info['name']
    base_model = model_info['baseModel']
    model_type = model_info['model']['type']

    # Sanitize names for directory creation
    safe_model_name = sanitize_filename(model_name)
    safe_model_version_name = sanitize_filename(model_version_name)
    safe_base_model = sanitize_filename(base_model)
    safe_model_type = sanitize_filename(model_type)

    target_dir = os.path.join(
        download_base_path,
        safe_base_model,
        safe_model_type,
        safe_model_name,
        safe_model_version_name
    )
    os.makedirs(target_dir, exist_ok=True)
    print(f"Created directory: {target_dir}")

    # Download model file
    model_file = None
    for file in model_info['files']:
        if file['type'] == 'Model': # Assuming 'Model' type is the main model file
            model_file = file
            break

    if model_file:
        model_download_url = model_file['downloadUrl']
        model_filename = model_file['name']
        expected_sha256 = model_file['hashes'].get('SHA256') # Get SHA256 hash

        # Check disk space before downloading
        required_bytes = model_file['sizeKB'] * 1024 # Convert KB to bytes
        disk_space_error = check_disk_space(target_dir, required_bytes)
        if disk_space_error:
            return disk_space_error

        download_error = download_file(model_download_url, os.path.join(target_dir, model_filename), api_key, progress_callback=progress_callback, expected_sha256=expected_sha256, stop_event=stop_event, pause_event=pause_event)
        if download_error:
            return f"Failed to download model file: {download_error}"
    else:
        return f"No main model file found for {model_name} v{model_version_name}"

    # Download images
    if 'images' in model_info:
        for i, image in enumerate(model_info['images']):
            image_url = image['url']
            image_name = f"image_{i}{os.path.splitext(image_url)[1]}" # Get extension from URL
            # For images, we can pass a specific callback or use the general one.
            # Let's use the general one for now, as GUI can differentiate based on context if needed.
            download_error = download_file(image_url, os.path.join(target_dir, image_name), api_key, progress_callback=progress_callback, stop_event=stop_event, pause_event=pause_event)
            if download_error:
                print(f"Warning: Failed to download image {image_name}: {download_error}")

    # Save metadata
    save_metadata(model_info, os.path.join(target_dir, "metadata.json"))

    # Generate HTML report
    from src.html_generator import generate_html_report
    generate_html_report(model_info, target_dir)
    return None # Indicate success

def sanitize_filename(name):
    """Sanitizes a string to be used as a filename or directory name."""
    return re.sub(r'[\\/:*?"<>|]', '_', name)