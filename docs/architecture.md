# Architecture Overview

## Purpose
Model Manager is a CustomTkinter desktop app for downloading Civitai models, tracking download history, and generating local HTML reports and thumbnails.

## High-level flow
- User inputs one or more Civitai URLs in the Downloads tab.
- URLs are queued for processing and handled by a background queue processor.
- The downloader fetches metadata, downloads the model and assets, and writes a report.
- History is persisted to `download_history.json` and surfaced in the History tab.
- Thumbnails are generated from downloaded images and cached locally.

## Key modules
- `main.py`: entry point that instantiates the GUI app.
- `src/gui/main_window.py`: primary UI window, download queue processing, and history interactions.
- `src/gui/utils.py`: UI helpers (file dialogs, URL validation, formatting, thread-safe UI updates).
- `src/civitai_downloader.py`: Civitai API access, file downloads, description asset capture, and background report generation.
- `src/history_manager.py`: JSON-backed history storage, search/filter, import/export, and cleanup.
- `src/html_generator.py`: builds local HTML reports for each model/version.
- `src/thumbnail_manager.py`: creates and caches thumbnails from downloaded images.
- `src/progress_tracker.py`: enhanced progress tracking and ETA calculations.
- `src/enhanced_progress_bar.py`: CustomTkinter widgets for progress UI.

## Data and outputs
- `download_history.json`: persistent record of downloads and metadata paths.
- Download output structure:
  - `<DOWNLOAD_PATH>/<base_model>/<type>/<model_name>/<version_name>/`
  - `metadata.json`, `description.md`, `report.html`, images, and assets.
- `thumbnails/`: cached thumbnails by size plus a fallback placeholder.

## Threading model
- Queue processor thread handles download tasks sequentially.
- Progress updates are pushed to a UI-safe queue and applied on the main thread.
- HTML report generation runs in background threads per download.

