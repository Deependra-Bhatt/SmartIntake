"""
llm_client.py  (NEW FILE)
==========================
Centralized, defensive wrapper around the Anthropic Messages API.

WHAT CHANGED (Critical feedback item: "No try/except anywhere around the
Anthropic API calls themselves ... only around Pydantic's ValidationError
... an API error or rate limit would crash the program outright"):

  Previously, main_Anth.py and main_Anth_CLI.py each called
  `client.messages.create(...)` directly — three or four separate call
  sites per file — with zero exception handling around any of them. A
  transient network blip, a 429 rate limit, a temporary 5xx from
  Anthropic, or an unexpected response shape would propagate as an
  unhandled exception and kill the entire session (interactive) or the
  entire batch run (T1–T5), directly contradicting the spec's "never
  raise an unhandled exception to the terminal" requirement.

  Now, every single call to the Anthropic API funnels through
  `safe_create()` below, which:
    - Retries transient errors (rate limit / overloaded / connection
      issues) with exponential backoff, up to config.MAX_RETRIES times.
    - Catches every `anthropic.APIError` subclass plus any other
      unexpected exception (broad `except Exception` is intentional here
      — this is the single most load-bearing safety boundary in the
      whole app, and it must never let an exception escape).
    - Logs failures via storage.log_error (token counts / status codes
      only — never raw user text, preserving the log-safety guarantee).
    - Returns a typed `LLMResult` (`.ok`, `.text`, `.tool_input`,
      `.stop_reason`, `.error`) instead of raising, so every caller in
      session.py can always degrade gracefully (fall back to a static
      question, a templated confirmation, etc.) instead of crashing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import anthropic

from config import MAX_RETRIES, RETRY_BASE_DELAY_SECONDS
from storage import log_error, log_usage


@dataclass
class LLMResult:
    """Typed result of a single Anthropic API call. Never raises."""

    ok: bool
    text: Optional[str] = None
    tool_input: Optional[dict] = None
    stop_reason: Optional[str] = None
    error: Optional[str] = None


# Transient errors worth retrying with backoff.
_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


def safe_create(client: anthropic.Anthropic, **kwargs: Any) -> LLMResult:
    """Call client.messages.create(**kwargs) defensively.

    Retries retryable errors with exponential backoff, catches every other
    Anthropic API error and any unexpected exception, logs the failure,
    and always returns an LLMResult instead of raising. Callers must check
    `.ok` and use a fallback path when it is False.
    """
    last_error_desc: Optional[str] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(**kwargs)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_error_desc = f"{type(exc).__name__}: {exc}"
            log_error(
                f"Retryable Anthropic API error on attempt "
                f"{attempt}/{MAX_RETRIES}: {type(exc).__name__}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
                continue
            return LLMResult(ok=False, error=f"{last_error_desc} (retries exhausted)")
        except anthropic.APIStatusError as exc:
            log_error(f"Anthropic API status error: HTTP {exc.status_code}")
            return LLMResult(ok=False, error=f"APIStatusError: HTTP {exc.status_code}")
        except anthropic.APIError as exc:
            log_error(f"Anthropic API error: {type(exc).__name__}")
            return LLMResult(ok=False, error=f"{type(exc).__name__}")
        except Exception as exc:  # noqa: BLE001 — deliberate broad catch, see module docstring
            log_error(f"Unexpected error calling Anthropic API: {type(exc).__name__}: {exc}")
            return LLMResult(ok=False, error=f"Unexpected error: {type(exc).__name__}")
        else:
            return _to_result(response)

    # Defensive fallback; loop above always returns before falling through
    # in practice, but this guarantees safe_create() itself never raises.
    return LLMResult(ok=False, error=last_error_desc or "Unknown error calling Anthropic API")


def _to_result(response: Any) -> LLMResult:
    """Convert a successful Anthropic response into an LLMResult."""
    try:
        usage = getattr(response, "usage", None)
        if usage:
            log_usage(usage)

        text: Optional[str] = None
        tool_input: Optional[dict] = None
        for block in getattr(response, "content", None) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text" and text is None:
                text = block.text
            elif block_type == "tool_use" and tool_input is None:
                tool_input = block.input

        return LLMResult(
            ok=True,
            text=text,
            tool_input=tool_input,
            stop_reason=getattr(response, "stop_reason", None),
        )
    except Exception as exc:  # noqa: BLE001 — malformed/unexpected response shape
        log_error(f"Failed to parse Anthropic response: {type(exc).__name__}: {exc}")
        return LLMResult(ok=False, error=f"Response parsing error: {type(exc).__name__}")
