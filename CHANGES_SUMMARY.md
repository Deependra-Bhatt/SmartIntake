# SmartIntake Refactor — Summary of Changes

Refactor performed against the capstone evaluation report for
Deependra Bhatt's SmartIntake submission. Every rubric-referenced gap is
resolved; both credited strengths are preserved and, where possible,
strengthened.

## Critical fixes

- **Real two-tier conversation memory** (`memory.py`, new file). Buffer
  mode keeps verbatim turns up to a configurable threshold (default 10);
  beyond that, older turns are condensed into a running summary (LLM-
  generated, with a deterministic non-LLM fallback if that call fails)
  and only the most recent turns are kept verbatim. Prompt size is now
  bounded for the life of a session instead of growing without limit.
- **No more unhandled exceptions around LLM calls** (`llm_client.py`, new
  file). Every `client.messages.create(...)` call in the codebase — for
  extraction, confirmation, follow-up questions, and summarization — now
  goes through a single defensive wrapper that retries transient errors
  with backoff and returns a typed result instead of ever raising.

## Significant gaps closed

- **Few-shot examples added.** `EXTRACTION_SYSTEM` in `prompts.py` now
  embeds two realistic AML/compliance extraction examples, as the spec
  required.
- **Tipping-off constraint added** to `EXTRACTION_SYSTEM`,
  `CONFIRMATION_SYSTEM`, and `FOLLOWUP_SYSTEM` — the system is now
  explicitly instructed to never phrase questions in a way that could
  alert a customer or third party to an investigation.
- **`submitting_team` validation rewritten** (`schema.py` +
  `guardrails.py`, new module): now rejects digits and identifier
  patterns (email, phone, SSN, card number, case/account reference),
  while a curated team-vocabulary/acronym allowlist means legitimate
  one-word team names ("Compliance", "KYC", "AML") are no longer
  falsely rejected the way they were before — only genuine individual
  names like "Priya" are still caught.

## Notable gaps closed

- **Deterministic out-of-scope + identifier screening** (`guardrails.py`)
  now runs in code *before* the extraction LLM call, as a backstop
  independent of whether the model follows its own instructions.
- **`tools.py`'s `"required"` list emptied**, removing the internal
  inconsistency with `tool_choice="auto"` and progressive multi-turn
  extraction; completeness is enforced by Pydantic instead.
- **`requirements.txt` cleaned up** — removed `langchain`,
  `langchain-core`, and `langchain-anthropic`, none of which were ever
  imported anywhere in the original code.
- **Failed-attempt counter + escalation logic added** (`session.py` +
  `config.py`): after two consecutive validation failures, the system
  stops calling the LLM for follow-up wording and asks a static,
  deterministic question from a new `FIELD_QUESTIONS` table instead.
- **`log_safe` is now verified, not hardcoded** (`storage.py`): every
  saved record is scanned for identifier-like patterns before the flag
  is set, and any hits are recorded in the saved JSON and audit log
  (field/pattern name only — never the raw value).
- **`model_config = ConfigDict(extra="forbid")` added** to
  `IntakeRecordAnth`, so an unexpected extra key from a tool call is now
  rejected instead of silently passed through.
- **README.md rewritten**: fixed the stray "Bash" label before code
  fences, the malformed clone URL, the missing space in "##Install", and
  added full environment-variable documentation and an architecture
  section.

## Strengths preserved and extended

- The **confirm-before-save gate**, the one strength credited in
  `main_Anth_CLI.py`, is preserved and moved into the shared
  `session.IntakeSession.submit_confirmation()` engine — it is now
  exercised by **both** the CLI and the automated batch harness, instead
  of only the CLI.
- The **T1–T5 automated test harness** in `main_Anth.py` is preserved
  with the exact same five scenarios, now running through the shared,
  hardened engine (defensive API calls, bounded memory, guardrails,
  and the confirm gate) instead of a separate, unvalidated code path.

## Architectural / code-quality improvements beyond the explicit feedback

- Eliminated ~150 lines of near-duplicate logic between the two entry
  points by extracting a single `session.IntakeSession` engine
  (`session.py`, new file); `main_Anth.py` and `main_Anth_CLI.py` are now
  thin I/O drivers.
- Centralized all environment/config handling in `config.py` instead of
  duplicating `load_dotenv()` / API key / model-name setup in two files.
- `storage.py` now uses a dedicated module logger instead of calling
  `logging.basicConfig()` at import time.
- Removed a dead `from urllib import response` import left over from
  copy/paste in the original `main_Anth.py`.
- Every new module (`memory.py`, `llm_client.py`, `guardrails.py`,
  `session.py`) is fully docstring-annotated explaining both the
  original gap and the specific fix, for future-maintainer clarity.
