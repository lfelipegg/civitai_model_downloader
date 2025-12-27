# Streamlit UI Audit (Current CustomTkinter)

## Entry points
- `run.bat` activates the venv and runs `main.py`.
- `main.py` instantiates `App` and calls `mainloop`.
- `src/gui/main_window.py` is a backward-compatible entrypoint that does the same.

## App shell
- `App` creates a `CTkTabview` with two tabs: Downloads and History.
- `DownloadTab` and `HistoryTab` are wired with shared services (HistoryService, DownloaderService, UrlService).
- Window close delegates to `DownloadTab._on_closing` to stop threads and cleanup.

## Downloads tab UI (DownloadTab)
- Inputs: URL text area (multiline), Browse .txt, API key (masked), download path + Browse Dir.
- Scope: option menu for current version vs all versions.
- Settings: max parallel, retry count, bandwidth limit (KB/s) from env.
- Actions: Start Download, Open Downloads Folder.
- Status: Status, Speed, ETA labels.
- Queue controls: Pause all, Resume all, Cancel all, Clear completed.
- Queue list: scrollable list with per-task card (title, status chip, URL, detail, progress bar, ETA, per-task bandwidth, pause/resume/cancel, reorder).
- Logs: read-only text area.
- Clear/Reset: only clears URL input.

## Downloads flow and state
- URL parsing and validation via `UrlService`.
- Queue worker threads process tasks with retry/backoff, pause/resume, cancel, and progress updates.
- Progress updates are batched via a queue to avoid UI stalls.
- Download work uses `DownloaderService` with callbacks and bandwidth limits.
- Per-task state is tracked in `download_tasks` dict and queue list.
- Background threads generate HTML reports and perform history updates.

## History tab UI (HistoryTab)
- Search bar with debounce, Search and Refresh buttons.
- Filters: model type, base model, date range, size range, trigger words checkbox.
- Sort selector.
- Controls: Scan Downloads, Export History, Import History.
- Stats label and active filters display.
- Results list: thumbnail, model info, trigger words, and action buttons.

## History flow and storage
- `HistoryManager` persists `download_history.json`.
- Scan populates history by crawling `metadata.json` under download folders.
- Export/import reads/writes JSON, with optional merge.
- History items include HTML report path and thumbnails.

## Services and dependencies
- `DownloaderService` wraps API/download functions in `civitai_downloader.py`.
- `HistoryService` wraps `HistoryManager`.
- `UrlService` parses/validates URLs and expands versions/collections.
- UI uses `customtkinter`, `tkinter`, and `dotenv`.

## Data layout
- Downloads stored at `<DOWNLOAD_PATH>/<base_model>/<type>/<model_name>/<version_name>/`.
- Each download directory includes `metadata.json`, `description.md`, `report.html`, images/assets.
- Thumbnails are cached under `thumbnails/`.
