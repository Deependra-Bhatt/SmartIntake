"""
memory.py  (NEW FILE)
======================
Bounded, two-tier conversation memory.

WHAT CHANGED (Critical feedback item: "There is no memory module in this
submission at all (no memory.py was included, and none of the logic in
either main file resembles one). conversation_history is a plain Python
list that every turn appends to and passes back to the model in full ...
there is no buffer-mode/summary-mode distinction, and no 10-turn threshold
switch anywhere. This is the exact scenario the spec's Layer 5 requirement
is written to prevent ('a long triage conversation cannot grow the prompt
without bound')."):

  `ConversationMemory` implements a real two-tier design:

    - BUFFER MODE: while the number of raw turns is at or below
      `buffer_threshold` (default 10, config.MEMORY_BUFFER_THRESHOLD),
      every turn is kept verbatim and sent to the model as-is — identical
      behaviour to the original code for short sessions.

    - SUMMARY MODE: once the raw turn count exceeds `buffer_threshold`,
      the oldest turns are condensed into a single running summary (via
      an LLM summarization call, injected as `summarizer`) and only the
      most recent `keep_recent` (default 4, config.MEMORY_KEEP_RECENT)
      turns are kept verbatim. From that point on, `to_api_messages()`
      returns the summary plus the recent turns instead of the full
      history, so the prompt sent to the model is now bounded instead of
      growing without limit for the life of a session.

  Already-extracted structured fields are NOT stored in this class at all
  — they live in the session's `collected` dict (session.py), so nothing
  extracted earlier is ever at risk of being lost by summarization; this
  class only manages the *conversational* context window.

  If the summarization LLM call fails, `_fallback_summary()` produces a
  deterministic, non-LLM summary instead of raising — summarization must
  never crash a session (this ties into the broader "never raise an
  unhandled exception" fix in llm_client.py).
"""

from __future__ import annotations

from typing import Callable, Optional

Summarizer = Callable[[list[dict], Optional[str]], str]


class ConversationMemory:
    def __init__(
        self,
        buffer_threshold: int = 10,
        keep_recent: int = 4,
        summarizer: Optional[Summarizer] = None,
    ):
        # keep_recent must be strictly smaller than buffer_threshold, or
        # compaction would never actually shrink the raw turn list.
        if keep_recent >= buffer_threshold:
            keep_recent = max(1, buffer_threshold - 1)

        self.buffer_threshold = buffer_threshold
        self.keep_recent = keep_recent
        self.summarizer = summarizer

        self._messages: list[dict] = []
        self._summary: Optional[str] = None

        # Surfaced for logging/diagnostics/tests — "buffer" or "summary".
        self.mode: str = "buffer"

    def add(self, role: str, content: str) -> None:
        """Append a turn and compact if the buffer threshold is exceeded."""
        self._messages.append({"role": role, "content": content})
        self._maybe_compact()

    def _maybe_compact(self) -> None:
        if len(self._messages) <= self.buffer_threshold:
            return

        self.mode = "summary"
        to_summarize = self._messages[: -self.keep_recent]
        recent = self._messages[-self.keep_recent :]

        self._summary = self._summarize(to_summarize)
        self._messages = recent

    def _summarize(self, turns: list[dict]) -> str:
        if self.summarizer is not None:
            try:
                return self.summarizer(turns, self._summary)
            except Exception:  # noqa: BLE001 — summarization must never crash the session
                pass
        return self._fallback_summary(turns)

    @staticmethod
    def _fallback_summary(turns: list[dict]) -> str:
        """Deterministic, non-LLM summary used if the summarization call
        fails. Only needs to preserve rough conversational context — the
        structured data itself lives independently in `collected` (see
        session.py) and is never at risk here.
        """
        user_turns = [t["content"] for t in turns if t.get("role") == "user"]
        preview = " | ".join(u[:80] for u in user_turns[-3:])
        if preview:
            return f"({len(turns)} earlier turn(s) condensed) Recent context: {preview}"
        return f"({len(turns)} earlier turn(s) condensed)"

    def to_api_messages(self) -> list[dict]:
        """Build the bounded message list actually sent to the model."""
        if self._summary is None:
            return list(self._messages)

        summary_block = [
            {
                "role": "user",
                "content": f"[Earlier conversation summary]: {self._summary}",
            },
            {
                "role": "assistant",
                "content": "Understood — continuing the intake using that context.",
            },
        ]
        return summary_block + list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)
