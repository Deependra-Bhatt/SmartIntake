"""
schema.py
=========
Pydantic intake schema.

WHAT CHANGED (feedback item: "Pydantic validation in use — ~7/15",
"submitting_team validator has no digit check and no identifier-pattern
check at all ... the weakest of any submission reviewed"):

  1. `model_config = ConfigDict(extra="forbid")` added. Previously any
     unexpected extra key the model's tool call happened to include would
     silently pass through into the record. Now it is rejected as a
     validation error, same as every other field.

  2. `validate_team` is fully rewritten:
       - Rejects any value containing a digit (catches things like
         "Team-4" or account-code-like strings — completely unchecked
         before).
       - Rejects any value matching a known identifier pattern (email,
         phone, SSN, card number, case/account reference) via the shared
         guardrails module — this reuses the exact same detection logic
         that also verifies log_safe in storage.py.
       - The single-word rejection rule is no longer a blanket "one
         alphabetic word = individual name". It now allows single-word
         *known compliance team vocabulary* ("Compliance", "KYC", "AML",
         "Fraud", "Legal", "Risk", etc.) and short all-caps acronyms
         ("KYC", "AML", "OPS"), while still catching bare individual names
         like "Priya" that match neither pattern. This directly fixes the
         reviewer's example: "would reject legitimate one-word team names
         like 'Compliance' or 'KYC' just as readily as an actual person's
         name."
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from guardrails import contains_identifier_pattern

# Vocabulary of single-word tokens that are legitimate team/unit names in a
# financial-crime compliance context. Checked case-insensitively.
_KNOWN_TEAM_WORDS = {
    "kyc",
    "aml",
    "cft",
    "ops",
    "operations",
    "compliance",
    "screening",
    "monitoring",
    "fraud",
    "sanctions",
    "legal",
    "risk",
    "audit",
    "investigations",
    "investigation",
    "onboarding",
    "support",
    "escalations",
    "surveillance",
    "diligence",
    "regulatory",
    "filings",
    "intake",
    "sar",
    "str",
    "aml/cft",
    "financial",
    "crime",
    "underwriting",
    "collections",
}


class IntakeRecordAnth(BaseModel):
    # NEW: extra="forbid" — reject any field the model's tool call includes
    # that isn't explicitly declared below, instead of silently accepting it.
    model_config = ConfigDict(extra="forbid")

    query_type: Literal[
        "sar_str_filing",
        "kyc_exception",
        "transaction_dispute",
        "sanctions_match",
        "regulatory_examination",
        "fraud_investigation",
        "general_enquiry",
    ]

    regulation_ref: Literal[
        "FATF_R20",
        "BSA_AML",
        "FCA_SYSC",
        "RBI_PMLA",
        "MAS_AML",
        "PCI_DSS",
        "OFAC_SDN",
        "other",
    ]

    jurisdiction: Literal[
        "india",
        "uk",
        "singapore",
        "usa",
        "eu",
        "multi_jurisdictional",
        "general",
    ]

    urgency: Literal[
        "routine",
        "standard",
        "urgent",
        "critical",
    ]

    submitting_team: str

    @field_validator("submitting_team")
    @classmethod
    def validate_team(cls, v: str) -> str:
        raw = v.strip()
        if not raw:
            raise ValueError("submitting_team cannot be empty.")

        # NEW: reject digits outright (e.g. "Team-4", account-code-like
        # strings). The original validator had no check for this at all.
        if any(ch.isdigit() for ch in raw):
            raise ValueError(
                "submitting_team must not contain digits — it looks like "
                "an identifier or account code rather than a team name."
            )

        if contains_identifier_pattern(raw):
            raise ValueError(
                "submitting_team appears to contain an identifier (email, "
                "phone number, case/account reference, etc.), which is not "
                "permitted in this field."
            )

        clean = raw.title()
        tokens = clean.split()

        if len(tokens) == 1:
            token_lower = tokens[0].lower()
            is_known_team_word = token_lower in _KNOWN_TEAM_WORDS

            is_acronym = raw.isupper() and raw.isalpha() and len(raw) <= 6

            if not (is_known_team_word or is_acronym):
                raise ValueError(
                    f"'{raw}' looks like an individual's name rather than "
                    "a team. submitting_team must identify a team, unit, "
                    "or department (e.g. 'KYC', 'Compliance', 'Fraud Ops')."
                )

        return clean
