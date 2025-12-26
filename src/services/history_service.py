"""
History service wrapper for download history operations.
"""

from typing import Optional

from src.history_manager import HistoryManager


class HistoryService:
    """Service wrapper around HistoryManager for UI-friendly access."""

    def __init__(self, history_manager: Optional[HistoryManager] = None):
        self._manager = history_manager or HistoryManager()

    def search_downloads(self, query: str = "", search_fields=None, filters=None, sort_by: str = "download_date", sort_order: str = "desc"):
        return self._manager.search_downloads(
            query=query,
            search_fields=search_fields,
            filters=filters,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    def get_stats(self):
        return self._manager.get_stats()

    def get_filter_options(self):
        return self._manager.get_filter_options()

    def scan_and_populate_history(self, download_path: str):
        return self._manager.scan_and_populate_history(download_path)

    def export_history(self, filename: str) -> bool:
        return self._manager.export_history(filename)

    def import_history(self, filename: str, merge: bool = True) -> bool:
        return self._manager.import_history(filename, merge=merge)

    def delete_download_entry(self, entry_id: str, delete_files: bool = False) -> bool:
        return self._manager.delete_download_entry(entry_id, delete_files=delete_files)
