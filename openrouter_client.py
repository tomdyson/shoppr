"""
OpenRouter API Client

Wrapper around OpenRouter API (OpenAI-compatible) for chat completion and cost tracking.
"""

import httpx
from typing import Dict, Any, List, Optional, Tuple


class OpenRouterClient:
    """
    Wrapper around OpenRouter API configured for chat completions and cost tracking.
    """

    def __init__(
        self,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str = "",
        model_prefix: str = ""
    ):
        """
        Initialize client.

        Args:
            base_url: OpenRouter API base URL (default: https://openrouter.ai/api/v1)
            api_key: API key for authentication
            model_prefix: Optional prefix to add to model names (e.g., "google/")
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model_prefix = model_prefix

        # httpx client for making requests
        self.httpx_client = httpx.Client(timeout=60.0)

    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Make a chat completion request with cost tracking.

        Args:
            model: Model name (e.g., "google/gemini-2.5-flash-lite")
            messages: OpenAI-format messages list
            temperature: Optional temperature setting
            max_tokens: Optional max tokens limit

        Returns:
            Tuple of (response_text, usage_stats)
            where usage_stats contains:
                - model: str
                - input_tokens: int
                - output_tokens: int
                - cost: float (USD from response usage object or header)

        Raises:
            httpx.HTTPError: If request fails
            ValueError: If response format is invalid
        """
        # Add model prefix if provided and not already present
        full_model_name = model
        if self.model_prefix and not model.startswith(self.model_prefix):
            full_model_name = f"{self.model_prefix}{model}"

        # Build request payload
        request_data: Dict[str, Any] = {"model": full_model_name, "messages": messages}
        if temperature is not None:
            request_data["temperature"] = temperature
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens

        # Make request via httpx
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://shoppr.local",
            "X-Title": "Shoppr",
        }
        response = self.httpx_client.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=request_data,
        )
        response.raise_for_status()

        # Parse response body
        response_json = response.json()

        # Extract response text
        try:
            response_text = response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ValueError(f"Invalid response format: {e}") from e

        usage = response_json.get("usage", {})

        # Extract cost from usage object or fallback headers
        cost = 0.0
        if "cost" in usage and usage["cost"] is not None:
            try:
                cost = float(usage["cost"])
            except (ValueError, TypeError):
                pass
        else:
            cost_header = response.headers.get("x-litellm-response-cost") or response.headers.get("openrouter-cost")
            if cost_header:
                try:
                    cost = float(cost_header)
                except (ValueError, TypeError):
                    pass

        usage_stats = {
            "model": model,
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "cost": cost,
        }

        return response_text, usage_stats

    def close(self):
        """Close underlying HTTP client."""
        self.httpx_client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
