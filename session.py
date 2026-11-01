"""
session.py  (NEW FILE)
========================
Shared intake-session engine used by BOTH entry points
(main_Anth.py's batch test harness and main_Anth_CLI.py's interactive CLI).

WHY THIS FILE EXISTS
---------------------
The original codebase implemented almost the entire extraction / follow-up
/ confirmation loop TWICE — once in main_Anth.py and once in
main_Anth_CLI.py — with the two copies already subtly diverging (e.g. only
the CLI had a confirm-before-save gate). That duplication is a
maintainability risk: a fix made in one file (as this refactor makes many
of) has to be remembered and re-applied in the other.

`IntakeSession` centralizes all of the actual intake logic exactly once:
  - Defensive LLM calls (via llm_client.safe_create — see that module for
    the "no try/except around API calls" fix)
  - Bounded two-tier conversation memory (via memory.ConversationMemory —
    see that module for the "no memory module at all" fix)
  - Code-level out-of-scope screening on the opening message (via
    guardrails.looks_out_of_scope — see that module)
  - Pydantic validation with a failed-attempt counter that escalates to a
    deterministic, static fallback question after
    config.MAX_FAILED_ATTEMPTS_BEFORE_FALLBACK consecutive failures (fixes
    "no failed-attempt counter or escalation logic anywhere")
  - A real confirm-before-save gate (the one genuine strength the review
    called out in main_Anth_CLI.py) — now available to BOTH entry points,
    so main_Anth.py's T1–T5 batch harness also exercises it instead of
    auto-saving the instant validation passes.

Both main_Anth.py and main_Anth_CLI.py now just drive this engine's public
methods (`handle_message`, `submit_confirmation`) and handle
presentation/I/O — they contain no extraction/validation/memory logic of
their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import anthropic
from pydantic import ValidationError

import guardrails
from config import (
    MAX_FAILED_ATTEMPTS_BEFORE_FALLBACK,
    MEMORY_BUFFER_THRESHOLD,
    MEMORY_KEEP_RECENT,
    MODEL,
)
from llm_client import safe_create
from memory import ConversationMemory
from prompts import (
    CONFIRMATION_SYSTEM,
    EXTRACTION_SYSTEM,
    FIELD_QUESTIONS,
    FOLLOWUP_SYSTEM,
    OUT_OF_SCOPE_FALLBACK_MESSAGE,
    SUMMARY_SYSTEM,
)
from schema import IntakeRecordAnth as IntakeRecord
from storage import log_debug, save_record_anth
from tools import INTAKE_TOOL

# A small, fixed set of natural-language affirmatives recognized by the
# confirm-before-save gate. Kept here (rather than only in the CLI) since
# the batch harness also needs to recognize "yes" when auto-confirming.
AFFIRMATIVE_RESPONSES = {"yes", "y", "correct", "looks good", "sure", "ok", "okay", "confirm", "confirmed"}


@dataclass
class TurnOutcome:
    """Result of processing one user turn, for the caller (CLI/batch) to render."""

    kind: str  # "out_of_scope" | "assistant_text" | "followup" | "confirmation_request" | "error"
    message: str
    record: Optional[IntakeRecord] = None


@dataclass
class SaveOutcome:
    """Result of submit_confirmation()."""

    kind: str  # "saved" | "correction_requested"
    message: str
    record: Optional[IntakeRecord] = None
    filepath: Optional[str] = None


@dataclass
class IntakeSession:
    """Encapsulates all state and logic for one regulatory-intake conversation."""

    client: anthropic.Anthropic
    model: str = MODEL

    memory: ConversationMemory = field(init=False)
    collected: dict = field(default_factory=dict)
    turns_taken: int = 0
    failed_attempts: int = 0

    pending_record: Optional[IntakeRecord] = None
    awaiting_confirmation: bool = False

    def __post_init__(self) -> None:
        self.memory = ConversationMemory(
            buffer_threshold=MEMORY_BUFFER_THRESHOLD,
            keep_recent=MEMORY_KEEP_RECENT,
            summarizer=self._summarize_turns,
        )

    # ------------------------------------------------------------------
    # Summarization callback wired into ConversationMemory
    # ------------------------------------------------------------------
    def _summarize_turns(self, turns: list[dict], previous_summary: Optional[str]) -> str:
        prior = f"Previous summary: {previous_summary}\n" if previous_summary else ""
        transcript = "\n".join(f"{t['role']}: {t['content']}" for t in turns)
        result = safe_create(
            self.client,
            model=self.model,
            max_tokens=150,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": f"{prior}Turns to condense:\n{transcript}"}],
        )
        if result.ok and result.text:
            return result.text
        # Raising here is caught by ConversationMemory._summarize(), which
        # falls back to its own deterministic summary — but we return a
        # deterministic value directly rather than raising, since we
        # already have everything we need to do so.
        raise RuntimeError("summarization call failed")

    # ------------------------------------------------------------------
    # Main turn-processing entry point
    # ------------------------------------------------------------------
    def handle_message(self, user_text: str) -> TurnOutcome:
        """Process one user message when NOT awaiting a save confirmation."""
        self.turns_taken += 1
        self.memory.add("user", user_text)

        # --- Code-level out-of-scope backstop -------------------------
        # Only applied on the opening message of a session (nothing
        # collected yet) so normal in-flow answers are never screened.
        if not self.collected and guardrails.looks_out_of_scope(user_text):
            self.memory.add("assistant", OUT_OF_SCOPE_FALLBACK_MESSAGE)
            log_debug(f"Turn {self.turns_taken}: out-of-scope backstop triggered")
            return TurnOutcome(kind="out_of_scope", message=OUT_OF_SCOPE_FALLBACK_MESSAGE)

        # --- Extraction call --------------------------------------------
        extraction = safe_create(
            self.client,
            model=self.model,
            max_tokens=300,
            system=EXTRACTION_SYSTEM,
            tools=INTAKE_TOOL,
            tool_choice={"type": "auto"},
            messages=self.memory.to_api_messages(),
        )

        if not extraction.ok:
            fallback = (
                "I'm having trouble reaching the compliance intake service "
                "right now. Please try again in a moment."
            )
            log_debug(f"Turn {self.turns_taken}: extraction call failed ({extraction.error})")
            return TurnOutcome(kind="error", message=fallback)

        if extraction.tool_input is None:
            # Model replied in plain text (e.g. clarifying question of its
            # own, or its own out-of-scope refusal).
            reply = extraction.text or (
                "Could you tell me more about the compliance matter you'd "
                "like to log?"
            )
            self.memory.add("assistant", reply)
            log_debug(f"Turn {self.turns_taken}: no tool call — model replied in text")
            return TurnOutcome(kind="assistant_text", message=reply)

        # Merge newly extracted (non-empty) fields into what we've collected.
        self.collected.update({k: v for k, v in extraction.tool_input.items() if v})

        try:
            record = IntakeRecord(**self.collected)
        except ValidationError as exc:
            return self._handle_validation_error(exc)

        # Validation passed — reset the failure counter and move to the
        # confirm-before-save gate (now shared by both entry points).
        self.failed_attempts = 0
        confirmation_text = self._generate_confirmation(record)
        self.memory.add("assistant", confirmation_text)
        self.pending_record = record
        self.awaiting_confirmation = True
        log_debug(f"Turn {self.turns_taken}: record complete, awaiting confirmation")
        return TurnOutcome(kind="confirmation_request", message=confirmation_text, record=record)

    def _handle_validation_error(self, exc: ValidationError) -> TurnOutcome:
        missing = [str(err["loc"][0]) for err in exc.errors()]
        self.failed_attempts += 1
        log_debug(
            f"Turn {self.turns_taken}: missing/invalid fields {missing} "
            f"(failed_attempts={self.failed_attempts})"
        )

        # NEW: after MAX_FAILED_ATTEMPTS_BEFORE_FALLBACK consecutive
        # failures, skip the LLM entirely and ask the static fallback
        # question — this is the "failed-attempt counter and escalation
        # logic" the feedback flagged as missing.
        if self.failed_attempts >= MAX_FAILED_ATTEMPTS_BEFORE_FALLBACK:
            first_missing = missing[0] if missing else "submitting_team"
            followup = FIELD_QUESTIONS.get(
                first_missing,
                "Could you clarify the missing information for this intake record?",
            )
            self.memory.add("assistant", followup)
            return TurnOutcome(kind="followup", message=followup)

        followup = self._generate_followup(missing)
        self.memory.add("assistant", followup)
        return TurnOutcome(kind="followup", message=followup)

    # ------------------------------------------------------------------
    # LLM-backed generation helpers, each with a deterministic fallback
    # ------------------------------------------------------------------
    def _generate_confirmation(self, record: IntakeRecord) -> str:
        result = safe_create(
            self.client,
            model=self.model,
            max_tokens=150,
            system=CONFIRMATION_SYSTEM,
            messages=[{"role": "user", "content": f"Intake record: {record.model_dump_json()}"}],
        )
        if result.ok and result.text:
            return result.text

        # Deterministic templated fallback — we already have the full
        # structured record, so a confirmation can always be produced
        # without the LLM if that call fails.
        log_debug(f"Turn {self.turns_taken}: confirmation call failed, using template fallback")
        return (
            f"Acknowledged: a {record.query_type.replace('_', ' ')} matter under "
            f"{record.regulation_ref} ({record.jurisdiction}), urgency "
            f"'{record.urgency}', submitted by {record.submitting_team}. "
            "Please confirm or correct before this record is saved."
        )

    def _generate_followup(self, missing: list[str]) -> str:
        import json as _json  # local import keeps this helper self-contained

        prompt = (
            f"Fields already collected: {_json.dumps(self.collected)}\n"
            f"Fields still needed: {', '.join(missing)}\n"
            "Ask for the first missing field only."
        )
        result = safe_create(
            self.client,
            model=self.model,
            max_tokens=150,
            system=FOLLOWUP_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if result.ok and result.text:
            return result.text

        log_debug(f"Turn {self.turns_taken}: follow-up call failed, using static fallback")
        first_missing = missing[0] if missing else "submitting_team"
        return FIELD_QUESTIONS.get(
            first_missing,
            "Could you clarify the missing information for this intake record?",
        )

    # ------------------------------------------------------------------
    # Confirm-before-save gate (kept from main_Anth_CLI.py's original
    # design — the review's one clearly-credited strength — and now
    # shared by both entry points)
    # ------------------------------------------------------------------
    def submit_confirmation(self, confirmed: bool) -> SaveOutcome:
        if not self.awaiting_confirmation or self.pending_record is None:
            raise RuntimeError("submit_confirmation() called with no pending record")

        record = self.pending_record

        if confirmed:
            filepath = save_record_anth(record, self.turns_taken)
            log_debug(f"Turn {self.turns_taken}: record explicitly confirmed and saved to {filepath}")
            self.awaiting_confirmation = False
            self.pending_record = None
            return SaveOutcome(kind="saved", message="Record confirmed and saved.", record=record, filepath=filepath)

        message = "Understood. Let's make corrections. What would you like to update?"
        self.memory.add("assistant", message)
        log_debug(f"Turn {self.turns_taken}: user declined to confirm — awaiting corrections")
        self.awaiting_confirmation = False
        self.pending_record = None
        return SaveOutcome(kind="correction_requested", message=message)

    @staticmethod
    def is_affirmative(text: str) -> bool:
        return text.strip().lower() in AFFIRMATIVE_RESPONSES
