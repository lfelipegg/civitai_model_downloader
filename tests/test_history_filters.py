import tempfile
import unittest

from src.history_manager import HistoryManager


class TestHistoryFilters(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        history_path = f"{self.temp_dir.name}/history.json"
        self.manager = HistoryManager(history_file_path=history_path)

        downloads = [
            {
                "id": "1",
                "model_type": "Lora",
                "base_model": "SD1",
                "download_date": "2025-01-15T12:00:00",
                "file_size": 20 * 1024 * 1024,
                "trigger_words": ["foo"],
            },
            {
                "id": "2",
                "model_type": "Checkpoint",
                "base_model": "SDXL",
                "download_date": "2025-02-10T12:00:00",
                "file_size": 80 * 1024 * 1024,
                "trigger_words": [],
            },
            {
                "id": "3",
                "model_type": "Lora",
                "base_model": "SD1",
                "download_date": "2024-12-20T12:00:00",
                "file_size": 5 * 1024 * 1024,
                "trigger_words": ["bar"],
            },
        ]

        self.manager._save_history({"downloads": downloads})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_filter_by_model_type(self):
        results = self.manager.search_downloads(filters={"model_type": "Lora"})
        ids = {item["id"] for item in results}
        self.assertEqual(ids, {"1", "3"})

    def test_filter_by_base_model(self):
        results = self.manager.search_downloads(filters={"base_model": "SD1"})
        ids = {item["id"] for item in results}
        self.assertEqual(ids, {"1", "3"})

    def test_filter_by_date_range(self):
        filters = {"date_from": "2025-01-01", "date_to": "2025-01-31"}
        results = self.manager.search_downloads(filters=filters)
        ids = {item["id"] for item in results}
        self.assertEqual(ids, {"1"})

    def test_filter_by_size_range(self):
        filters = {"size_min": 10, "size_max": 50}
        results = self.manager.search_downloads(filters=filters)
        ids = {item["id"] for item in results}
        self.assertEqual(ids, {"1"})

    def test_filter_trigger_words(self):
        results = self.manager.search_downloads(filters={"has_trigger_words": True})
        ids = {item["id"] for item in results}
        self.assertEqual(ids, {"1", "3"})

    def test_search_query_matches_trigger_words(self):
        results = self.manager.search_downloads(query="foo")
        ids = {item["id"] for item in results}
        self.assertEqual(ids, {"1"})


if __name__ == "__main__":
    unittest.main()
