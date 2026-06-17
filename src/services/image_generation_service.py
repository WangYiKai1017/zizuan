"""Image generation service using DashScope API.

Supports both synchronous models (qwen-image-2.0) and asynchronous
models (wan2.7-image) via automatic endpoint detection.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# DashScope API endpoints
_SYNC_ENDPOINT = "/api/v1/services/aigc/multimodal-generation/generation"
_ASYNC_ENDPOINT = "/api/v1/services/aigc/image-generation/generation"
_TASK_URL = "/api/v1/tasks/{task_id}"

# Models that use the synchronous endpoint
_SYNC_MODELS = {"qwen-image-2.0"}

# Polling configuration (async models only)
_POLL_INTERVAL_SECONDS = 3.0
_POLL_MAX_ATTEMPTS = 120  # 6 minutes max wait

# Transient error retry configuration (for polling)
_TRANSIENT_MAX_RETRIES = 3
_TRANSIENT_RETRY_DELAY = 2.0

# Generate retry configuration (for rate limiting / concurrency limits)
_GENERATE_MAX_RETRIES = 3
_GENERATE_RETRY_BASE_DELAY = 5.0  # exponential backoff: 5s, 10s, 20s


@dataclass(frozen=True)
class ImageResult:
    """Result of an image generation request."""

    url: str
    task_id: str


class ImageGenerationError(Exception):
    """Raised when image generation fails."""


class ImageGenerationService:
    """Image generation via DashScope text-to-image API.

    Automatically selects the correct endpoint based on model name:
    - qwen-image-2.0: synchronous multimodal-generation endpoint
    - wan2.7-image: asynchronous image-generation endpoint with polling
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com",
        model: str = "qwen-image-2.0",
        size: str = "1024*1024",
        timeout: float = 180.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.size = size
        self.timeout = timeout
        self._is_sync = model in _SYNC_MODELS

    async def generate(self, prompt: str) -> ImageResult:
        """Generate an image from a text prompt.

        Retries on rate limiting (429) or server errors (5xx) with exponential backoff.

        Args:
            prompt: English text description of the image to generate.

        Returns:
            ImageResult with the generated image URL.

        Raises:
            ImageGenerationError: If generation fails after all retries.
        """
        last_error: Exception | None = None

        for attempt in range(_GENERATE_MAX_RETRIES):
            try:
                if self._is_sync:
                    return await self._generate_sync(prompt)
                else:
                    return await self._generate_async(prompt)
            except ImageGenerationError as e:
                last_error = e
                error_msg = str(e)
                is_retryable = any(
                    token in error_msg.lower()
                    for token in ("429", "500", "502", "503", "rate", "concurrent",
                                  "throttl", "busy", "timed out", "too many")
                )
                if not is_retryable or attempt >= _GENERATE_MAX_RETRIES - 1:
                    raise
                delay = _GENERATE_RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Image generation failed (attempt %d/%d), retrying in %.0fs: %s",
                    attempt + 1, _GENERATE_MAX_RETRIES, delay, e,
                )
                await asyncio.sleep(delay)

        raise ImageGenerationError(
            f"Image generation failed after {_GENERATE_MAX_RETRIES} retries: {last_error}"
        )

    async def download(self, url: str, save_path: Path) -> Path:
        """Download image from URL and save to local path."""
        save_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
            await asyncio.to_thread(save_path.write_bytes, content)
            logger.info("Image saved to %s (%d bytes)", save_path, len(content))
            return save_path
        except httpx.HTTPError as e:
            raise ImageGenerationError(f"Failed to download image: {e}") from e

    async def _generate_sync(self, prompt: str) -> ImageResult:
        """Synchronous generation for qwen-image-2.0 — single request, direct response."""
        url = f"{self.base_url}{_SYNC_ENDPOINT}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {"role": "user", "content": [{"text": prompt}]},
                ],
            },
            "parameters": {"size": self.size, "n": 1},
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as e:
            raise ImageGenerationError(f"Sync image generation failed: {e}") from e

        image_url = self._extract_image_url(data, task_id="")
        request_id = data.get("request_id", "")
        logger.info("Sync image generated: request_id=%s", request_id)
        return ImageResult(url=image_url, task_id=request_id)

    async def _generate_async(self, prompt: str) -> ImageResult:
        """Async generation for wan2.7-image — submit task then poll."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            task_id = await self._submit_task(client, prompt)
            logger.info("Async image task submitted: %s", task_id)
            image_url = await self._poll_task(client, task_id)
        return ImageResult(url=image_url, task_id=task_id)

    async def _submit_task(self, client: httpx.AsyncClient, prompt: str) -> str:
        """Submit async image generation task, return task_id."""
        url = f"{self.base_url}{_ASYNC_ENDPOINT}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {"role": "user", "content": [{"text": prompt}]},
                ],
            },
            "parameters": {"size": self.size, "n": 1},
        }

        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise ImageGenerationError(f"Failed to submit image task: {e}") from e

        task_id = data.get("output", {}).get("task_id")
        if not task_id:
            raise ImageGenerationError(f"No task_id in response: {data}")
        return task_id

    async def _poll_task(self, client: httpx.AsyncClient, task_id: str) -> str:
        """Poll task status until completion, return image URL."""
        url = f"{self.base_url}{_TASK_URL.format(task_id=task_id)}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        transient_failures = 0

        for attempt in range(_POLL_MAX_ATTEMPTS):
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                transient_failures = 0
            except httpx.HTTPError as e:
                transient_failures += 1
                if transient_failures >= _TRANSIENT_MAX_RETRIES:
                    raise ImageGenerationError(
                        f"Failed to poll task {task_id} after {_TRANSIENT_MAX_RETRIES} retries: {e}"
                    ) from e
                logger.warning(
                    "Transient error polling task %s (attempt %d/%d): %s",
                    task_id, transient_failures, _TRANSIENT_MAX_RETRIES, e,
                )
                await asyncio.sleep(_TRANSIENT_RETRY_DELAY)
                continue

            output = data.get("output", {})
            status = output.get("task_status")

            if status == "SUCCEEDED":
                return self._extract_image_url(data, task_id)

            if status == "FAILED":
                error_msg = output.get("message", "Unknown error")
                raise ImageGenerationError(f"Task {task_id} failed: {error_msg}")

            if status in ("CANCELED", "UNKNOWN"):
                raise ImageGenerationError(f"Task {task_id} terminated with status: {status}")

            logger.debug("Task %s status: %s (attempt %d)", task_id, status, attempt + 1)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        raise ImageGenerationError(f"Task {task_id} timed out after {_POLL_MAX_ATTEMPTS} attempts")

    @staticmethod
    def _extract_image_url(data: dict, task_id: str) -> str:
        """Extract image URL from DashScope response (works for both sync and async)."""
        output = data.get("output", {})
        choices = output.get("choices", [])
        if not choices:
            raise ImageGenerationError(
                f"Task {task_id}: no choices in response" if task_id else "No choices in response"
            )
        message = choices[0].get("message", {})
        content = message.get("content", [])
        if not content:
            raise ImageGenerationError(f"Task {task_id}: no content" if task_id else "No content")
        image_url = content[0].get("image")
        if not image_url:
            raise ImageGenerationError(
                f"Task {task_id}: no image URL: {content[0]}" if task_id else f"No image URL: {content[0]}"
            )
        return image_url
