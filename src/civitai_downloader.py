import os
import requests
import re
import time
import hashlib
import json
from functools import wraps
import shutil
from urllib.parse import urlparse, unquote, parse_qs

CIVITAI_BASE_URL = "https://civitai.com/api/v1"
DESCRIPTION_MEDIA_PATTERN = re.compile(
    r'https?://[^\s>"\'\)\]]+?\.(?:jpe?g|png|gif|webp|mp4|mov|avi|wmv|flv|webm)(?=[\s>"\'\)\]]|$)',
    re.IGNORECASE
)

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

def extract_primary_file_hash(model_version_data):
    """Extract SHA256 hash from the primary file in model version data."""
    if not model_version_data or 'files' not in model_version_data:
        return None
    
    for file_info in model_version_data.get('files', []):
        if file_info.get('primary'):
            return file_info.get('hashes', {}).get('SHA256')
    return None

def get_model_version_data(model_version_id, hash_id=None, api_key=None):
    """
    Fetches model version data from Civitai API with fallback support.
    First tries the regular API, then falls back to hash-based API if available.
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    
    @retry(exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException), tries=3, delay=2, backoff=2)
    def _get_response_with_retry(url, headers):
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response
    
    # If hash_id is provided, use hash-based API directly
    if hash_id:
        endpoint = f"{CIVITAI_BASE_URL}/model-versions/by-hash/{hash_id}"
        print(f"Fetching model version info by hash from: {endpoint}")
        try:
            response = _get_response_with_retry(endpoint, headers)
            return response.json(), None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                return None, "Unauthorized: Invalid API Key or missing authentication."
            elif e.response.status_code == 404:
                return None, f"Not Found: Model version with hash {hash_id} not found."
            elif e.response.status_code == 429:
                return None, "Too Many Requests: Rate limit exceeded. Please wait and try again."
            else:
                return None, f"HTTP Error: {e.response.status_code} - {e.response.reason}"
        except requests.exceptions.RequestException as e:
            return None, f"Network Error: Could not connect to Civitai API. {e}"
    
    # Try regular API first
    endpoint = f"{CIVITAI_BASE_URL}/model-versions/{model_version_id}"
    print(f"Fetching model version info from: {endpoint}")
    try:
        response = _get_response_with_retry(endpoint, headers)
        model_version_data = response.json()
        return model_version_data, None
    except requests.exceptions.HTTPError as e:
        print(f"Primary API failed with HTTP error: {e.response.status_code} - {e.response.reason}")
        
        # Try to fall back to hash-based API if we can get the hash
        if e.response.status_code in [404, 500, 502, 503, 504]:  # Server errors that might benefit from hash fallback
            print("Attempting fallback to hash-based API...")
            
            # For fallback, we need to try a different approach since we don't have the data yet
            # We'll return the error and let the calling function handle the fallback if needed
            if e.response.status_code == 401:
                return None, "Unauthorized: Invalid API Key or missing authentication."
            elif e.response.status_code == 404:
                return None, f"Not Found: Model version with ID {model_version_id} not found."
            elif e.response.status_code == 429:
                return None, "Too Many Requests: Rate limit exceeded. Please wait and try again."
            else:
                return None, f"HTTP Error: {e.response.status_code} - {e.response.reason}"
        else:
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
def get_model_version_data_with_fallback(model_version_id, api_key=None, cached_model_data=None):
    """
    Fetches model version data from Civitai API with hash-based fallback support.
    First tries the regular API, then falls back to hash-based API if available.
    """
    # First attempt with regular API
    model_data, error = get_model_version_data(model_version_id, api_key=api_key)
    
    if model_data:
        return model_data, None
    
    # If primary API failed, try hash-based fallback
    print(f"Primary API failed: {error}")
    
    # Try to get hash from cached data or attempt to fetch it differently
    hash_id = None
    if cached_model_data:
        hash_id = extract_primary_file_hash(cached_model_data)
    
    if hash_id:
        print(f"Attempting hash-based fallback with hash: {hash_id}")
        hash_data, hash_error = get_model_version_data(model_version_id, hash_id=hash_id, api_key=api_key)
        if hash_data:
            print("Hash-based API fallback successful!")
            return hash_data, None
        else:
            print(f"Hash-based fallback also failed: {hash_error}")
    else:
        print("No hash available for fallback, cannot use hash-based API")
    
    # Both attempts failed, return original error
    return None, error
def get_model_version_data_with_enhanced_fallback(model_version_id, api_key=None, model_id=None):
    """
    Enhanced fallback that can use parent model ID when available.
    """
    # First attempt with regular API
    model_data, error = get_model_version_data(model_version_id, api_key=api_key)
    
    if model_data:
        return model_data, None
    
    # If primary API failed and we have a model_id, try to get hash from parent model
    print(f"Primary API failed: {error}")
    
    if model_id:
        print(f"Attempting to get hash from parent model ID: {model_id}")
        hash_id = get_hash_from_model_id(model_id, model_version_id, api_key)
        
        if hash_id:
            print(f"Found hash from parent model: {hash_id}")
            print(f"Attempting hash-based fallback with hash: {hash_id}")
            hash_data, hash_error = get_model_version_data(model_version_id, hash_id=hash_id, api_key=api_key)
            if hash_data:
                print("Hash-based API fallback successful!")
                return hash_data, None
            else:
                print(f"Hash-based fallback also failed: {hash_error}")
    
    # Both attempts failed, return original error
    return None, error

def get_hash_from_model_id(model_id, target_version_id, api_key):
    """
    Gets the hash for a specific model version by fetching the parent model info.
    """
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        
        @retry(exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException), tries=2, delay=1, backoff=1.5)
        def _get_model_with_retry(url, headers):
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response
        
        endpoint = f"{CIVITAI_BASE_URL}/models/{model_id}"
        print(f"Fetching parent model info from: {endpoint}")
        
        response = _get_model_with_retry(endpoint, headers)
        model_info = response.json()
        
        # Find the specific version and extract its hash
        if model_info and model_info.get('modelVersions'):
            for version in model_info['modelVersions']:
                if str(version['id']) == str(target_version_id):
                    return extract_primary_file_hash(version)
        
        print(f"Could not find version {target_version_id} in parent model {model_id}")
        return None
        
    except Exception as e:
        print(f"Error getting hash from parent model {model_id}: {e}")
        return None



def get_model_with_versions(model_id, api_key=None):
    """
    Fetch complete model metadata including available versions.
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    endpoint = f"{CIVITAI_BASE_URL}/models/{model_id}"

    @retry(exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException), tries=3, delay=2, backoff=2)
    def _get_model_response_with_retry(url, headers):
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response

    try:
        response = _get_model_response_with_retry(endpoint, headers)
        return response.json(), None
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return None, "Unauthorized: Invalid API Key or missing authentication."
        elif e.response.status_code == 404:
            return None, f"Not Found: Model with ID {model_id} not found."
        elif e.response.status_code == 429:
            return None, "Too Many Requests: Rate limit exceeded. Please wait and try again."
        return None, f"HTTP Error: {e.response.status_code} - {e.response.reason}"
    except requests.exceptions.RequestException as e:
        return None, f"Network Error: Could not connect to Civitai API. {e}"


