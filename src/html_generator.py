import os
import json
import html

def generate_html_report(model_info, output_dir):
    """
    Generates an HTML report for a downloaded Civitai model.
    """
    model_name = model_info['model']['name']
    model_version_name = model_info['name']
    model_type = model_info['model']['type']
    download_count = model_info['stats']['downloadCount']
    thumbs_up_count = model_info['stats']['thumbsUpCount']
    rating = model_info['stats']['rating']
    rating_count = model_info['stats']['ratingCount']
    published_at = model_info['publishedAt'].split('T')[0] if 'publishedAt' in model_info else 'N/A'
    base_model = model_info.get('baseModel', 'N/A')
    trained_words = model_info.get('trainedWords', [])
    usage_tips = model_info.get('usageTips', 'N/A')
    description = (
        model_info.get('description')
        or model_info.get('model', {}).get('description')
    )
    if not description:
        description_path = os.path.join(output_dir, "description.md")
        if os.path.exists(description_path):
            try:
                with open(description_path, 'r', encoding='utf-8') as f:
                    loaded_description = f.read().strip()
                if loaded_description:
                    description = loaded_description
            except OSError as e:
                print(f"Warning: Unable to load description from {description_path}: {e}")
    if not description:
        description = 'No description provided.'

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{model_name} - {model_version_name}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f0f2f5;
            color: #333;
            line-height: 1.6;
        }}
        .container {{
            max-width: 960px;
            margin: 20px auto;
            background-color: #fff;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        }}
        header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid #eee;
        }}
        header h1 {{
            color: #2c3e50;
            font-size: 2.5em;
            margin-bottom: 5px;
        }}
        header h2 {{
            color: #34495e;
            font-size: 1.5em;
            margin-top: 0;
            font-weight: normal;
        }}
        .civitai-links {{
            margin-top: 15px;
            font-size: 0.9em;
        }}
        .civitai-links a {{
            color: #007bff;
            text-decoration: none;
            margin: 0 10px;
        }}
        .civitai-links a:hover {{
            text-decoration: underline;
        }}
        .stats-container {{
            display: flex;
            justify-content: center;
            gap: 25px;
            margin-top: 20px;
            flex-wrap: wrap;
        }}
        .stat-item {{
            text-align: center;
            padding: 10px 15px;
            background-color: #e9ecef;
            border-radius: 5px;
            font-size: 0.9em;
            color: #555;
        }}
        .stat-item strong {{
            display: block;
            font-size: 1.2em;
            color: #2c3e50;
        }}
        .section-title {{
            color: #2c3e50;
            font-size: 1.8em;
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
            margin-top: 40px;
            margin-bottom: 20px;
        }}
        .details-section {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .detail-item {{
            background-color: #f9f9f9;
            padding: 15px;
            border-radius: 5px;
            border: 1px solid #ddd;
        }}
        .detail-item strong {{
            color: #4CAF50;
            display: block;
            margin-bottom: 5px;
        }}
        .tags-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 20px;
        }}
        .tag {{
            background-color: #007bff;
            color: white;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            white-space: nowrap;
        }}
        .trigger-words ul {{
            list-style: none;
            padding: 0;
        }}
        .trigger-words li {{
            background-color: #e6f7ff;
            border: 1px solid #bae7ff;
            padding: 8px 12px;
            margin-bottom: 5px;
            border-radius: 4px;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.9em;
        }}
        .model-file {{
            background-color: #f0f8f0;
            border: 1px solid #c3e6cb;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 15px;
        }}
        .model-file p {{
            margin: 5px 0;
        }}
        .image-gallery {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        .image-gallery img, .image-gallery video {{
            width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            object-fit: cover;
            cursor: pointer; /* Add pointer cursor to indicate clickability */
        }}
        .image-item {{
            position: relative;
            background-color: #f0f0f0;
            border-radius: 8px;
            overflow: hidden;
        }}
        .image-meta {{
            background-color: rgba(0, 0, 0, 0.6);
            color: white;
            padding: 10px;
            font-size: 0.8em;
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            max-height: 50%;
            overflow-y: auto;
            opacity: 0;
            transition: opacity 0.3s ease-in-out;
        }}
        .image-item:hover .image-meta {{
            opacity: 1;
        }}
        pre {{
            background-color: #eef1f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.9em;
            border: 1px solid #e0e4e8;
        }}
        /* Modal Styles */
        .modal {{
            display: none; /* Hidden by default */
            position: fixed; /* Stay in place */
            z-index: 1; /* Sit on top */
            left: 0;
            top: 0;
            width: 100%; /* Full width */
            height: 100%; /* Full height */
            overflow: auto; /* Enable scroll if needed */
            background-color: rgba(0,0,0,0.8); /* Black w/ opacity */
            justify-content: center;
            align-items: center;
            padding-top: 50px;
        }}
        .modal-content {{
            background-color: #fefefe;
            margin: auto;
            padding: 20px;
            border: 1px solid #888;
            width: 80%;
            max-width: 900px;
            border-radius: 8px;
            position: relative;
            box-shadow: 0 5px 15px rgba(0,0,0,0.3);
        }}
        .close-button {{
            color: #aaa;
            float: right;
            font-size: 28px;
            font-weight: bold;
        }}
        .close-button:hover,
        .close-button:focus {{
            color: #000;
            text-decoration: none;
            cursor: pointer;
        }}
        .modal-image, .modal-video {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 10px auto;
            border-radius: 5px;
        }}
        .modal-details h4 {{
            color: #2c3e50;
            margin-top: 15px;
            margin-bottom: 5px;
        }}
        .modal-details pre {{
            background-color: #eef1f4;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 0.85em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{model_name}</h1>
            <h2>Version: {model_version_name} ({model_type})</h2>
            <div class="stats-container">
                <div class="stat-item">
                    <strong>{download_count:,}</strong>
                    Downloads
                </div>
                <div class="stat-item">
                    <strong>{thumbs_up_count:,}</strong>
                    Likes
                </div>
                <div class="stat-item">
                    <strong>{rating:.2f} ({rating_count})</strong>
                    Rating
                </div>
            </div>
            <div class="civitai-links">
                <a href="https://civitai.com/models/{model_info['modelId']}" target="_blank">View Model on Civitai</a>
                <a href="https://civitai.com/models/{model_info['modelId']}?modelVersionId={model_info['id']}" target="_blank">View Version on Civitai</a>
            </div>
        </header>

        <h3 class="section-title">Details</h3>
        <div class="details-section">
            <div class="detail-item">
                <strong>Published At:</strong> {published_at}
            </div>
            <div class="detail-item">
                <strong>Base Model:</strong> {base_model}
            </div>
            <div class="detail-item">
                <strong>Usage Tips:</strong> {usage_tips}
            </div>
            <div class="detail-item">
                <strong>Model ID:</strong> {model_info['modelId']}
            </div>
            <div class="detail-item">
                <strong>Version ID:</strong> {model_info['id']}
            </div>
        </div>

        <h3 class="section-title">Description</h3>
        <pre>{html.escape(description) if description else 'No description provided.'}</pre>

        <h3 class="section-title">Trigger Words</h3>
        <div class="trigger-words">
            <ul>
                {"".join([f"<li>{word.strip()}</li>" for word in trained_words]) if trained_words else "<li>No trigger words specified.</li>"}
            </ul>
        </div>

        <h3 class="section-title">Model Files</h3>
        <div class="model-files">
            {"".join([f'''
            <div class="model-file">
                <p><strong>Name:</strong> {file['name']}</p>
                <p><strong>Type:</strong> {file['type']}</p>
                <p><strong>Size:</strong> {file['sizeKB'] / 1024:.2f} MB</p>
                <p><strong>Primary:</strong> {'Yes' if file.get('primary') else 'No'}</p>
                <p><strong>Scanned:</strong> {file.get('scannedAt', 'N/A').split('T')[0]}</p>
                <p><strong>Pickle Scan:</strong> {file.get('pickleScanResult', 'N/A')}</p>
                <p><strong>Virus Scan:</strong> {file.get('virusScanResult', 'N/A')}</p>
                <p><strong>SHA256:</strong> {file['hashes'].get('SHA256', 'N/A')}</p>
                <p><a href="{file['downloadUrl']}" target="_blank">Download</a></p>
            </div>
            ''' for file in model_info.get('files', [])]) if model_info.get('files') else '<p>No model files available.</p>'}
        </div>

        <h3 class="section-title">Images & Videos</h3>
        <div class="image-gallery">
    """

    # Add images and videos
    if 'images' in model_info:
        for i, media_item in enumerate(model_info['images']):
            media_url = media_item['url']
            media_type = media_item.get('type', 'image') # 'image' or 'video'
            
            # Assuming images/videos are downloaded to the same directory as the HTML report
            # We need to get the local filename based on how it was saved
            media_filename = f"image_{i}{os.path.splitext(media_url)[1].split('?')[0]}" # Remove query params from extension

            meta_content = ""
            if media_item.get('meta'):
                meta_content = json.dumps(media_item['meta'], indent=2)
            elif media_item.get('metadata'):
                meta_content = json.dumps(media_item['metadata'], indent=2)
            
            # Escape single quotes in meta_content for use in data-meta attribute
            escaped_meta_content = meta_content.replace("'", "'")

            if media_type == 'video':
                html_content += f'''
                <div class="image-item" data-type="video" data-src="./{media_filename}" data-meta='{escaped_meta_content}'>
                    <video controls class="modal-video" src="./{media_filename}" alt="Video {i+1}"></video>
                    <div class="image-meta">
                        <h4>Metadata</h4>
                        <pre>{meta_content}</pre>
                    </div>
                </div>
                '''
            else: # Default to image
                html_content += f'''
                <div class="image-item" data-type="image" data-src="./{media_filename}" data-meta='{escaped_meta_content}'>
                    <img class="modal-image" src="./{media_filename}" alt="Image {i+1}">
                    <div class="image-meta">
                        <h4>Metadata</h4>
                        <pre>{meta_content}</pre>
                    </div>
                </div>
                '''

    html_content += f"""
        </div>

        <h3 class="section-title">Raw Metadata</h3>
        <pre class="raw-metadata">{json.dumps(model_info, indent=2)}</pre>
    </div>

    <!-- The Modal -->
    <div id="imageModal" class="modal">
        <div class="modal-content">
            <span class="close-button">&times;</span>
            <div id="modal-media-container">
                <!-- Media (image or video) will be inserted here -->
            </div>
            <div class="modal-details">
                <h4>Prompt:</h4>
                <pre id="modal-prompt"></pre>
                <h4>Negative Prompt:</h4>
                <pre id="modal-negative-prompt"></pre>
                <h4>Other Metadata:</h4>
                <pre id="modal-other-meta"></pre>
            </div>
        </div>
    </div>

    <script>
        // Get the modal
        var modal = document.getElementById("imageModal");

        // Get the <span> element that closes the modal
        var span = document.getElementsByClassName("close-button")[0];

        // Get elements to populate in the modal
        var modalMediaContainer = document.getElementById("modal-media-container");
        var modalPrompt = document.getElementById("modal-prompt");
        var modalNegativePrompt = document.getElementById("modal-negative-prompt");
        var modalOtherMeta = document.getElementById("modal-other-meta");

        // When the user clicks on an image, open the modal and populate content
        document.querySelectorAll('.image-item').forEach(item => {{
            item.addEventListener('click', function() {{
                var mediaSrc = this.getAttribute('data-src');
                var mediaType = this.getAttribute('data-type');
                var metaData = JSON.parse(this.getAttribute('data-meta').replace(/'/g, "'")); // Unescape single quotes

                // Clear previous media
                modalMediaContainer.innerHTML = '';

                // Add image or video to modal
                if (mediaType === 'video') {{
                    var video = document.createElement('video');
                    video.src = mediaSrc;
                    video.controls = true;
                    video.classList.add('modal-video');
                    modalMediaContainer.appendChild(video);
                }} else {{
                    var img = document.createElement('img');
                    img.src = mediaSrc;
                    img.classList.add('modal-image');
                    modalMediaContainer.appendChild(img);
                }}

                // Populate metadata
                modalPrompt.textContent = metaData.prompt || 'N/A';
                modalNegativePrompt.textContent = metaData.negativePrompt || 'N/A';
                
                // Display other metadata, excluding prompt and negativePrompt
                var otherMeta = {{...metaData}};
                delete otherMeta.prompt;
                delete otherMeta.negativePrompt;
                modalOtherMeta.textContent = JSON.stringify(otherMeta, null, 2);

                modal.style.display = "flex"; // Use flex to center the modal
            }});
        }});

        // When the user clicks on <span> (x), close the modal
        span.onclick = function() {{
            modal.style.display = "none";
        }}

        // When the user clicks anywhere outside of the modal, close it
        window.onclick = function(event) {{
            if (event.target == modal) {{
                modal.style.display = "none";
            }}
        }}
    </script>
</body>
</html>
    """

    output_path = os.path.join(output_dir, "report.html")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"HTML report generated at: {output_path}")
