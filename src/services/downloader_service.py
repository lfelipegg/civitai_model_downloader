"""
Download orchestration service for Civitai models.
"""

from src.civitai_downloader import (
    get_model_info_from_url,
    download_civitai_model,
    is_model_downloaded,
    get_model_with_versions,
    get_collection_models,
)


class DownloaderService:
    """Service wrapper for model download operations."""

    def get_model_info(self, url: str, api_key: str):
        return get_model_info_from_url(url, api_key)

    def download_model(self, model_info, download_path, api_key, progress_callback=None, stop_event=None, pause_event=None):
        return download_civitai_model(
            model_info,
            download_path,
            api_key,
            progress_callback=progress_callback,
            stop_event=stop_event,
            pause_event=pause_event,
        )

    def is_model_downloaded(self, model_info, download_path: str) -> bool:
        return is_model_downloaded(model_info, download_path)

    def get_model_versions(self, model_id: str, api_key: str):
        return get_model_with_versions(model_id, api_key)

    def get_collection_models(self, collection_id: str, api_key: str):
        return get_collection_models(collection_id, api_key)
