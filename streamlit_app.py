"""
Streamlit UI for Model Manager.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import streamlit as st
from dotenv import load_dotenv

try:
    from src.services.downloader_service import DownloaderService
    from src.services.history_service import HistoryService
    from src.services.url_service import UrlService
except Exception:  # pragma: no cover - Streamlit UI should still render without services.
    DownloaderService = None
    HistoryService = None
    UrlService = None
try:
    from streamlit_autorefresh import st_autorefresh
except Exception:  # pragma: no cover - optional dependency.
    st_autorefresh = None


MAX_LOG_LINES = 500
STATE_FILE_NAME = "streamlit_download_state.json"
STATE_FLUSH_INTERVAL = 0.5


def read_env_int(name: str, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    raw_value = os.getenv(name)
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def read_env_float(
    name: str,
    default: float,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> float:
    raw_value = os.getenv(name)
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        return default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def format_bytes(size_bytes: Optional[int]) -> str:
    if size_bytes is None:
        return "Unknown"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "Unknown"
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "Unknown"
    if value < 0:
        value = 0
    if value >= 3600:
        hours = int(value // 3600)
        minutes = int((value % 3600) // 60)
        secs = int(value % 60)
        return f"{hours}h {minutes}m {secs}s"
    if value >= 60:
        minutes = int(value // 60)
        secs = int(value % 60)
        return f"{minutes}m {secs}s"
    return f"{value:.1f}s"


def format_speed(bytes_per_sec: Optional[float]) -> str:
    if not bytes_per_sec:
        return "N/A"
    return f"{format_bytes(int(bytes_per_sec))}/s"


def parse_url_lines(text: str) -> List[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def init_state() -> None:
    load_dotenv()
    if "urls_text" not in st.session_state:
        st.session_state.urls_text = ""
    if "api_key" not in st.session_state:
        st.session_state.api_key = os.getenv("CIVITAI_API_KEY", "")
    if "download_path" not in st.session_state:
        st.session_state.download_path = os.getenv("DOWNLOAD_PATH", os.getcwd())
    if "download_scope" not in st.session_state:
        st.session_state.download_scope = "Current version only"
    if "max_parallel" not in st.session_state:
        st.session_state.max_parallel = read_env_int("MAX_PARALLEL_DOWNLOADS", 1, min_value=1, max_value=16)
    if "retry_count" not in st.session_state:
        st.session_state.retry_count = read_env_int("DOWNLOAD_RETRY_COUNT", 2, min_value=0, max_value=10)
    if "bandwidth_limit_kbps" not in st.session_state:
        st.session_state.bandwidth_limit_kbps = read_env_float("BANDWIDTH_LIMIT_KBPS", 0.0, min_value=0.0)
    if "ui_alert" not in st.session_state:
        st.session_state.ui_alert = None
    if "history_alert" not in st.session_state:
        st.session_state.history_alert = None
    if "history_query" not in st.session_state:
        st.session_state.history_query = ""
    if "auto_refresh" not in st.session_state:
        st.session_state.auto_refresh = True


def set_alert(key: str, level: str, message: str) -> None:
    st.session_state[key] = (level, message)


def show_alert(key: str) -> None:
    alert: Optional[Tuple[str, str]] = st.session_state.get(key)
    if not alert:
        return
    level, message = alert
    if level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.success(message)
    st.session_state[key] = None


def open_path(path_value: str, label: str) -> None:
    if not path_value:
        set_alert("ui_alert", "warning", f"{label} path is not set.")
        return
    if not os.path.exists(path_value):
        set_alert("ui_alert", "warning", f"{label} path not found: {path_value}")
        return
    try:
        if hasattr(os, "startfile"):
            os.startfile(path_value)  # type: ignore[attr-defined]
        else:
            import webbrowser

            webbrowser.open(path_value)
    except Exception as exc:
        set_alert("ui_alert", "error", f"Unable to open {label.lower()}: {exc}")


class DownloadManager:
    RETRY_BACKOFF_BASE_SECONDS = 2
    RETRY_BACKOFF_MAX_SECONDS = 60

    def __init__(self, downloader_service: DownloaderService, url_service: UrlService):
        self.downloader_service = downloader_service
        self.url_service = url_service
        self._lock = threading.Lock()
        self._queue_condition = threading.Condition(self._lock)
        self._queue: List[Dict[str, str]] = []
        self._task_order: List[str] = []
        self._tasks: Dict[str, Dict[str, object]] = {}
        self._logs: List[str] = []
        self._status = "N/A"
        self._speed = "N/A"
        self._eta = "N/A"
        self._stop_event = threading.Event()
        self._worker_threads: List[threading.Thread] = []
        self._background_threads: Dict[str, threading.Thread] = {}
        self._max_parallel = 1
        self._retry_count = 2
        self._bandwidth_limit_bps: Optional[int] = None
        self._completion_logged = False
        self._state_path = os.path.join(os.getcwd(), STATE_FILE_NAME)
        self._last_state_flush = 0.0

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        with self._lock:
            self._logs.append(entry)
            if len(self._logs) > MAX_LOG_LINES:
                self._logs = self._logs[-MAX_LOG_LINES:]
            self._persist_state_locked()

    def clear_logs(self) -> None:
        with self._lock:
            self._logs = []
            self._persist_state_locked(force=True)

    def _persist_state(self, force: bool = False) -> None:
        with self._lock:
            self._persist_state_locked(force=force)

    def _persist_state_locked(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_state_flush) < STATE_FLUSH_INTERVAL:
            return
        tasks_view = []
        for task_id in self._task_order:
            task = self._tasks.get(task_id)
            if not task:
                continue
            limit_bps = task.get("bandwidth_limit_bps")
            limit_kbps = int(limit_bps / 1024) if limit_bps else 0
            tasks_view.append(
                {
                    "id": task_id,
                    "url": task.get("url", ""),
                    "display_url": task.get("display_url", ""),
                    "state": task.get("state", "queued"),
                    "detail": task.get("detail", ""),
                    "progress": float(task.get("progress", 0.0)),
                    "eta": task.get("eta", "Pending"),
                    "bandwidth_limit_kbps": limit_kbps,
                }
            )
        payload = {
            "status": self._status,
            "speed": self._speed,
            "eta": self._eta,
            "tasks": tasks_view,
            "logs": list(self._logs),
            "updated_at": datetime.utcnow().isoformat(),
        }
        try:
            with open(self._state_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            self._last_state_flush = now
        except OSError:
            pass

    def _load_state_snapshot(self) -> Optional[Dict[str, object]]:
        if not os.path.exists(self._state_path):
            return None
        try:
            with open(self._state_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        payload["read_only"] = True
        return payload

    def sync_settings(self, max_parallel: int, retry_count: int, bandwidth_limit_kbps: float) -> None:
        with self._lock:
            self._max_parallel = max(1, int(max_parallel))
            self._retry_count = max(0, int(retry_count))
            if bandwidth_limit_kbps and bandwidth_limit_kbps > 0:
                self._bandwidth_limit_bps = int(bandwidth_limit_kbps * 1024)
            else:
                self._bandwidth_limit_bps = None

    def enqueue_urls(self, url_text: str, api_key: str, download_path: str, download_scope: str) -> Dict[str, int]:
        urls = parse_url_lines(url_text)
        if not urls:
            self.log("No URLs provided.")
            return {"queued": 0, "invalid": 0}

        queued = 0
        invalid = 0
        download_all_versions = download_scope == "All versions"

        for url in urls:
            if not self.url_service.validate_url(url):
                self._enqueue_task(
                    url,
                    api_key,
                    download_path,
                    display_label=f"Invalid URL: {url}",
                    enqueue=False,
                    initial_state="failed",
                    detail="Invalid URL format",
                )
                invalid += 1
                continue

            collection_id = self.url_service.extract_collection_id(url)
            if collection_id:
                queued_count = self._queue_collection(url, collection_id, api_key, download_path)
                if queued_count:
                    queued += queued_count
                    continue
                self.log(f"Failed to queue collection URL: {url}")
                continue

            if download_all_versions:
                queued_count = self._queue_all_versions(url, api_key, download_path)
                if queued_count:
                    queued += queued_count
                    continue
                self.log(f"Falling back to referenced version for {url}.")

            if self._queue_single_url(url, api_key, download_path):
                queued += 1

        if queued:
            self._status = f"Queued {queued} downloads"
            self.log(f"Queued {queued} downloads.")
            self._completion_logged = False
            self._start_workers()
        elif invalid:
            self._status = "No valid URLs queued"
        self._persist_state()
        return {"queued": queued, "invalid": invalid}

    def _queue_single_url(self, url: str, api_key: str, download_path: str) -> bool:
        self._enqueue_task(url, api_key, download_path, display_label=url)
        return True

    def _queue_all_versions(self, url: str, api_key: str, download_path: str) -> int:
        model_id = self.url_service.extract_model_id(url)
        if not model_id:
            version_info, error = self.downloader_service.get_model_info(url, api_key)
            if error or not version_info:
                self.log(f"Unable to resolve model ID for {url}: {error or 'unknown error'}")
                return 0
            model_id = str(
                version_info.get("modelId")
                or version_info.get("model", {}).get("id")
                or ""
            )
            if not model_id:
                self.log(f"Could not determine model ID from metadata for {url}.")
                return 0

        model_data, error = self.downloader_service.get_model_versions(model_id, api_key)
        if error or not model_data:
            self.log(f"Failed to retrieve model metadata for {model_id}: {error or 'unknown error'}")
            return 0

        versions = model_data.get("modelVersions") or []
        if not versions:
            self.log(f"No versions available for model {model_id}.")
            return 0

        base_name = model_data.get("name") or f"Model {model_id}"
        queued = 0
        seen_versions = set()

        for version in versions:
            version_id = version.get("id")
            if not version_id:
                continue
            version_id = str(version_id)
            if version_id in seen_versions:
                continue
            seen_versions.add(version_id)
            version_url = self.url_service.build_version_url(url, model_id, version_id)
            version_name = version.get("name", f"Version {version_id}")
            display_label = f"{base_name} - {version_name}"
            self._enqueue_task(version_url, api_key, download_path, display_label=display_label)
            queued += 1

        if queued:
            self.log(f"Queued {queued} versions for {base_name}.")
        return queued

    def _queue_collection(self, original_url: str, collection_id: str, api_key: str, download_path: str) -> int:
        models, collection_name, error = self.downloader_service.get_collection_models(collection_id, api_key)
        if error or not models:
            self.log(f"Failed to load collection {collection_id}: {error or 'No items found.'}")
            return 0

        base_name = collection_name or f"Collection {collection_id}"
        queued = 0
        seen = set()

        for model in models:
            model_id = model.get("model_id")
            version_id = model.get("version_id")
            if not model_id or not version_id:
                continue
            key = (model_id, version_id)
            if key in seen:
                continue
            seen.add(key)
            version_url = self.url_service.build_version_url(original_url, model_id, version_id)
            display_label = (
                f"{base_name} - {model.get('model_name', model_id)} - {model.get('version_name', version_id)}"
            )
            self._enqueue_task(version_url, api_key, download_path, display_label=display_label)
            queued += 1

        if queued:
            self.log(f"Queued {queued} items from {base_name}.")
        return queued

    def _enqueue_task(
        self,
        url: str,
        api_key: str,
        download_path: str,
        display_label: Optional[str] = None,
        enqueue: bool = True,
        initial_state: str = "queued",
        detail: Optional[str] = None,
    ) -> str:
        task_id = f"task_{uuid.uuid4().hex}"
        task_entry = {
            "id": task_id,
            "url": url,
            "display_url": display_label or url,
            "state": initial_state,
            "detail": detail or "",
            "progress": 0.0,
            "eta": "Pending",
            "stop_event": threading.Event(),
            "pause_event": threading.Event(),
            "retry_count": self._retry_count,
            "bandwidth_limit_bps": None,
            "model_info": None,
        }
        with self._lock:
            self._tasks[task_id] = task_entry
            self._task_order.append(task_id)
            if enqueue:
                self._queue.append(
                    {
                        "task_id": task_id,
                        "url": url,
                        "api_key": api_key,
                        "download_path": download_path,
                    }
                )
                self._queue_condition.notify_all()
        return task_id

    def _start_workers(self) -> None:
        with self._lock:
            self._worker_threads = [t for t in self._worker_threads if t.is_alive()]
            existing = len(self._worker_threads)
            target = max(1, self._max_parallel)
            for i in range(target - existing):
                worker = threading.Thread(
                    target=self._process_queue,
                    daemon=True,
                    name=f"streamlit_worker_{existing + i + 1}",
                )
                worker.start()
                self._worker_threads.append(worker)

    def _process_queue(self) -> None:
        while not self._stop_event.is_set():
            task_item = None
            with self._lock:
                while not self._queue and not self._stop_event.is_set():
                    self._queue_condition.wait(timeout=0.5)
                if self._stop_event.is_set():
                    break
                if self._queue:
                    task_item = self._queue.pop(0)

            if not task_item:
                continue

            task_id = task_item.get("task_id")
            url = task_item.get("url")
            api_key = task_item.get("api_key")
            download_path = task_item.get("download_path")
            if not task_id:
                continue

            task = self._get_task(task_id)
            if not task:
                continue

            stop_event = task["stop_event"]
            pause_event = task["pause_event"]
            if stop_event.is_set():
                self._set_task_state(task_id, "cancelled", "Cancelled")
                continue
            if pause_event.is_set():
                while pause_event.is_set() and not stop_event.is_set():
                    time.sleep(0.2)
                if stop_event.is_set():
                    self._set_task_state(task_id, "cancelled", "Cancelled")
                    continue

            self._set_task_state(task_id, "queued", "Fetching info")
            model_info, error_message = self.downloader_service.get_model_info(url, api_key)
            if error_message:
                self._set_task_state(task_id, "failed", error_message)
                self.log(f"Error retrieving model info for {url}: {error_message}")
                continue

            if model_info:
                with self._lock:
                    task["model_info"] = model_info

            if self.downloader_service.is_model_downloaded(model_info, download_path):
                self._set_task_state(task_id, "complete", "Already downloaded")
                self.log(f"Model already downloaded: {url}")
                continue

            retry_count = task.get("retry_count", self._retry_count)
            bandwidth_limit = self._get_task_bandwidth_limit(task_id)
            last_error: Optional[str] = None

            for attempt in range(int(retry_count) + 1):
                if stop_event.is_set():
                    self._set_task_state(task_id, "cancelled", "Cancelled")
                    last_error = None
                    break

                if attempt > 0:
                    delay = self._calculate_backoff_delay(attempt)
                    detail = f"Retrying in {delay}s ({attempt}/{retry_count})"
                    self._set_task_state(task_id, "queued", detail)
                    if not self._wait_for_retry(delay, stop_event, pause_event):
                        self._set_task_state(task_id, "cancelled", "Cancelled")
                        last_error = None
                        break

                self._set_task_state(task_id, "downloading")

                def progress_callback(bytes_downloaded, total_size, speed, tid=task_id):
                    self._update_progress(tid, bytes_downloaded, total_size, speed)

                download_error, bg_thread = self.downloader_service.download_model(
                    model_info,
                    download_path,
                    api_key,
                    progress_callback=progress_callback,
                    stop_event=stop_event,
                    pause_event=pause_event,
                    bandwidth_limit=bandwidth_limit,
                )

                if not download_error:
                    if bg_thread:
                        with self._lock:
                            self._background_threads[task_id] = bg_thread
                    self._set_task_state(task_id, "complete", "Complete")
                    last_error = None
                    self.log(f"Download complete for {url}")
                    break

                last_error = str(download_error)
                if not self._is_retryable_error(download_error) or attempt >= retry_count:
                    break
                self.log(f"Retrying {url} after error: {download_error}")

            if last_error:
                self._set_task_state(task_id, "failed", last_error)
                self.log(f"Download failed for {url}: {last_error}")

        self.log("Download queue processing stopped.")

    def _get_task(self, task_id: str) -> Optional[Dict[str, object]]:
        with self._lock:
            return self._tasks.get(task_id)

    def _set_task_state(self, task_id: str, state: str, detail: Optional[str] = None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["state"] = state
            if detail is not None:
                task["detail"] = detail
            if state == "complete":
                task["progress"] = 1.0
                task["eta"] = "Done"
            elif state == "failed":
                task["eta"] = "Failed"
            elif state == "cancelled":
                task["eta"] = "Cancelled"
            elif state == "paused":
                task["eta"] = "Paused"
            if state in {"downloading", "queued"}:
                self._status = detail or state.capitalize()
            elif state in {"failed", "cancelled", "complete"}:
                self._status = detail or state.capitalize()
            self._update_completion_locked()
            self._persist_state_locked(force=state in {"failed", "cancelled", "complete"})

    def _update_completion_locked(self) -> None:
        if not self._tasks:
            return
        active = any(
            task.get("state") in {"queued", "downloading", "paused"} for task in self._tasks.values()
        )
        if active or self._queue:
            return
        if self._completion_logged:
            return
        self._status = "All downloads finished"
        self._logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] All downloads finished.")
        if len(self._logs) > MAX_LOG_LINES:
            self._logs = self._logs[-MAX_LOG_LINES:]
        self._completion_logged = True
        self._persist_state_locked(force=True)

    def _update_progress(self, task_id: str, bytes_downloaded: int, total_size: int, speed: float) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if task["pause_event"].is_set() or task.get("state") == "paused":
                return
            if total_size > 0:
                task["progress"] = min(1.0, bytes_downloaded / total_size)
            else:
                task["progress"] = 0.0

            if speed > 0 and total_size > 0:
                remaining_bytes = max(0, total_size - bytes_downloaded)
                eta_seconds = remaining_bytes / speed if speed > 0 else None
                task["eta"] = format_duration(eta_seconds)
                self._eta = task["eta"]
            else:
                task["eta"] = "Calculating..."
                self._eta = task["eta"]
            self._speed = format_speed(speed)
            self._persist_state_locked()

    def _get_task_bandwidth_limit(self, task_id: str) -> Optional[int]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.get("bandwidth_limit_bps") is not None:
                return int(task["bandwidth_limit_bps"])
            return self._bandwidth_limit_bps

    def _calculate_backoff_delay(self, attempt: int) -> int:
        delay = self.RETRY_BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1))
        return min(delay, self.RETRY_BACKOFF_MAX_SECONDS)

    def _is_retryable_error(self, error_message: Optional[str]) -> bool:
        if not error_message:
            return False
        lowered = str(error_message).lower()
        if "insufficient disk space" in lowered:
            return False
        if "already downloaded" in lowered:
            return False
        if "invalid url" in lowered:
            return False
        if "interrupted by user" in lowered:
            return False
        return True

    def _wait_for_retry(self, delay_seconds: int, stop_event: threading.Event, pause_event: threading.Event) -> bool:
        end_time = time.time() + delay_seconds
        while time.time() < end_time:
            if stop_event.is_set():
                return False
            if pause_event.is_set():
                time.sleep(0.2)
                continue
            time.sleep(0.2)
        return True

    def set_task_bandwidth(self, task_id: str, limit_kbps: int) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if limit_kbps and limit_kbps > 0:
                task["bandwidth_limit_bps"] = int(limit_kbps * 1024)
            else:
                task["bandwidth_limit_bps"] = None

    def pause_task(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["pause_event"].set()
            task["state"] = "paused"
            task["detail"] = "Paused"
            self._persist_state_locked()

    def resume_task(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["pause_event"].clear()
            if task["state"] == "paused":
                task["state"] = "queued"
                task["detail"] = "Resumed"
            self._persist_state_locked()

    def cancel_task(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["stop_event"].set()
            task["state"] = "cancelled"
            task["detail"] = "Cancelled"
            self._persist_state_locked()

    def pause_all(self) -> None:
        with self._lock:
            for task_id in self._task_order:
                task = self._tasks.get(task_id)
                if task and task["state"] in {"queued", "downloading"}:
                    task["pause_event"].set()
                    task["state"] = "paused"
                    task["detail"] = "Paused"
            self._persist_state_locked()

    def resume_all(self) -> None:
        with self._lock:
            for task_id in self._task_order:
                task = self._tasks.get(task_id)
                if task and task["state"] == "paused":
                    task["pause_event"].clear()
                    task["state"] = "queued"
                    task["detail"] = "Resumed"
            self._persist_state_locked()

    def cancel_all(self) -> None:
        with self._lock:
            for task_id in self._task_order:
                task = self._tasks.get(task_id)
                if task and task["state"] in {"queued", "downloading", "paused"}:
                    task["stop_event"].set()
                    task["state"] = "cancelled"
                    task["detail"] = "Cancelled"
            self._persist_state_locked()

    def clear_completed(self) -> None:
        with self._lock:
            remaining = []
            for task_id in self._task_order:
                task = self._tasks.get(task_id)
                if task and task["state"] in {"complete", "failed", "cancelled"}:
                    self._tasks.pop(task_id, None)
                    continue
                remaining.append(task_id)
            self._task_order = remaining
            self._queue = [item for item in self._queue if item.get("task_id") in self._tasks]
            self._persist_state_locked(force=True)

    def move_task(self, task_id: str, direction: int) -> None:
        with self._lock:
            if task_id not in self._task_order:
                return
            index = self._task_order.index(task_id)
            new_index = index + direction
            if new_index < 0 or new_index >= len(self._task_order):
                return
            self._task_order[index], self._task_order[new_index] = (
                self._task_order[new_index],
                self._task_order[index],
            )
            queue_ids = [item.get("task_id") for item in self._queue]
            if task_id in queue_ids:
                q_index = queue_ids.index(task_id)
                q_new = q_index + direction
                if 0 <= q_new < len(queue_ids):
                    self._queue[q_index], self._queue[q_new] = self._queue[q_new], self._queue[q_index]
            self._persist_state_locked()

    def get_snapshot(self) -> Dict[str, object]:
        with self._lock:
            tasks_view = []
            for task_id in self._task_order:
                task = self._tasks.get(task_id)
                if not task:
                    continue
                limit_bps = task.get("bandwidth_limit_bps")
                limit_kbps = int(limit_bps / 1024) if limit_bps else 0
                tasks_view.append(
                    {
                        "id": task_id,
                        "url": task.get("url", ""),
                        "display_url": task.get("display_url", ""),
                        "state": task.get("state", "queued"),
                        "detail": task.get("detail", ""),
                        "progress": float(task.get("progress", 0.0)),
                        "eta": task.get("eta", "Pending"),
                        "bandwidth_limit_kbps": limit_kbps,
                    }
                )
            if not tasks_view:
                fallback = self._load_state_snapshot()
                if fallback:
                    return fallback
            return {
                "status": self._status,
                "speed": self._speed,
                "eta": self._eta,
                "tasks": tasks_view,
                "logs": list(self._logs),
                "read_only": False,
            }

    def has_active_tasks(self) -> bool:
        with self._lock:
            for task in self._tasks.values():
                if task.get("state") in {"queued", "downloading", "paused"}:
                    return True
            return False


@st.cache_resource
def get_history_service() -> Optional["HistoryService"]:
    if HistoryService is None:
        return None
    return HistoryService()


@st.cache_resource
def get_download_manager_cached() -> Optional[DownloadManager]:
    if DownloaderService is None or UrlService is None:
        return None
    return DownloadManager(
        downloader_service=DownloaderService(),
        url_service=UrlService(),
    )


def get_download_manager() -> Optional[DownloadManager]:
    return get_download_manager_cached()


def main() -> None:
    st.set_page_config(page_title="Model Manager", layout="wide")
    init_state()
    download_manager = get_download_manager()

    st.title("Model Manager")

    with st.sidebar:
        st.header("Settings")
        st.text_input("Civitai API Key", key="api_key", type="password")
        st.text_input("Download Path", key="download_path")
        st.number_input("Max parallel", min_value=1, max_value=16, step=1, key="max_parallel")
        st.number_input("Retry count", min_value=0, max_value=10, step=1, key="retry_count")
        st.number_input(
            "Bandwidth limit (KB/s)",
            min_value=0.0,
            step=50.0,
            key="bandwidth_limit_kbps",
            help="0 means unlimited",
        )
        st.checkbox("Auto-refresh while downloading", key="auto_refresh")
        show_alert("ui_alert")

    downloads_tab, history_tab = st.tabs(["Downloads", "History"])

    with downloads_tab:
        if download_manager is None:
            st.warning("Download services are unavailable.")
        else:
            left, right = st.columns([3, 1])
            with left:
                st.text_area("Civitai URLs", key="urls_text", height=160)
            with right:
                uploaded = st.file_uploader("Load URLs from .txt", type=["txt"])
                if uploaded is not None and st.button("Use file contents"):
                    content = uploaded.getvalue().decode("utf-8", errors="ignore")
                    st.session_state.urls_text = content
                    download_manager.log("Loaded URLs from uploaded file.")
                if st.button("Clear URL input"):
                    st.session_state.urls_text = ""
                    download_manager.log("Cleared URL input.")

            st.radio(
                "Download scope",
                ["Current version only", "All versions"],
                key="download_scope",
                horizontal=True,
            )

            actions = st.columns([1, 1, 1, 1])
            if actions[0].button("Start Download", type="primary"):
                if not st.session_state.urls_text.strip():
                    set_alert("ui_alert", "warning", "Please enter Civitai URLs or load a .txt file.")
                elif not st.session_state.download_path:
                    set_alert("ui_alert", "warning", "Please set a download path.")
                elif not os.path.isdir(st.session_state.download_path):
                    set_alert("ui_alert", "warning", "Download path does not exist.")
                else:
                    download_manager.sync_settings(
                        st.session_state.max_parallel,
                        st.session_state.retry_count,
                        st.session_state.bandwidth_limit_kbps,
                    )
                    counts = download_manager.enqueue_urls(
                        st.session_state.urls_text,
                        st.session_state.api_key,
                        st.session_state.download_path,
                        st.session_state.download_scope,
                    )
                    if counts["queued"]:
                        set_alert("ui_alert", "success", f"Queued {counts['queued']} downloads.")
                    elif counts["invalid"]:
                        set_alert("ui_alert", "warning", "No valid URLs queued.")

            if actions[1].button("Open Downloads Folder"):
                open_path(st.session_state.download_path, "Download")
            if actions[2].button("Clear Completed"):
                download_manager.clear_completed()
            actions[3].button("Refresh now")

            snapshot = download_manager.get_snapshot()
            read_only = bool(snapshot.get("read_only"))
            if read_only:
                st.warning("Showing last known download state (read-only).")
            stats = st.columns(3)
            stats[0].metric("Status", snapshot.get("status") or "N/A")
            stats[1].metric("Speed", snapshot.get("speed") or "N/A")
            stats[2].metric("ETA", snapshot.get("eta") or "N/A")

            queue_controls = st.columns(4)
            if queue_controls[0].button("Pause all", disabled=read_only):
                download_manager.pause_all()
            if queue_controls[1].button("Resume all", disabled=read_only):
                download_manager.resume_all()
            if queue_controls[2].button("Cancel all", disabled=read_only):
                download_manager.cancel_all()
            if queue_controls[3].button("Clear completed", disabled=read_only):
                download_manager.clear_completed()

            tasks = snapshot.get("tasks", [])
            st.subheader("Download Queue")
            if not tasks:
                st.info("No active downloads.")
            else:
                for index, task in enumerate(tasks):
                    task_id = task["id"]
                    with st.container():
                        header_cols = st.columns([3, 1])
                        header_cols[0].markdown(f"**{task['display_url']}**")
                        header_cols[1].markdown(f"`{task['state']}`")
                        if task.get("detail"):
                            st.caption(task["detail"])
                        st.caption(task["url"])
                        st.progress(task.get("progress", 0.0))
                        info_cols = st.columns([1, 1, 2])
                        info_cols[0].caption(f"ETA: {task.get('eta', 'Pending')}")
                        limit_key = f"limit_{task_id}"
                        if limit_key not in st.session_state:
                            st.session_state[limit_key] = int(task.get("bandwidth_limit_kbps", 0))
                        new_limit = info_cols[1].number_input(
                            "Limit KB/s",
                            min_value=0,
                            step=10,
                            key=limit_key,
                            disabled=read_only,
                        )
                        if not read_only:
                            download_manager.set_task_bandwidth(task_id, int(new_limit))

                        action_cols = info_cols[2].columns(5)
                        action_cols[0].button(
                            "Pause",
                            key=f"pause_{task_id}",
                            disabled=read_only or task["state"] not in {"queued", "downloading"},
                            on_click=download_manager.pause_task,
                            args=(task_id,),
                        )
                        action_cols[1].button(
                            "Resume",
                            key=f"resume_{task_id}",
                            disabled=read_only or task["state"] != "paused",
                            on_click=download_manager.resume_task,
                            args=(task_id,),
                        )
                        action_cols[2].button(
                            "Cancel",
                            key=f"cancel_{task_id}",
                            disabled=read_only or task["state"] in {"complete", "failed", "cancelled"},
                            on_click=download_manager.cancel_task,
                            args=(task_id,),
                        )
                        action_cols[3].button(
                            "Up",
                            key=f"up_{task_id}",
                            disabled=read_only or index == 0,
                            on_click=download_manager.move_task,
                            args=(task_id, -1),
                        )
                        action_cols[4].button(
                            "Down",
                            key=f"down_{task_id}",
                            disabled=read_only or index == len(tasks) - 1,
                            on_click=download_manager.move_task,
                            args=(task_id, 1),
                        )
                        st.divider()

            with st.expander("Logs", expanded=False):
                st.text_area("Logs", value="\n".join(snapshot.get("logs", [])), height=200, disabled=True)
                if st.button("Clear logs"):
                    download_manager.clear_logs()

            should_refresh = st.session_state.auto_refresh and (
                download_manager.has_active_tasks() or (read_only and tasks)
            )
            if should_refresh:
                if st_autorefresh:
                    st_autorefresh(interval=1000, key="downloads_autorefresh")
                else:
                    st.caption("Auto-refresh requires streamlit-autorefresh. Use Refresh now.")

    with history_tab:
        show_alert("history_alert")
        history_service = get_history_service()
        if history_service is None:
            st.warning("History service is unavailable.")
        else:
            filters_col, refresh_col = st.columns([3, 1])
            with filters_col:
                st.text_input("Search", key="history_query")
            with refresh_col:
                if st.button("Refresh"):
                    if hasattr(st, "experimental_rerun"):
                        st.experimental_rerun()

            options = history_service.get_filter_options()
            model_types = ["All"] + options.get("model_types", [])
            base_models = ["All"] + options.get("base_models", [])

            filter_cols = st.columns(4)
            model_type = filter_cols[0].selectbox("Model type", model_types, key="history_model_type")
            base_model = filter_cols[1].selectbox("Base model", base_models, key="history_base_model")
            date_from = filter_cols[2].text_input("From date (YYYY-MM-DD)", key="history_date_from")
            date_to = filter_cols[3].text_input("To date (YYYY-MM-DD)", key="history_date_to")

            size_cols = st.columns(4)
            size_min = size_cols[0].number_input("Min size (MB)", min_value=0.0, step=1.0, key="history_size_min")
            size_max = size_cols[1].number_input("Max size (MB)", min_value=0.0, step=1.0, key="history_size_max")
            has_triggers = size_cols[2].checkbox("Has trigger words", key="history_has_triggers")

            sort_options = {
                "Date (newest first)": ("download_date", "desc"),
                "Date (oldest first)": ("download_date", "asc"),
                "Name (A-Z)": ("model_name", "asc"),
                "Name (Z-A)": ("model_name", "desc"),
                "Size (largest)": ("file_size", "desc"),
                "Size (smallest)": ("file_size", "asc"),
                "Type (A-Z)": ("model_type", "asc"),
                "Type (Z-A)": ("model_type", "desc"),
            }
            sort_choice = size_cols[3].selectbox("Sort", list(sort_options.keys()), key="history_sort_choice")
            sort_by, sort_order = sort_options[sort_choice]

            control_cols = st.columns([1, 1, 2])
            if control_cols[0].button("Scan Downloads"):
                download_path = st.session_state.download_path
                if not download_path or not os.path.isdir(download_path):
                    set_alert("history_alert", "warning", "Set a valid download path before scanning.")
                else:
                    with st.spinner("Scanning downloads..."):
                        history_service.scan_and_populate_history(download_path)
                    set_alert("history_alert", "success", "Scan complete.")

            with st.expander("Import / Export"):
                import_file = st.file_uploader("Import history JSON", type=["json"], key="history_import_file")
                import_mode = st.radio("Import mode", ["Merge", "Replace"], horizontal=True)
                if st.button("Import History"):
                    if import_file is None:
                        set_alert("history_alert", "warning", "Choose a JSON file to import.")
                    else:
                        merge = import_mode == "Merge"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_file:
                            temp_file.write(import_file.getvalue())
                            temp_path = temp_file.name
                        try:
                            if history_service.import_history(temp_path, merge=merge):
                                set_alert("history_alert", "success", "History imported successfully.")
                            else:
                                set_alert("history_alert", "error", "Failed to import history.")
                        finally:
                            try:
                                os.remove(temp_path)
                            except OSError:
                                pass

                history_path = getattr(history_service._manager, "history_file_path", "download_history.json")
                if os.path.exists(history_path):
                    with open(history_path, "rb") as history_file:
                        st.download_button(
                            "Download history JSON",
                            data=history_file.read(),
                            file_name=os.path.basename(history_path),
                            mime="application/json",
                        )
                else:
                    st.caption("No history file found to export.")

            filters: Dict[str, object] = {}
            if model_type != "All":
                filters["model_type"] = model_type
            if base_model != "All":
                filters["base_model"] = base_model
            if date_from:
                filters["date_from"] = date_from
            if date_to:
                filters["date_to"] = date_to
            if size_min > 0:
                filters["size_min"] = size_min
            if size_max > 0:
                filters["size_max"] = size_max
            if has_triggers:
                filters["has_trigger_words"] = True

            downloads = history_service.search_downloads(
                query=st.session_state.history_query,
                filters=filters or None,
                sort_by=sort_by,
                sort_order=sort_order,
            )

            if st.session_state.history_query or filters:
                st.caption(f"Found {len(downloads)} matches")
            else:
                stats = history_service.get_stats()
                total_size_mb = stats["total_size"] / (1024 * 1024) if stats else 0
                st.caption(f"Total: {stats['total_downloads']} models, {total_size_mb:.1f} MB")

            if not downloads:
                st.info("No history entries found.")
            else:
                for download in downloads:
                    model_name = download.get("model_name", "Unknown")
                    version_name = download.get("version_name", "Unknown")
                    file_size_mb = download.get("file_size", 0) / (1024 * 1024)
                    download_date = download.get("download_date", "")
                    try:
                        dt = datetime.fromisoformat(download_date.replace("Z", "+00:00"))
                        date_text = dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        date_text = download_date

                    st.markdown(f"**{model_name} - {version_name}**")
                    st.caption(
                        f"Type: {download.get('model_type', 'Unknown')} | "
                        f"Base: {download.get('base_model', 'Unknown')} | "
                        f"Size: {file_size_mb:.1f} MB | "
                        f"Downloaded: {date_text}"
                    )
                    triggers = download.get("trigger_words") or []
                    if triggers:
                        st.caption("Triggers: " + ", ".join(triggers[:5]))

                    action_cols = st.columns(5)
                    if action_cols[0].button("Open Folder", key=f"open_{download['id']}"):
                        open_path(download.get("download_path", ""), "Model")
                    if action_cols[1].button("View Report", key=f"report_{download['id']}"):
                        open_path(download.get("html_report_path", ""), "Report")
                    delete_files = action_cols[2].checkbox(
                        "Delete files",
                        key=f"delete_files_{download['id']}",
                    )
                    confirm_delete = action_cols[3].checkbox(
                        "Confirm",
                        key=f"confirm_delete_{download['id']}",
                    )
                    if action_cols[4].button(
                        "Delete",
                        key=f"delete_{download['id']}",
                        disabled=not confirm_delete,
                    ):
                        success = history_service.delete_download_entry(
                            download["id"],
                            delete_files=delete_files,
                        )
                        if success:
                            set_alert("history_alert", "success", "History entry deleted.")
                        else:
                            set_alert("history_alert", "error", "Failed to delete history entry.")
                    st.divider()


if __name__ == "__main__":
    main()