def get_collection_models(collection_id, api_key=None):
    """
    Fetch models contained within a collection.

    Returns:
        Tuple[List[Dict], str, Optional[str]]: (models, collection_name, error_message)
    """
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    collection_name = None

    try:
        numeric_collection_id = int(str(collection_id))
    except (TypeError, ValueError):
        return None, "", f"Invalid collection ID: {collection_id}"

    @retry(
        exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException),
        tries=3,
        delay=2,
        backoff=2,
    )
    def _get_with_retry(url, headers, params=None):
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response

    # Attempt to fetch collection metadata for display purposes and existence check.
    trpc_url = "https://civitai.com/api/trpc/collection.getById"
    trpc_params = {"input": json.dumps({"json": {"id": numeric_collection_id}})}

    try:
        metadata_response = _get_with_retry(trpc_url, headers, trpc_params)
        metadata_json = metadata_response.json()
        payload = (
            metadata_json.get("result", {})
            .get("data", {})
            .get("json", {})
            or {}
        )
        collection_info = payload.get("collection") or {}
        permissions = payload.get("permissions") or {}

        if not collection_info:
            if not permissions.get("read", True):
                return (
                    None,
                    "",
                    f"Collection with ID {collection_id} is private or inaccessible.",
                )
            return None, "", f"Not Found: Collection with ID {collection_id} not found."

        collection_name = (
            collection_info.get("name")
            or collection_info.get("title")
            or f"Collection {collection_id}"
        )
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 401:
            return None, "", "Unauthorized: Invalid API Key or missing authentication."
        if status == 404:
            return None, "", f"Not Found: Collection with ID {collection_id} not found."
        if status == 429:
            return None, "", "Too Many Requests: Rate limit exceeded. Please wait and try again."
        return None, "", f"HTTP Error: {status} - {e.response.reason}"
    except requests.exceptions.RequestException as e:
        return None, "", f"Network Error: Could not connect to Civitai API. {e}"

    models = []
    cursor = None
    seen_cursors = set()

    while True:
        params = {
            "collectionIds": numeric_collection_id,
            "limit": 100,
        }
        if cursor:
            params["cursor"] = cursor

        try:
            response = _get_with_retry(f"{CIVITAI_BASE_URL}/models", headers, params)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status == 401:
                return None, "", "Unauthorized: Invalid API Key or missing authentication."
            if status == 404:
                return None, "", f"Not Found: Collection with ID {collection_id} not found."
            if status == 429:
                return None, "", "Too Many Requests: Rate limit exceeded. Please wait and try again."
            return None, "", f"HTTP Error: {status} - {e.response.reason}"
        except requests.exceptions.RequestException as e:
            return None, "", f"Network Error: Could not connect to Civitai API. {e}"

        data = response.json()
        items = data.get("items") or []

        for item in items:
            model_id = item.get("id")
            model_name = item.get("name") or (f"Model {model_id}" if model_id else None)

            version_data = next(
                (
                    version
                    for version in (item.get("modelVersions") or [])
                    if version.get("id")
                ),
                None,
            )

            if not model_id or not version_data:
                continue

            version_id = version_data.get("id")
            models.append(
                {
                    "model_id": str(model_id),
                    "model_name": model_name or f"Model {model_id}",
                    "version_id": str(version_id),
                    "version_name": version_data.get("name")
                    or f"Version {version_id}",
                }
            )

        metadata = data.get("metadata") or {}
        next_cursor = metadata.get("nextCursor")

        if not next_cursor:
            next_page = metadata.get("nextPage")
            if next_page:
                parsed = urlparse(next_page)
                cursor_values = parse_qs(parsed.query).get("cursor") or []
                if cursor_values:
                    next_cursor = cursor_values[0]

        if not next_cursor or next_cursor in seen_cursors:
            break

        seen_cursors.add(next_cursor)
        cursor = next_cursor

    if not models:
        return None, collection_name or f"Collection {collection_id}", "No downloadable models found in this collection."

    return models, collection_name or f"Collection {collection_id}", None


