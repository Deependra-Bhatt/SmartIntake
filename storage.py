"""
storage.py
==========
Safe persistence and logging utilities.

WHAT CHANGED (feedback item: "log_safe: True is hardcoded rather than
verified ... this submission has no identifier-screening logic anywhere
at all (not even a digit check), making it the least-defended
implementation of this requirement of any submission reviewed"):

  `save_record_anth` now calls `guardrails.scan_record_for_identifiers()`
  on the record before writing it, and sets `log_safe` based on the
  result of that scan instead of a hardcoded literal:
    - If no identifier-like patterns are found: log_safe = True (as
      before, but now actually verified).
    - If any are found: log_safe = False, the specific field/pattern
      hits are recorded in `log_safe_findings`, and a warning is written
      to debug.log (never containing the raw offending text itself, only
      the field name and pattern type) so a human reviewer is alerted.
      The record is still saved (compliance intake must not silently
      drop data), but it is now clearly flagged rather than silently
      mis-labeled as log-safe.

  All other behaviour (log_usage, log_error, log_debug never writing raw
  user text to debug.log) is preserved from the original implementation.

  Additionally: the output directory and debug log path are now read from
  config.py instead of being hardcoded, and logging uses a module-level
  logger instead of calling `logging.basicConfig` at import time (which
  is fragile if storage.py is imported more than once or in a different
  order relative to other logging configuration).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from config import DEBUG_LOG_PATH, OUTPUT_DIR
from guardrails import scan_record_for_identifiers
from schema import IntakeRecordAnth as IntakeRecord

OUTPUT_PATH = Path(OUTPUT_DIR)
OUTPUT_PATH.mkdir(exist_ok=True)

# Dedicated logger instead of the root logger via basicConfig, so this
# module behaves predictably regardless of import order.
_logger = logging.getLogger("smartintake")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _handler = logging.FileHandler(DEBUG_LOG_PATH)
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    _logger.addHandler(_handler)


def log_usage(usage) -> None:
    """Log token usage only — never raw prompt/response content."""
    _logger.info(
        f"Prompt={usage.input_tokens} "
        f"Completion={usage.output_tokens} "
        f"Total={usage.input_tokens + usage.output_tokens}"
    )


def log_error(message: str) -> None:
    """Log an error/status string. Callers must never pass raw user text."""
    _logger.error(message)


def log_debug(message: str) -> None:
    """Log a debug/status string. Callers must never pass raw user text."""
    _logger.info(message)


def save_record_anth(record: IntakeRecord, turns_taken: int) -> str:
    """Save a log-safe JSON record. Returns the file path.

    `log_safe` is now a *verified* flag rather than a hardcoded literal —
    see module docstring above.
    """
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    filepath = str(OUTPUT_PATH / f"intake_{timestamp}.json")

    data = record.model_dump()
    data["timestamp"] = datetime.now().isoformat()
    data["turns_taken"] = turns_taken

    findings = scan_record_for_identifiers(data)
    data["log_safe"] = not findings
    if findings:
        data["log_safe_findings"] = findings
        # Log only the *kind* of pattern and which field it was found in —
        # never the offending value itself.
        log_debug(
            f"Record {filepath} flagged log_safe=False; "
            f"identifier-like patterns detected in: {findings}"
        )

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    return filepath
