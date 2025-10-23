
import sqlite3
import re
import os
import requests
from urllib.parse import urlparse

def download_images(model_id=None):
    conn = sqlite3.connect('D:\\AI\\ComphyUI\\scripts\\civitai\\civitai_models.db')
    cursor = conn.cursor()

    if model_id:
        cursor.execute("SELECT id, directory_location, description FROM models WHERE id = ?", (model_id,))
    else:
        cursor.execute("SELECT id, directory_location, description FROM models")

    counter = 0
    for row in cursor.fetchall():
        model_id, directory_location, description = row
        if not description:
            continue

        urls = re.findall(r'https?://[^\s>"]*?\.(?:jpe?g|png|gif|webp|mp4|mov|avi|wmv|flv|webm)\b', description, re.IGNORECASE)
        if not urls:
            continue

        counter += 1

        images_dir = os.path.join(directory_location, 'description_images')
        os.makedirs(images_dir, exist_ok=True)

        print(f"=== STARTING at : {images_dir}")

        for url in urls:
            print(f"URL captured without query string: {url}")
            try:
                response = requests.get(url, stream=True)
                response.raise_for_status()
                
                # Get the filename from the URL
                parsed_url = urlparse(url)
                filename = os.path.basename(parsed_url.path)

                # Sanitize filename
                filename = re.sub(r'[^a-zA-Z0-9_.-]', '', filename)
                
                # If the URL doesn't have a filename, create one
                if not filename:
                    filename = f"image_{urls.index(url)}.jpg"


                with open(os.path.join(images_dir, filename), 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"Downloaded {url} to {os.path.join(images_dir, filename)}")
            except requests.exceptions.RequestException as e:
                print(f"Failed to download {url}: {e}")

    print(f"COUNTER {counter}")
    conn.close()

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Download images from model descriptions.')
    parser.add_argument('--model_id', type=int, help='The ID of the model to process.')
    args = parser.parse_args()

    download_images(args.model_id)