def get_model_info_from_url(url, api_key):
    """
    Extracts model information from a Civitai URL.
    """
    model_id_match = re.search(r'models/(\d+)', url)
    model_version_id_path_match = re.search(r'model-versions/(\d+)', url)
    model_version_id_query_match = re.search(r'modelVersionId=(\d+)', url)

    model_version_id = None
    model_id = None

    if model_version_id_query_match:
        model_version_id = model_version_id_query_match.group(1)
    elif model_version_id_path_match:
        model_version_id = model_version_id_path_match.group(1)
    
    # Extract model ID if present in URL
    if model_id_match:
        model_id = model_id_match.group(1)

    if model_version_id:
        # Use the enhanced fallback that can utilize parent model ID
        if model_id:
            return get_model_version_data_with_enhanced_fallback(model_version_id, api_key=api_key, model_id=model_id)
        else:
            return get_model_version_data_with_fallback(model_version_id, api_key=api_key)
    elif model_id_match:
        model_id = model_id_match.group(1)
        model_data, error = get_model_with_versions(model_id, api_key)
        if error:
            return None, error

        versions = model_data.get('modelVersions') or []
        if versions:
            latest_version_id = versions[0].get('id')
            if latest_version_id:
                return get_model_version_data(latest_version_id, api_key=api_key)
        return None, f"No model versions found for model ID: {model_id}"
    return None, "Invalid Civitai URL provided."

