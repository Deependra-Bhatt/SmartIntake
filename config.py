"""
config.py
=========
Single source of truth for environment configuration and tunable constants.

WHAT CHANGED / WHY THIS FILE EXISTS
------------------------------------
The original codebase duplicated the exact same block —

    load_dotenv()
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    MODEL = "claude-haiku-4-5"
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

— verbatim in both main_Anth.py and main_Anth_CLI.py. Any change (model name,
retry policy, output directory, memory thresholds) had to be made twice and
could silently drift out of sync.

This module centralizes:
  - Anthropic API credentials / client construction
  - The model name (now overridable via env var instead of hardcoded)
  - Retry / backoff tuning for the new defensive LLM wrapper (llm_client.py)
  - Conversation-memory buffer/summary thresholds (memory.py) — this is the
    configuration knob for the Layer 5 "multi-turn memory" fix
  - The failed-attempt threshold that triggers the deterministic follow-up
    question fallback (session.py) — this is the fix for "no failed-attempt
    counter or escalation logic anywhere"
  - Output/log file locations

All values have sane defaults so the app runs out of the box with just an
ANTHROPIC_API_KEY set, but every knob is overridable via environment
variables for ops/deployment flexibility.
"""

from __future__ import annotations

import os
import warnings

from dotenv import load_dotenv

# Load variables from a local .env file (if present) into the process
# environment. Safe to call even if no .env file exists.
load_dotenv()

# ---------------------------------------------------------------------------
# Anthropic API configuration
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")


MODEL: str = os.getenv("SMARTINTAKE_MODEL", "claude-haiku-4-5")

if not ANTHROPIC_API_KEY:
    warnings.warn(
        "ANTHROPIC_API_KEY is not set. Set it in your environment or in a "
        ".env file before running SmartIntake — API calls will fail until "
        "it is configured.",
        RuntimeWarning,
        stacklevel=2,
    )

# ---------------------------------------------------------------------------
# Defensive LLM call tuning (see llm_client.py)
# Addresses feedback: "No try/except anywhere around the Anthropic API
# calls themselves ... an API error or rate limit would crash the program
# outright."
# ---------------------------------------------------------------------------
MAX_RETRIES: int = int(os.getenv("SMARTINTAKE_MAX_RETRIES", "3"))
RETRY_BASE_DELAY_SECONDS: float = float(
    os.getenv("SMARTINTAKE_RETRY_BASE_DELAY", "1.5")
)

# ---------------------------------------------------------------------------
# Conversation memory tuning (see memory.py)
# Addresses feedback: "There is no memory module in this submission at all
# ... conversation_history is a plain Python list that every turn appends to
# ... no 10-turn threshold switch anywhere."
# ---------------------------------------------------------------------------
MEMORY_BUFFER_THRESHOLD: int = int(os.getenv("SMARTINTAKE_MEMORY_THRESHOLD", "10"))
MEMORY_KEEP_RECENT: int = int(os.getenv("SMARTINTAKE_MEMORY_KEEP_RECENT", "4"))

# ---------------------------------------------------------------------------
# Failed-attempt escalation (see session.py)
# Addresses feedback: "No failed-attempt counter or escalation logic
# anywhere ... after two failed extraction attempts, fall back to asking
# the user a direct clarifying question."
# ---------------------------------------------------------------------------
MAX_FAILED_ATTEMPTS_BEFORE_FALLBACK: int = int(
    os.getenv("SMARTINTAKE_MAX_FAILED_ATTEMPTS", "2")
)

# ---------------------------------------------------------------------------
# Storage / logging locations
# ---------------------------------------------------------------------------
OUTPUT_DIR: str = os.getenv("SMARTINTAKE_OUTPUT_DIR", "output")
DEBUG_LOG_PATH: str = os.getenv("SMARTINTAKE_DEBUG_LOG", "debug.log")
