# Streamlit UI Structure (Step 2)

## Navigation decision
- Use a single Streamlit app with `st.tabs` for Downloads and History.
- Keep shared settings in the sidebar to avoid duplication and make them global.
## Refinement decisions (before Step 3)
- App entrypoint: `streamlit_app.py` in repo root.
- Sidebar holds only global settings; Downloads tab owns URL ingestion and queue controls.
- History list starts as a simple read-only list driven by `HistoryService` (actions wired later).
- Background work and progress updates will be staged via session state placeholders before wiring real threads.

## Sidebar layout (global settings)
- API key (password input).
- Download path (text input, optional browse action handled in code).
- Max parallel, retry count, bandwidth limit (KB/s).
- Optional: show active environment defaults and validation status.

## Downloads tab layout mapping
- URL input block: `st.text_area` for URLs, plus `st.file_uploader` for .txt.
- Scope selector: `st.radio` (current version vs all versions).
- Actions row: Start Download (primary), Open Downloads Folder, Clear URL input.
- Status row: Status, Speed, ETA using `st.metric` or inline labels.
- Queue controls: Pause all, Resume all, Cancel all, Clear completed.
- Queue list: per-task container with
  - Title (display label) and state badge.
  - Secondary URL line and detail line.
  - `st.progress` bar and ETA label.
  - Per-task bandwidth input.
  - Task actions: Pause/Resume/Cancel and Move Up/Down.
- Logs: `st.expander` with read-only text area, plus Clear Logs action.

## History tab layout mapping
- Search row: search input and Refresh button.
- Filters row: model type, base model, date range, size range, trigger words checkbox.
- Sort selector: by date/name/size/type, asc/desc.
- Control row: Scan Downloads, Export History, Import History.
- Stats line: total or filtered counts.
- Active filters display: tag-like text line.
- Results list: per-item container with
  - Thumbnail image.
  - Title and detail text.
  - Trigger words line.
  - Actions: Open Folder, View Report, Delete.

## Session state mapping (initial keys)
- `urls_text`, `api_key`, `download_path`, `download_scope`
- `max_parallel`, `retry_count`, `bandwidth_limit_kbps`
- `queue`, `tasks`, `logs`, `status`, `speed`, `eta`
- `history_query`, `history_filters`, `history_sort_by`, `history_sort_order`

## Notes
- Streamlit reruns require careful handling of background threads and progress updates.
- Folder/report opening should use Windows-friendly calls (e.g., `os.startfile`) with user feedback.
