# SmartIntake — AI-Powered Regulatory Intake System

SmartIntake is an intelligent, multi-turn regulatory intake and extraction
chatbot built on **Anthropic Claude** and **Pydantic**. It is designed for
compliance, risk, and legal operations teams to capture, validate, and
record regulatory incidents, examinations, sanctions hits, and filings
through natural conversation.

> This version is a full refactor of the original capstone submission,
> written to resolve every point raised in the attached capstone
> evaluation report. See [`CHANGES_SUMMARY.md`](./CHANGES_SUMMARY.md) for a
> concise bullet list, and the "Feedback Resolution Map" section below for
> a point-by-point mapping to the reviewer's report.

---

## Features

- **Dynamic Tool-Use Extraction:** Uses Claude's native tool-use
  capability to extract structured regulatory data from free-form text,
  progressively across multiple turns.
- **Bounded, Two-Tier Conversation Memory:** Short sessions keep full
  verbatim history ("buffer mode"); sessions exceeding a configurable
  turn threshold automatically condense older turns into a running
  summary ("summary mode"), so the prompt sent to the model never grows
  without bound.
- **Strict, Defense-in-Depth Validation:** Pydantic data models enforce
  the regulatory schema; a dedicated guardrails module adds identifier
  (PII) pattern detection and out-of-scope screening as a deterministic
  backstop underneath the model's own instructed behaviour.
- **Never Crashes on an API Hiccup:** Every single Anthropic API call
  goes through a defensive wrapper with retry/backoff and typed
  success/failure results — a rate limit, timeout, or transient 5xx
  degrades gracefully instead of taking down the session.
- **Failed-Attempt Escalation:** After two consecutive extraction/
  validation failures on the same field, the system falls back to a
  static, deterministic clarifying question instead of relying on the
  LLM indefinitely.
- **Verified Log-Safety:** The `log_safe` flag on every saved record is
  computed by actually scanning the record for identifier-like patterns,
  not hardcoded.
- **Automated Record Storage:** Serializes and saves confirmed intake
  records to disk with audit logging that never writes raw user text to
  the debug log.
- **Confirm-Before-Save Gate:** No record is ever persisted without an
  explicit confirmation step — now shared by **both** execution modes.
- **Dual Execution Modes:**
  - **Automated Test Suite Mode** (`main_Anth.py`): Runs the spec's own
    Appendix A scenarios (`T1`–`T5`) end-to-end with zero manual input.
  - **Interactive CLI Mode** (`main_Anth_CLI.py`): Real-time
    conversational interface for logging incidents live.

---

## Architecture

```text
├── main_Anth_CLI.py   # Interactive CLI — thin I/O driver around session.IntakeSession
├── main_Anth.py        # Automated T1–T5 batch harness — thin driver around the same engine
├── session.py          # Shared intake engine: extraction, memory, validation, confirm gate
├── llm_client.py        # Defensive wrapper around every Anthropic API call (retry, no raises)
├── memory.py            # Two-tier bounded conversation memory (buffer <-> summary mode)
├── guardrails.py        # Deterministic PII/identifier detection + out-of-scope screening
├── prompts.py            # System prompts: few-shot examples, tipping-off constraints,
│                          #   static fallback question table
├── tools.py               # Anthropic tool schema for structured extraction
├── schema.py               # Pydantic IntakeRecordAnth model + submitting_team validator
├── storage.py               # Record persistence + audit logging (verified log_safe)
├── config.py                 # Centralized environment/config loading
├── requirements.txt
├── .env.example
└── output/                    # Saved records + debug.log land here
```

**Why this structure:** the original codebase implemented the entire
extraction → validation → follow-up → save loop *twice* — once in each
entry point — with the two copies already diverging (only the CLI had a
confirmation gate). `session.py` now contains that logic exactly once;
`main_Anth.py` and `main_Anth_CLI.py` are pure I/O drivers around it. This
means every fix below (retry handling, memory, guardrails, escalation)
automatically applies to both execution modes, and there is no
"forgot to fix the other file" risk going forward.

---

## Installation & Setup

Clone the repository:

```bash
git clone https://github.com/your-username/smart-intake.git
cd smart-intake
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure environment variables — copy the example file and fill in your
key:

```bash
cp .env.example .env
```

At minimum, set `ANTHROPIC_API_KEY` in `.env`. All other variables are
optional and documented inline in `.env.example` / `config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `SMARTINTAKE_MODEL` | `claude-haiku-4-5` | Model used for all calls |
| `SMARTINTAKE_MAX_RETRIES` | `3` | Retry attempts for transient API errors |
| `SMARTINTAKE_RETRY_BASE_DELAY` | `1.5` | Base seconds for exponential backoff |
| `SMARTINTAKE_MEMORY_THRESHOLD` | `10` | Raw turns kept before switching to summary mode |
| `SMARTINTAKE_MEMORY_KEEP_RECENT` | `4` | Verbatim turns always kept once in summary mode |
| `SMARTINTAKE_MAX_FAILED_ATTEMPTS` | `2` | Consecutive failures before static fallback question |
| `SMARTINTAKE_OUTPUT_DIR` | `output` | Where saved JSON records are written |
| `SMARTINTAKE_DEBUG_LOG` | `debug.log` | Audit log path |