def download_file(url, path, api_key=None, progress_callback=None, expected_sha256=None, stop_event=None, pause_event=None, bandwidth_limit=None):
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
            return download_file(
                url,
                path,
                api_key,
                progress_callback,
                expected_sha256,
                stop_event=stop_event,
                pause_event=pause_event,
                bandwidth_limit=bandwidth_limit
            ) # Restart without range header
        return f"HTTP Error during download: {e.response.status_code} - {e.response.reason}"
    except requests.exceptions.RequestException as e:
        return f"Network Error during download: {e}"

    total_size = int(response.headers.get('content-length', 0))
    # If resuming, total_size from header is the remaining size, add current_size to get actual total
    if file_mode == 'ab':
        total_size += current_size

    bytes_downloaded = current_size
    start_time = time.time()
    last_progress_update = 0  # Track last progress update time for throttling
    
    sha256_hash = hashlib.sha256()
    # If resuming, need to hash existing content first
    if current_size > 0 and file_mode == 'ab':
        with open(path, 'rb') as f_existing:
            for chunk in iter(lambda: f_existing.read(8192), b''):
                sha256_hash.update(chunk)

    limit_window_start = time.time()
    bytes_since_limit = 0

    with open(path, file_mode) as f:
        for chunk in response.iter_content(chunk_size=32768):  # Increased chunk size for better performance
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

            if bandwidth_limit and bandwidth_limit > 0:
                bytes_since_limit += len(chunk)
                elapsed_limit = time.time() - limit_window_start
                if elapsed_limit > 0:
                    expected_time = bytes_since_limit / bandwidth_limit
                    if expected_time > elapsed_limit:
                        time.sleep(expected_time - elapsed_limit)
                if elapsed_limit > 1.0:
                    limit_window_start = time.time()
                    bytes_since_limit = 0
            
            # Throttle progress updates to prevent UI flooding (max 10 updates per second)
            current_time = time.time()
            if progress_callback and (current_time - last_progress_update) >= 0.1:
                elapsed_time = current_time - start_time
                speed = (bytes_downloaded / elapsed_time) if elapsed_time > 0 else 0
                progress_callback(bytes_downloaded, total_size, speed)
                last_progress_update = current_time
    print(f"Downloaded {os.path.basename(path)}")

    if expected_sha256:
        actual_sha256 = sha256_hash.hexdigest()
        if actual_sha256.lower() != expected_sha256.lower():
            os.remove(path) # Delete the corrupted file
            return f"SHA256 mismatch for {os.path.basename(path)}: Expected {expected_sha256}, got {actual_sha256}. File deleted."
        print(f"SHA256 verification successful for {os.path.basename(path)}")
    return None # Indicate success


def save_metadata(metadata, path):
    """Saves metadata to a JSON file."""
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
    
    # Optional: More rigorous SHA256 check for existing file (non-blocking)
    expected_sha256 = model_file['hashes'].get('SHA256')
    if expected_sha256:
        try:
            # Quick file size check first (much faster than hash)
            expected_size = model_file.get('sizeKB', 0) * 1024
            if expected_size > 0 and abs(os.path.getsize(model_filepath) - expected_size) > 1024:  # Allow 1KB tolerance
                print(f"File size mismatch for {os.path.basename(model_filepath)}. Re-download is needed.")
                os.remove(model_filepath)
                return False
            
            # Skip expensive SHA256 verification for now - will be done during download
            # This prevents UI blocking on large files
            print(f"File size check passed for {os.path.basename(model_filepath)}. Assuming file is valid.")
        except Exception as e:
            print(f"Error checking file for {os.path.basename(model_filepath)}: {e}. Re-download is needed.")
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

