"""Image generation service using DashScope API."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# DashScope API endpoints
_SUBMIT_URL = "/api/v1/services/aigc/image-generation/generation"
_TASK_URL = "/api/v1/tasks/{task_id}"

# Polling configuration
_POLL_INTERVAL_SECONDS = 3.0
_POLL_MAX_ATTEMPTS = 120  # 6 minutes max wait

# Transient error retry configuration
_TRANSIENT_MAX_RETRIES = 3
_TRANSIENT_RETRY_DELAY = 2.0


@dataclass(frozen=True)
class ImageResult:
    """Result of an image generation request."""

    url: str
    task_id: str


class ImageGenerationError(Exception):
    """Raised when image generation fails."""


class ImageGenerationService:
    """Async image generation via DashScope text-to-image API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com",
        model: str = "wan2.7-image",
        size: str = "1024*1024",
        timeout: float = 180.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.size = size
        self.timeout = timeout

    async def generate(self, prompt: str) -> ImageResult:
        """Submit image generation task and wait for completion.

        Args:
            prompt: English text description of the image to generate.

        Returns:
            ImageResult with the generated image URL.

        Raises:
            ImageGenerationError: If submission or generation fails.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            task_id = await self._submit_task(client, prompt)
            logger.info("Image generation task submitted: %s", task_id)
            image_url = await self._poll_task(client, task_id)
        return ImageResult(url=image_url, task_id=task_id)

    async def download(self, url: str, save_path: Path) -> Path:
        """Download image from URL and save to local path.

        Args:
            url: Image URL to download.
            save_path: Local file path to save the image.

        Returns:
            The save_path on success.

        Raises:
            ImageGenerationError: If download fails.
        """
        save_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
            # Write to disk in a thread to avoid blocking the event loop
            await asyncio.to_thread(save_path.write_bytes, content)
            logger.info("Image saved to %s (%d bytes)", save_path, len(content))
            return save_path
        except httpx.HTTPError as e:
            raise ImageGenerationError(f"Failed to download image: {e}") from e

    async def _submit_task(self, client: httpx.AsyncClient, prompt: str) -> str:
        """Submit async image generation task, return task_id."""
        url = f"{self.base_url}{_SUBMIT_URL}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ],
            },
            "parameters": {
                "size": self.size,
                "n": 1,
            },
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
            # Check status first, then sleep before next attempt
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                transient_failures = 0  # Reset on successful request
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
                choices = output.get("choices", [])
                if not choices:
                    raise ImageGenerationError(f"Task {task_id} succeeded but no choices")
                message = choices[0].get("message", {})
                content = message.get("content", [])
                if not content:
                    raise ImageGenerationError(f"Task {task_id} result has no content")
                image_url = content[0].get("image")
                if not image_url:
                    raise ImageGenerationError(f"Task {task_id} result has no image URL: {content[0]}")
                return image_url

            if status == "FAILED":
                error_msg = output.get("message", "Unknown error")
                raise ImageGenerationError(f"Task {task_id} failed: {error_msg}")

            if status in ("CANCELED", "UNKNOWN"):
                raise ImageGenerationError(f"Task {task_id} terminated with status: {status}")

            # PENDING or RUNNING - sleep before next check
            logger.debug("Task %s status: %s (attempt %d)", task_id, status, attempt + 1)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        raise ImageGenerationError(f"Task {task_id} timed out after {_POLL_MAX_ATTEMPTS} attempts")
