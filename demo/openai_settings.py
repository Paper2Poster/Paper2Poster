"""Resolve the OpenAI-compatible endpoint and model IDs used by the demo."""

from urllib.parse import urlsplit


DEFAULT_TEXT_MODEL = "gpt-5"
DEFAULT_VISION_MODEL = "gpt-5"


def resolve_openai_settings(base_url="", text_model="", vision_model=""):
    """Keep first-party defaults, but require explicit model IDs for custom APIs."""
    base_url = (base_url or "").strip()
    text_model = (text_model or "").strip()
    vision_model = (vision_model or "").strip()

    if base_url:
        parsed_url = urlsplit(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("API base URL must be an absolute http(s) URL.")
        if not text_model or not vision_model:
            raise ValueError(
                "Custom API endpoints require both a text model ID and a vision model ID."
            )
    else:
        text_model = text_model or DEFAULT_TEXT_MODEL
        vision_model = vision_model or DEFAULT_VISION_MODEL

    return base_url, text_model, vision_model
