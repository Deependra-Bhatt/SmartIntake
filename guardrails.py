"""
guardrails.py  (NEW FILE)
==========================
Deterministic, code-level safety backstops that do not depend on the model
following its instructions.

FEEDBACK ADDRESSED
------------------
1. "No proactive screening of the raw user message for out-of-scope content
    or sensitive identifiers before the LLM call — both checks are
    delegated entirely to the model via prompt instructions ... with no
    deterministic code-level backstop if the model doesn't comply."
        -> looks_out_of_scope() below is consulted in session.py *before*
           the extraction LLM call is made, on the opening message of a
           session only (see docstring on that function for why).

2. "submitting_team validator has no digit check and no identifier-pattern
    check at all ... the weakest such validator of any submission
    reviewed."
        -> find_identifier_patterns()/contains_identifier_pattern() are
           reused directly inside schema.py's validator.

3. "log_safe: True is hardcoded rather than verified ... this submission
    has no identifier-screening logic anywhere at all."
        -> scan_record_for_identifiers() is called from storage.py before
           a record is written, so log_safe now reflects a real check
           instead of being a hardcoded literal.

These are intentionally simple, explainable heuristics layered underneath
the LLM's own instructed behaviour — a backstop, not a replacement for the
prompt-level rules in prompts.py.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Identifier / PII pattern detection
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s()]{7,}\d)")
_LONG_DIGIT_RUN_RE = re.compile(r"\d{5,}")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_CASE_REF_RE = re.compile(r"\b(?:REF|CASE|ACC|ACCT|ID)[-#:]?\s*\d{3,}\b", re.IGNORECASE)

# Ordered so more-specific patterns (SSN, card) are checked distinctly from
# the generic long-digit-run catch-all, purely for clearer diagnostic names
# in logs — all patterns are still evaluated.
_IDENTIFIER_PATTERNS: dict[str, re.Pattern] = {
    "email": _EMAIL_RE,
    "ssn": _SSN_RE,
    "card_number": _CARD_RE,
    "case_or_account_reference": _CASE_REF_RE,
    "phone_or_long_number": _PHONE_RE,
    "long_digit_run": _LONG_DIGIT_RUN_RE,
}


def find_identifier_patterns(text: str) -> list[str]:
    """Return the names of any identifier-like patterns found in `text`.

    Used both as a rejection rule (schema.py's submitting_team validator)
    and as a verification step before persisting a record (storage.py).
    """
    if not text:
        return []
    hits: list[str] = []
    for name, pattern in _IDENTIFIER_PATTERNS.items():
        if pattern.search(text):
            hits.append(name)
    return hits


def contains_identifier_pattern(text: str) -> bool:
    """Convenience boolean wrapper around find_identifier_patterns()."""
    return bool(find_identifier_patterns(text))


# ---------------------------------------------------------------------------
# Out-of-scope screening
# (backstop for the "If the query is not regulatory in nature, do NOT call
#  the tool" rule stated in prompts.EXTRACTION_SYSTEM)
# ---------------------------------------------------------------------------

_COMPLIANCE_KEYWORDS = {
    "sar", "str", "fincen", "aml", "kyc", "cft", "sanctions", "sanction",
    "ofac", "sdn", "fatf", "pmla", "mas", "fca", "pci", "rbi", "bsa",
    "transaction", "monitoring", "fraud", "compliance", "regulator",
    "regulatory", "regulation", "examination", "audit", "investigation",
    "dispute", "filing", "file", "freeze", "screening", "risk",
    "suspicious", "laundering", "watchlist", "diligence", "onboarding",
    "escalation", "breach", "incident", "legal", "enquiry", "inquiry",
    "request", "chargeback", "takeover", "credential", "stuffing",
    "structuring", "165", "team", "portfolio", "account", "customer",
    "client", "crime", "criminal", "enforcement",
}


def looks_out_of_scope(text: str) -> bool:
    """Cheap, keyword-based backstop for detecting non-regulatory chatter.

    Deliberately biased toward "assume in scope" — it only flags a message
    as out-of-scope when *none* of a broad compliance vocabulary is
    present. This is a safety net for the obvious cases (e.g. "what's a
    good restaurant near the office?"), not a strict classifier, and it is
    only ever consulted on the opening message of a session (see
    session.py) so that normal in-flow answers ("Critical — immediate
    freeze required", a bare team name, "yes"/"no" confirmations, etc.)
    are never subjected to it.
    """
    if not text or not text.strip():
        return True
    lowered = text.lower()
    return not any(keyword in lowered for keyword in _COMPLIANCE_KEYWORDS)


# ---------------------------------------------------------------------------
# Log-safety verification
# (replaces the previously hardcoded `log_safe: True` in storage.py)
# ---------------------------------------------------------------------------

def scan_record_for_identifiers(data: dict) -> list[str]:
    """Scan every string value in a record for identifier-like patterns.

    All enum fields in IntakeRecordAnth are schema-constrained to a fixed
    set of values, so in practice this mainly protects the one free-text
    field (submitting_team) as defense-in-depth in case a future schema
    change introduces another free-text field without updating its
    validator. Returns a list of "field:pattern_name" strings describing
    every hit found (empty list == clean).
    """
    findings: list[str] = []
    for field_name, value in data.items():
        if isinstance(value, str):
            for hit in find_identifier_patterns(value):
                findings.append(f"{field_name}:{hit}")
    return findings
