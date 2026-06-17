"""Image generation configuration.

Uses lazy loading to ensure env vars are read after dotenv is initialized.
"""

import os
from functools import lru_cache
from typing import NamedTuple


class ImageConfig(NamedTuple):
    model_name: str
    api_key: str
    size: str
    base_url: str


@lru_cache(maxsize=1)
def get_image_config() -> ImageConfig:
    """Load image generation config from environment variables.

    Cached after first call. Call after load_dotenv() to ensure env vars are available.
    """
    return ImageConfig(
        model_name=os.getenv("IMAGE_MODEL_NAME", "wan2.7-image"),
        api_key=os.getenv("DEEPSEEK_APIKEY") or "",
        size=os.getenv("IMAGE_SIZE", "1024*1024"),
        base_url=os.getenv("IMAGE_BASE_URL", "https://dashscope.aliyuncs.com"),
    )
