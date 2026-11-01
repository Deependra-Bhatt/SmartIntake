"""
tools.py
========
Anthropic native tool ("input_schema") definition used for structured
extraction.

WHAT CHANGED (feedback item: "'required' lists all five fields ... in
direct tension with the system's own design: tool_choice is set to 'auto'
rather than forced, so if the model takes the 'required' declaration
seriously it may simply decline to call the tool at all until it believes
it has every field"):

  `"required"` is now an empty list, not all five field names.

  WHY: SmartIntake is explicitly designed for *progressive, multi-turn*
  extraction — a user may only give the query type and jurisdiction on
  turn 1, with urgency and submitting_team following on later turns. If
  the tool schema declares every field required, a strictly schema-
  following model can reasonably decide not to call the tool at all until
  it has every value in hand, which would starve the incremental
  collection flow and force a fallback to plain-text replies on every
  turn until the very last one.

  Making the fields optional at the *tool* level and enforcing
  completeness at the *Pydantic* level (schema.py) — which is exactly
  what the rest of the system already does via ValidationError-driven
  follow-up questions — resolves the inconsistency the reviewer flagged,
  and matches the pattern used by every other reviewed submission.
"""

INTAKE_TOOL = [
    {
        "name": "extract_intake_record",
        "description": (
            "Extract whatever AML/compliance intake fields are present in "
            "the conversation so far. Not every field needs to be present "
            "on every call — this tool is used progressively across "
            "multiple turns, so partial extractions (even a single field) "
            "are expected and useful. Only include a field if its value "
            "is actually stated or clearly implied in the conversation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": [
                        "sar_str_filing",
                        "kyc_exception",
                        "transaction_dispute",
                        "sanctions_match",
                        "regulatory_examination",
                        "fraud_investigation",
                        "general_enquiry",
                    ],
                },
                "regulation_ref": {
                    "type": "string",
                    "enum": [
                        "FATF_R20",
                        "BSA_AML",
                        "FCA_SYSC",
                        "RBI_PMLA",
                        "MAS_AML",
                        "PCI_DSS",
                        "OFAC_SDN",
                        "other",
                    ],
                },
                "jurisdiction": {
                    "type": "string",
                    "enum": [
                        "india",
                        "uk",
                        "singapore",
                        "usa",
                        "eu",
                        "multi_jurisdictional",
                        "general",
                    ],
                },
                "urgency": {
                    "type": "string",
                    "enum": [
                        "routine",
                        "standard",
                        "urgent",
                        "critical",
                    ],
                },
                "submitting_team": {
                    "type": "string",
                    "description": (
                        "The name of the team or department submitting "
                        "this request (e.g. 'KYC', 'Sanctions Screening "
                        "Team'). Must NOT be an individual person's name."
                    ),
                },
            },
            "required": [],
        },
    }
]
