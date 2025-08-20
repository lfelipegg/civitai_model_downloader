import os
import requests
import re
import time
import hashlib

CIVITAI_BASE_URL = "https://civitai.com/api/v1"

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
            response = requests.get(endpoint, headers=headers)
            response.raise_for_status()
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
            response = requests.get(endpoint, headers=headers)
            response.raise_for_status()
            model_info = response.json()
            if model_info and model_info.get('modelVersions'):
                # Find the latest version by checking the 'createdAt' or 'updatedAt' field,
                # or assume the first one is the latest if no specific ordering is guaranteed by the API
                # For now, keeping the existing logic of assuming the first is latest, as per original code.
                latest_version = model_info['modelVersions'][0]
                endpoint = f"{CIVITAI_BASE_URL}/model-versions/{latest_version['id']}"
                print(f"Fetching latest model version info from: {endpoint}")
                response = requests.get(endpoint, headers=headers)
                response.raise_for_status()
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

def download_file(url, path, api_key=None, progress_callback=None, expected_sha256=None):
    """Downloads a file from a URL to a specified path with progress updates and SHA256 verification."""
    print(f"Downloading {url} to {path}")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = requests.get(url, stream=True, headers=headers)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        return f"HTTP Error during download: {e.response.status_code} - {e.response.reason}"
    except requests.exceptions.RequestException as e:
        return f"Network Error during download: {e}"

    total_size = int(response.headers.get('content-length', 0))
    bytes_downloaded = 0
    start_time = time.time()
    
    sha256_hash = hashlib.sha256()

    with open(path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
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

def download_civitai_model(model_info, download_base_path, api_key, progress_callback=None):
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
        download_error = download_file(model_download_url, os.path.join(target_dir, model_filename), api_key, progress_callback=progress_callback, expected_sha256=expected_sha256)
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
            download_error = download_file(image_url, os.path.join(target_dir, image_name), api_key, progress_callback=progress_callback)
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