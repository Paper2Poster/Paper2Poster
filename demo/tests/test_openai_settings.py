import unittest

from demo.openai_settings import (
    DEFAULT_TEXT_MODEL,
    DEFAULT_VISION_MODEL,
    resolve_openai_settings,
)


class ResolveOpenAISettingsTests(unittest.TestCase):
    def test_blank_endpoint_preserves_default_models(self):
        self.assertEqual(
            resolve_openai_settings(),
            ("", DEFAULT_TEXT_MODEL, DEFAULT_VISION_MODEL),
        )
        self.assertEqual(DEFAULT_TEXT_MODEL, "gpt-5")
        self.assertEqual(DEFAULT_VISION_MODEL, "gpt-5")

    def test_custom_endpoint_accepts_explicit_models_with_or_without_trailing_slash(self):
        for base_url in ("https://api.example.test/v1", "https://api.example.test/v1/"):
            with self.subTest(base_url=base_url):
                self.assertEqual(
                    resolve_openai_settings(base_url, "text-model", "vision-model"),
                    (base_url, "text-model", "vision-model"),
                )

    def test_custom_endpoint_requires_absolute_http_url(self):
        for base_url in (
            "api.example.test/v1",
            "ftp://api.example.test/v1",
            "https:///v1",
        ):
            with self.subTest(base_url=base_url):
                with self.assertRaisesRegex(ValueError, r"absolute http\(s\) URL"):
                    resolve_openai_settings(base_url, "text-model", "vision-model")

    def test_custom_endpoint_requires_both_model_ids(self):
        for text_model, vision_model in (("", "vision-model"), ("text-model", ""), ("", "")):
            with self.subTest(text_model=text_model, vision_model=vision_model):
                with self.assertRaisesRegex(ValueError, "both a text model ID and a vision model ID"):
                    resolve_openai_settings(
                        "https://api.example.test/v1", text_model, vision_model
                    )

    def test_whitespace_is_trimmed_and_blank_endpoint_keeps_defaults(self):
        self.assertEqual(
            resolve_openai_settings("  ", "  ", "  "),
            ("", DEFAULT_TEXT_MODEL, DEFAULT_VISION_MODEL),
        )


if __name__ == "__main__":
    unittest.main()