---

## Usage

### Running the Interactive CLI

```bash
python main_Anth_CLI.py
```

Type `exit`, `quit`, or `q` at any time to end the session.

### Running the Automated Test Suite (T1–T5)

```bash
python main_Anth.py
```

This replays five realistic AML/compliance scenarios end-to-end
(SAR/STR filing, a multi-turn sanctions match, a clean single-turn
regulatory examination, an out-of-scope query, and a multi-turn fraud
investigation), auto-confirming the save gate for each so the whole suite
runs unattended.

---

## Logging & Auditing

SmartIntake automatically generates audit trails:

- `debug.log`: Execution flow, missing-field errors, token usage, and
  identifier-pattern findings — **never raw user text or extracted field
  values**.
- `output/`: Successfully validated and confirmed JSON intake records,
  timestamped for compliance archiving. Each record now includes a
  **verified** `log_safe` flag (see below) instead of a hardcoded one.

---

## Feedback Resolution Map

Every point from the capstone evaluation report, and how it is addressed:

| # | Feedback | Resolution |
|---|---|---|
| 1 | **Critical** — No memory-tier implementation; `conversation_history` grows unbounded | `memory.py`: new `ConversationMemory` class with buffer mode (verbatim, ≤10 turns) and summary mode (LLM-condensed + deterministic fallback, beyond 10 turns) |
| 2 | **Critical** — No `try/except` around any Anthropic API call | `llm_client.py`: every call funnels through `safe_create()`, which retries transient errors and never raises; all failure paths degrade gracefully (see `session.py`) |
| 3 | Zero few-shot examples in `prompts.py` | `prompts.py`: `EXTRACTION_SYSTEM` now embeds two realistic AML few-shot examples |
| 4 | No tipping-off constraint anywhere | Added explicit tipping-off language to `EXTRACTION_SYSTEM`, `CONFIRMATION_SYSTEM`, and `FOLLOWUP_SYSTEM` |
| 5 | `submitting_team` validator has no digit check or identifier-pattern check; rejects legitimate one-word team names like "Compliance"/"KYC" | `schema.py` + `guardrails.py`: digit check, identifier-pattern check, and a known-team-vocabulary/acronym allowlist so "Compliance"/"KYC"/"AML" pass while "Priya" is still rejected |
| 6 | No proactive out-of-scope or identifier screening before the LLM call | `guardrails.looks_out_of_scope()` is checked in `session.py` before every extraction call on a session's opening message |
| 7 | `tools.py`'s `"required"` lists all five fields, in tension with progressive multi-turn extraction | `tools.py`: `"required": []`, with completeness enforced by Pydantic instead |
| 8 | `requirements.txt` lists LangChain packages never actually used | Removed; only `anthropic`, `pydantic`, `python-dotenv` remain |
| 9 | No failed-attempt counter or escalation logic | `session.py` + `config.py`: after `SMARTINTAKE_MAX_FAILED_ATTEMPTS` (default 2) consecutive validation failures, the system falls back to a static question from `prompts.FIELD_QUESTIONS` |
| 10 | No static fallback question table for follow-ups | `prompts.py`: `FIELD_QUESTIONS` dict, used both on repeated failure and whenever the follow-up/confirmation LLM call itself fails |
| 11 | `log_safe: True` hardcoded rather than verified | `storage.py` + `guardrails.scan_record_for_identifiers()`: `log_safe` is now computed from an actual scan of the record |
| 12 | No `extra="forbid"` on the Pydantic model | `schema.py`: `model_config = ConfigDict(extra="forbid")` |
| 13 | README rough edges (stray "Bash" label, malformed clone URL, missing space in "##Install") | Fixed in this document |
| 14 | *(Strength, preserved)* Confirm-before-save gate in `main_Anth_CLI.py` | Now in `session.IntakeSession.submit_confirmation()`, shared by **both** entry points |
| 15 | *(Strength, preserved)* Embedded T1–T5 automated test harness in `main_Anth.py` | Preserved verbatim as scenarios in `main_Anth.py`, now also exercising the confirm-before-save gate |

---

## Known Limitations / Honest Notes

- `guardrails.looks_out_of_scope()` and the identifier-pattern regexes are
  intentionally simple, explainable heuristics — a defense-in-depth
  backstop layered *underneath* the model's own instructed behaviour, not
  a replacement for it or a claim of perfect PII detection.
- The out-of-scope backstop is only applied to a session's opening
  message (when nothing has been collected yet), by design — this avoids
  false positives on normal in-flow answers like a bare team name or a
  one-word urgency confirmation.
- `debug.log` and `output/` are created relative to the working directory
  the process is launched from; set `SMARTINTAKE_OUTPUT_DIR` /
  `SMARTINTAKE_DEBUG_LOG` for deployment-specific paths.
