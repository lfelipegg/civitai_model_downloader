"""
URL parsing and normalization helpers.
"""

from urllib.parse import urlparse
from typing import List, Optional
import re


class UrlService:
    """Service for parsing and validating Civitai URLs."""

    def validate_url(self, url: str) -> bool:
        if not url:
            return False
        try:
            parsed = urlparse(url)
            return bool(parsed.scheme and parsed.netloc and "civitai.com" in parsed.netloc)
        except Exception:
            return False

    def parse_urls(self, text: str) -> List[str]:
        if not text:
            return []
        urls = [line.strip() for line in text.splitlines() if line.strip()]
        return [url for url in urls if self.validate_url(url)]

    def extract_model_id(self, url: str) -> Optional[str]:
        if not url:
            return None
        match = re.search(r"/models/(\d+)", url)
        return match.group(1) if match else None

    def extract_collection_id(self, url: str) -> Optional[str]:
        if not url:
            return None
        match = re.search(r"/collections/(\d+)", url)
        return match.group(1) if match else None

    def build_version_url(self, original_url: str, model_id: str, version_id: str) -> str:
        parsed = urlparse(original_url or "")
        if parsed.scheme and parsed.netloc:
            base = f"{parsed.scheme}://{parsed.netloc}"
        else:
            base = "https://civitai.com"
        return f"{base}/models/{model_id}?modelVersionId={version_id}"