def download_civitai_model(
    model_info,
    download_base_path,
    api_key,
    progress_callback=None,
    stop_event=None,
    pause_event=None,
    bandwidth_limit=None,
    event_callback=None,
):
    """
    Downloads a Civitai model, its images, description assets, and saves metadata.
    Creates the directory structure: ./{{base_model}}/{{type}}/{{Model_name}}/{{Model_version}}/
    """
    def emit_event(event, phase, **payload):
        if not event_callback:
            return
        try:
            event_callback(event, phase, payload)
        except Exception as exc:
            print(f"Warning: Event callback failed for {phase}: {exc}")

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
            return disk_space_error, None

        emit_event("start", "model_download", filename=model_filename, size_bytes=required_bytes)
        model_download_start = time.monotonic()
        download_error = download_file(
            model_download_url,
            os.path.join(target_dir, model_filename),
            api_key,
            progress_callback=progress_callback,
            expected_sha256=expected_sha256,
            stop_event=stop_event,
            pause_event=pause_event,
            bandwidth_limit=bandwidth_limit
        )
        model_download_elapsed = time.monotonic() - model_download_start
        emit_event("end", "model_download", duration=model_download_elapsed, error=download_error)
        if download_error:
            return f"Failed to download model file: {download_error}", None
    else:
        return f"No main model file found for {model_name} v{model_version_name}", None

    assets_total = 0
    assets_downloaded = 0
    emit_event("start", "asset_download")
    assets_start = time.monotonic()

    # Download images
    if 'images' in model_info:
        for i, image in enumerate(model_info['images']):
            image_url = image['url']
            image_name = f"image_{i}{os.path.splitext(image_url)[1]}" # Get extension from URL
            assets_total += 1
            # For images, we can pass a specific callback or use the general one.
            # Let's use the general one for now, as GUI can differentiate based on context if needed.
            download_error = download_file(
                image_url,
                os.path.join(target_dir, image_name),
                api_key,
                progress_callback=progress_callback,
                stop_event=stop_event,
                pause_event=pause_event,
                bandwidth_limit=bandwidth_limit
            )
            if download_error:
                print(f"Warning: Failed to download image {image_name}: {download_error}")
            else:
                assets_downloaded += 1

    # Ensure description text is present before saving metadata
    description_text = ensure_model_description(model_info, api_key=api_key)

    # Save metadata
    save_metadata(model_info, os.path.join(target_dir, "metadata.json"))

    # Persist description text and any embedded media from the post
    description_assets = save_description_and_assets(
        model_info,
        target_dir,
        description_text=description_text,
        api_key=api_key,
        stop_event=stop_event,
        pause_event=pause_event,
        bandwidth_limit=bandwidth_limit
    )
    if description_assets:
        assets_total += description_assets.get("assets_total", 0)
        assets_downloaded += description_assets.get("assets_downloaded", 0)

    assets_elapsed = time.monotonic() - assets_start
    emit_event(
        "end",
        "asset_download",
        duration=assets_elapsed,
        assets_total=assets_total,
        assets_downloaded=assets_downloaded,
    )

    # Generate HTML report and add to history in background to avoid UI blocking
    import threading
    def background_tasks():
        try:
            # Generate HTML report
            from src.html_generator import generate_html_report
            emit_event("start", "html_report")
            report_start = time.monotonic()
            model_data = None
            model_id = (
                model_info.get('modelId')
                or model_info.get('model', {}).get('id')
            )
            if model_id:
                model_data, error = get_model_with_versions(model_id, api_key)
                if error:
                    print(f"Warning: Failed to fetch model info for report: {error}")
            generate_html_report(model_info, target_dir, model_data=model_data)
            print(f"HTML report generated for {model_name} v{model_version_name}")
            report_elapsed = time.monotonic() - report_start
            emit_event("end", "html_report", duration=report_elapsed)
        except Exception as e:
            print(f"Warning: Failed to generate HTML report: {e}")
            try:
                report_elapsed = time.monotonic() - report_start
            except Exception:
                report_elapsed = 0.0
            emit_event("end", "html_report", duration=report_elapsed, error=str(e))

    # Run background tasks in separate thread to avoid blocking
    bg_thread = threading.Thread(target=background_tasks, daemon=True, name=f"bg_{model_name}_{model_version_name}")
    bg_thread.start()

    return None, bg_thread # Return success and background thread for tracking

def sanitize_filename(name):
    """Sanitizes a string to be used as a filename or directory name."""
    return re.sub(r'[\\/:*?"<>|]', '_', name)

