# Refactor Plan

## Goals
- Separate UI concerns from download and history logic.
- Reduce shared mutable state and thread coordination complexity.
- Make filtering and search reliable and testable.
- Establish clearer module boundaries for future features.

## Proposed stages

### Stage 1: Stabilize data flow and interfaces
- Introduce a `DownloadTask` dataclass to unify task state across the queue and UI.
- Centralize queue operations in a `DownloadQueue` service with clear APIs.
- Normalize filter keys and value types between the GUI and `HistoryManager`.
- Replace duplicated `_process_download_queue` with a single implementation.
- Add a small diagnostics logger for threading and queue state.

### Stage 2: Decompose the GUI
- Split `src/gui/main_window.py` into:
  - `src/gui/download_tab.py` (download UI and queue controls).
  - `src/gui/history_tab.py` (search/filter/history list).
  - `src/gui/app.py` (window and tab wiring).
- Move widget creation helpers into `src/gui/widgets/` where appropriate.
- Convert direct state access into injected services (queue, history, downloader).

### Stage 3: Extract services
- Create `src/services/downloader_service.py` for API, download, and report orchestration.
- Create `src/services/history_service.py` to wrap `HistoryManager` with GUI-friendly queries.
- Move URL parsing and scope handling into a `src/services/url_service.py`.
- Ensure services are unit-testable without a GUI context.

### Stage 4: Tests and cleanup
- Add lightweight tests for:
  - URL parsing and scope expansion.
  - History filtering and sorting.
  - Queue behavior and cancellation logic.
- Remove dead code paths and unused imports.
- Document public interfaces in module docstrings.

## Refactor targets and rationale
- `src/gui/main_window.py`: too many responsibilities; split to improve readability and testability.
- `src/history_manager.py`: filter contract mismatch with GUI; align inputs and fix date handling.
- `src/civitai_downloader.py`: blend of API, download, and asset parsing; split into focused helpers.
- `src/progress_tracker.py` and `src/enhanced_progress_bar.py`: keep, but hide internals behind a thin adapter for the GUI.

## Suggested order of edits
1. Fix history filter mismatch and duplicate queue processor definition.
2. Introduce task dataclass and queue service.
3. Extract download and history services.
4. Split GUI into tab modules and wire services.

