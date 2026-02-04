"""OpenAI-compatible LLM client for local models."""

import logging
from typing import Optional

import httpx

from granola_bridge.config import AppConfig

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Error from LLM API."""

    pass


class LLMClient:
    """Client for OpenAI-compatible APIs (LMStudio, Ollama, etc.)."""

    def __init__(self, config: AppConfig):
        self.base_url = config.llm.base_url.rstrip("/")
        self.model = config.llm.model
        self.timeout = config.llm.timeout_seconds

    async def complete(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        """Send a completion request to the LLM.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature (lower = more deterministic)
            max_tokens: Maximum tokens in response

        Returns:
            The LLM's response text

        Raises:
            LLMError: If the API request fails
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                )

                if response.status_code != 200:
                    error_text = response.text
                    logger.error(f"LLM API error: {response.status_code} - {error_text}")
                    raise LLMError(f"API returned {response.status_code}: {error_text}")

                data = response.json()

                # Extract response text
                choices = data.get("choices", [])
                if not choices:
                    raise LLMError("No choices in response")

                message = choices[0].get("message", {})
                content = message.get("content", "")

                if not content:
                    raise LLMError("Empty response from LLM")

                return content

        except httpx.ConnectError as e:
            logger.error(f"Failed to connect to LLM at {self.base_url}: {e}")
            raise LLMError(f"Cannot connect to LLM server at {self.base_url}. Is LMStudio running?")
        except httpx.TimeoutException as e:
            logger.error(f"LLM request timed out after {self.timeout}s: {e}")
            raise LLMError(f"Request timed out after {self.timeout} seconds")
        except Exception as e:
            if isinstance(e, LLMError):
                raise
            logger.error(f"Unexpected LLM error: {e}")
            raise LLMError(f"Unexpected error: {e}")

    async def health_check(self) -> bool:
        """Check if the LLM server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/models")
                return response.status_code == 200
        except Exception:
            return False