def ensure_model_description(model_info, api_key=None):
    """
    Guarantees that model_info has a description by fetching it from the parent model if missing.
    Returns the resolved description or None.
    """
    description = (
        model_info.get('description')
        or model_info.get('model', {}).get('description')
    )

    if description:
        return description

    fetched_description = fetch_model_description(model_info, api_key=api_key)
    if fetched_description:
        model_info['description'] = fetched_description
        return fetched_description

    return None

def fetch_model_description(model_info, api_key=None):
    """
    Fetches a model description from the Civitai API using the parent model ID.
    Attempts to match the specific model version first before falling back to any available description.
    """
    model_id = (
        model_info.get('modelId')
        or model_info.get('model', {}).get('id')
    )
    if not model_id:
        return None

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    endpoint = f"{CIVITAI_BASE_URL}/models/{model_id}"

    @retry(exceptions=(requests.exceptions.HTTPError, requests.exceptions.RequestException), tries=2, delay=1.5, backoff=2)
    def _get_model_data(url, headers):
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response

    try:
        response = _get_model_data(endpoint, headers)
        model_data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Warning: Failed to fetch description for model ID {model_id}: {e}")
        return None

    candidates = []
    if model_data.get('description'):
        candidates.append(model_data['description'])

    target_version_id = (
        model_info.get('id')
        or model_info.get('modelVersionId')
        or model_info.get('model', {}).get('modelVersions', [{}])[0].get('id')
    )

    for version in model_data.get('modelVersions', []):
        if version.get('id') == target_version_id and version.get('description'):
            candidates.append(version['description'])

    for version in model_data.get('modelVersions', []):
        if version.get('description'):
            candidates.append(version['description'])

    posts = model_data.get('posts') or []
    for post in posts:
        content = post.get('content')
        if content:
            candidates.append(content)

    for desc in candidates:
        if desc:
            return desc

    return None

def save_description_and_assets(
    model_info,
    target_dir,
    description_text=None,
    api_key=None,
    stop_event=None,
    pause_event=None,
    bandwidth_limit=None,
):
    """
    Persists the model description text and downloads any media referenced inside it.
    The description text is saved as Markdown to preserve formatting.
    Returns a dict with asset download counts.
    """
    result = {"assets_total": 0, "assets_downloaded": 0}

    description = (
        description_text
        or model_info.get('description')
        or model_info.get('model', {}).get('description')
    )

    if not description and api_key:
        description = fetch_model_description(model_info, api_key=api_key)
        if description:
            model_info['description'] = description

    if not description:
        return result

    description_path = os.path.join(target_dir, "description.md")
    try:
        with open(description_path, 'w', encoding='utf-8') as f:
            f.write(description)
        print(f"Saved model description to {description_path}")
    except OSError as e:
        print(f"Warning: Failed to save description text: {e}")

    media_urls = DESCRIPTION_MEDIA_PATTERN.findall(description)
    if not media_urls:
        return result

    assets_dir = os.path.join(target_dir, "description_images")
    os.makedirs(assets_dir, exist_ok=True)

    seen_urls = set()
    for index, original_url in enumerate(media_urls):
        url = original_url.strip()
        if not url:
            continue

        lower_url = url.lower()
        if lower_url in seen_urls:
            continue
        seen_urls.add(lower_url)

        if stop_event and stop_event.is_set():
            print("Description media download interrupted by stop request.")
            break

        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        filename = unquote(filename)
        filename = sanitize_filename(filename)

        if not filename:
            ext = os.path.splitext(parsed.path)[1]
            filename = f"description_asset_{index}{ext if ext else '.jpg'}"
        elif not os.path.splitext(filename)[1]:
            ext = os.path.splitext(parsed.path)[1]
            if ext:
                filename = f"{filename}{ext}"

        destination_path = os.path.join(assets_dir, filename)
        result["assets_total"] += 1
        download_error = download_file(
            url,
            destination_path,
            api_key,
            progress_callback=None,
            stop_event=stop_event,
            pause_event=pause_event,
            bandwidth_limit=bandwidth_limit
        )
        if download_error:
            print(f"Warning: Failed to download description media from {url}: {download_error}")
        else:
            result["assets_downloaded"] += 1

    return result
