Model Manager
============

Desktop GUI for downloading Civitai models, keeping a local download history, and generating per-model HTML reports with thumbnails.

Features
--------
- Queue-based downloads with pause/resume/cancel.
- Download scope: current version or all versions for a model.
- Collection URL expansion.
- Persistent download history with search and filters.
- Local HTML report per model/version.
- Thumbnail caching for history browsing.

Requirements
------------
- Python 3.10+ recommended (uses a local venv in `venv/`).
- Windows is the primary target (uses `run.bat`).

Setup
-----
1) Create a virtual environment:
   - `python -m venv venv`
2) Install dependencies:
   - `venv\Scripts\pip install -r requirements.txt`
3) (Optional) Set environment variables in `.env`:
   - `CIVITAI_API_KEY` (optional but recommended)
   - `DOWNLOAD_PATH` (default is current working directory)
   - `MAX_PARALLEL_DOWNLOADS` (default 1)
   - `DOWNLOAD_RETRY_COUNT` (default 2)
   - `BANDWIDTH_LIMIT_KBPS` (0 = unlimited)

Run
---
- `run.bat`

Usage
-----
- Paste one or more Civitai URLs (one per line) or load a `.txt` file.
- Choose download scope and destination folder.
- Use the History tab to search, filter, and manage downloaded models.

Data layout
-----------
- Download history stored in `download_history.json`.
- Downloads are saved to:
  - `<DOWNLOAD_PATH>/<base_model>/<type>/<model_name>/<version_name>/`
  - Contains `metadata.json`, `description.md`, `report.html`, images, and assets.
- Thumbnails cached under `thumbnails/`.

Project layout
--------------
- `main.py`: app entry point.
- `src/gui/`: GUI modules.
- `src/services/`: service layer (downloader, history, URL parsing).
- `src/civitai_downloader.py`: API access and download implementation.
- `src/history_manager.py`: JSON-backed history store.
- `docs/`: architecture and refactor plan notes.

Tests
-----
Run all tests:
- `python -m unittest discover -s tests`

Troubleshooting
---------------
- If downloads fail, verify the URL is valid and the API key (if used).
- If the UI hangs, confirm the download directory exists and is writable.
- If thumbnails are missing, ensure Pillow is installed.
