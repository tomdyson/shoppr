"""
LiteLLM Proxy Client

Wrapper around OpenAI client configured for litellm proxy.
Provides cost tracking via response headers.
"""

import httpx
from typing import Dict, Any, List, Optional, Tuple


class LiteLLMClient:
    """
    Wrapper around OpenAI client configured for litellm proxy.
    Provides cost tracking via response headers.
    """

    def __init__(self, base_url: str, api_key: str, model_prefix: str = "gemini/"):
        """
        Initialize client.

        Args:
            base_url: LiteLLM proxy URL (e.g., https://litellm.co.tomd.org)
            api_key: API key for proxy authentication
            model_prefix: Prefix to add to model names (e.g., "gemini/")
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model_prefix = model_prefix

        # httpx client for making requests and extracting response headers
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
            model: Model name (e.g., "gemini-2.5-flash-lite")
            messages: OpenAI-format messages list
            temperature: Optional temperature setting
            max_tokens: Optional max tokens limit

        Returns:
            Tuple of (response_text, usage_stats)
            where usage_stats contains:
                - model: str
                - input_tokens: int
                - output_tokens: int
                - cost: float (USD from proxy header)

        Raises:
            httpx.HTTPError: If request fails
            ValueError: If response format is invalid
        """
        # Add model prefix if provided and not already present
        full_model_name = model
        if self.model_prefix and not model.startswith(self.model_prefix):
            full_model_name = f"{self.model_prefix}{model}"

        # Build request payload
        request_data = {"model": full_model_name, "messages": messages}
        if temperature is not None:
            request_data["temperature"] = temperature
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens

        # Make request via httpx to capture headers
        response = self.httpx_client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=request_data,
        )
        response.raise_for_status()

        # Extract cost from header
        cost = 0.0
        cost_header = response.headers.get("x-litellm-response-cost")
        if cost_header:
            try:
                cost = float(cost_header)
            except (ValueError, TypeError):
                print(f"Warning: Could not parse cost header: {cost_header}")
        else:
            print("Warning: No cost header in response")

        # Parse response body
        response_json = response.json()

        # Extract response text and usage
        try:
            response_text = response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ValueError(f"Invalid response format: {e}") from e

        usage = response_json.get("usage", {})

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
