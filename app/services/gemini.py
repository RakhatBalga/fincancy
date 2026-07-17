"""Shared Gemini client with retries and a fallback model.

Centralises the ``google-genai`` client so both the expense parser and the
advisor reuse one instance. Gemini occasionally returns ``503 UNAVAILABLE``
(model overloaded) or ``429`` (rate limit); these are transient, so calls are
retried with backoff and, if the primary model keeps failing, a cheaper
fallback model is tried before giving up.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import TypeVar

import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings

log = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# Tried in order after the configured model, if that one keeps failing.
# All lightweight flash variants — unlikely to all be overloaded at once.
_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-flash-latest",
)
# One try per model so a 503 cascades quickly through the list instead of
# making the user wait on repeated backoffs.
_MAX_ATTEMPTS_PER_MODEL = 1
_BASE_BACKOFF = 0.8  # seconds between attempts


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Return a process-wide Gemini client (created lazily, then cached)."""
    return genai.Client(api_key=settings.gemini_api_key)


def _models(primary: str | None) -> list[str]:
    first = primary or settings.gemini_model
    return [first, *[m for m in _FALLBACK_MODELS if m != first]]


def _is_retryable(exc: Exception) -> bool:
    """503 (overloaded) and 429 (rate limit) are worth retrying."""
    if isinstance(exc, genai_errors.ServerError):  # 5xx
        return True
    if isinstance(exc, genai_errors.ClientError):
        return getattr(exc, "status_code", None) == 429
    return False


async def _generate(
    contents: str, config: types.GenerateContentConfig, primary: str | None
) -> types.GenerateContentResponse:
    """Call the API, retrying transient errors across primary + fallback models."""
    last_exc: Exception | None = None
    for model in _models(primary):
        for attempt in range(_MAX_ATTEMPTS_PER_MODEL):
            try:
                return await get_client().aio.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as exc:  # noqa: BLE001 - classified below
                if not _is_retryable(exc):
                    raise
                last_exc = exc
                log.warning(
                    "gemini_retry",
                    model=model,
                    attempt=attempt + 1,
                    error=type(exc).__name__,
                )
                await asyncio.sleep(_BASE_BACKOFF * (attempt + 1))
    assert last_exc is not None
    raise last_exc


async def generate_json(
    contents: str,
    schema: type[T],
    system_instruction: str,
    *,
    temperature: float = 0.0,
    model: str | None = None,
) -> T | None:
    """Generate a response constrained to ``schema`` and return the parsed model."""
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
    )
    response = await _generate(contents, config, model)
    parsed = getattr(response, "parsed", None)
    return parsed if isinstance(parsed, schema) else None


async def generate_text(
    contents: str,
    system_instruction: str,
    *,
    temperature: float = 0.4,
    model: str | None = None,
) -> str:
    """Generate free-form text (used for the monthly advice)."""
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
    )
    response = await _generate(contents, config, model)
    return (response.text or "").strip()
