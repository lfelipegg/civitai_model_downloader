import unittest

from src.services.url_service import UrlService


class TestUrlService(unittest.TestCase):
    def setUp(self):
        self.service = UrlService()

    def test_validate_url(self):
        self.assertTrue(self.service.validate_url("https://civitai.com/models/123"))
        self.assertFalse(self.service.validate_url("https://example.com/models/123"))
        self.assertFalse(self.service.validate_url(""))

    def test_parse_urls(self):
        text = "\n".join(
            [
                "https://civitai.com/models/123?modelVersionId=456",
                "not a url",
                "https://example.com/models/123",
            ]
        )
        urls = self.service.parse_urls(text)
        self.assertEqual(
            urls,
            ["https://civitai.com/models/123?modelVersionId=456"],
        )

    def test_extract_model_id(self):
        url = "https://civitai.com/models/123?modelVersionId=456"
        self.assertEqual(self.service.extract_model_id(url), "123")

    def test_extract_collection_id(self):
        url = "https://civitai.com/collections/99"
        self.assertEqual(self.service.extract_collection_id(url), "99")

    def test_build_version_url(self):
        url = "https://civitai.com/models/123"
        built = self.service.build_version_url(url, "123", "456")
        self.assertEqual(built, "https://civitai.com/models/123?modelVersionId=456")

        built_default = self.service.build_version_url("", "123", "456")
        self.assertEqual(built_default, "https://civitai.com/models/123?modelVersionId=456")


if __name__ == "__main__":
    unittest.main()
