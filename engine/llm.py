"""Async Anthropic client wrapper with Pydantic structured outputs.

Single LLM entry point for the audit engine. Uses the SDK's `messages.parse()`
structured-output path, which validates the response against the Pydantic
model server-side and returns a typed instance — no JSON-mode parsing, no
regex. The SDK's built-in retries (429/5xx/connection) apply.
"""

from __future__ import annotations

import os
from typing import TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_DEFAULT_MAX_TOKENS = 2048


class StructuredOutputError(RuntimeError):
    pass


class AnthropicLLM:
    """Reuse one instance process-wide; the underlying client is pooled."""

    def __init__(self) -> None:
        self._client = AsyncAnthropic(max_retries=3)
        self.model = os.environ.get("LLM_MODEL", "claude-opus-5")
        self.effort = os.environ.get("LLM_EFFORT", "low")

    async def structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> T:
        response = await self._client.messages.parse(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=response_model,
            output_config={"effort": self.effort},
        )
        if response.stop_reason == "refusal":
            raise StructuredOutputError("Model declined the request (stop_reason=refusal).")
        parsed = response.parsed_output
        if parsed is None:
            raise StructuredOutputError(
                f"Structured output failed to parse (stop_reason={response.stop_reason})."
            )
        return parsed
