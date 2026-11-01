"""
main_Anth.py
============
Automated system-validation test harness
"""

from __future__ import annotations

import json
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY, OUTPUT_DIR
from session import IntakeSession

Path(OUTPUT_DIR).mkdir(exist_ok=True)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def run_session(
    initial_message: str, additional_turns: list[str] | None = None
) -> object | None:
    """Feed a scripted scenario through a fresh IntakeSession and print the
    transcript, auto-confirming whenever the save gate engages (this is a
    non-interactive harness, so there is no human to answer y/n)."""
    session = IntakeSession(client=client)
    all_messages = [initial_message] + (additional_turns or [])

    print(f"\n{'=' * 60}")
    print("SmartIntake — Regulatory Intake Session")
    print(f"{'=' * 60}\n")

    for user_input in all_messages:
        print(f"[Turn {session.turns_taken + 1}] User: {user_input}")

        outcome = session.handle_message(user_input)
        turn_no = session.turns_taken

        if outcome.kind == "confirmation_request":
            print(f"[Turn {turn_no}] SmartIntake:\n{outcome.message}\n")
            print(f"[Turn {turn_no}] Auto-confirming (non-interactive batch mode): yes")
            save_outcome = session.submit_confirmation(True)
            print(f"✓ Record saved: {save_outcome.filepath}")
            print(json.dumps(save_outcome.record.model_dump(), indent=2))
            return save_outcome.record

        print(f"[Turn {turn_no}] SmartIntake: {outcome.message}\n")

    print("Session ended without a complete record.\n")
    return None


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("RUNNING SYSTEM VALIDATION TEST SUITE (T1 - T5)")
    print("=" * 80)

    # T1: SAR/STR Filing (Critical Urgency, Single-turn extraction with team confirmation)
    print("\n--- Test T1: SAR/STR Filing (US / BSA_AML) ---")
    run_session(
        initial_message=(
            "Transaction monitoring here. We have a structuring pattern flagged "
            "on a business account in our US portfolio. Need to file a SAR with FinCEN "
            "— the 30-day clock is almost up."
        ),
        additional_turns=["Transaction Monitoring Team"],  # Confirm submitting team
    )

    # T2: Sanctions Hit (Partial Path — Requires follow-up for missing urgency & team)
    print("\n--- Test T2: Sanctions Match (Singapore / OFAC_SDN — Multi-turn) ---")
    run_session(
        initial_message=(
            "Hi, we have a new OFAC sanctions hit on a customer in our Singapore business."
        ),
        additional_turns=[
            "Critical — immediate freeze required.",  # Turn 2: Urgency
            "Sanctions Screening Team",  # Turn 3: Submitting Team
        ],
    )

    # T3: Regulatory Examination (Clean Single-turn Extraction)
    print("\n--- Test T3: Regulatory Examination (UK / FCA_SYSC) ---")
    run_session(
        initial_message=(
            "KYC Operations here. The FCA has issued a Section 165 information request "
            "for our UK retail book. We have 10 business days to respond."
        )
    )

    # T4: Non-compliance Fallback
    print("\n--- Test T4: Non-Compliance Fallback ---")
    run_session(
        initial_message=(
            "Can you tell me what the best restaurants are near our Mumbai office?"
        )
    )

    # T5: Fraud Investigation (Partial Path — Missing urgency deadline)
    print("\n--- Test T5: Fraud Investigation (India / RBI_PMLA) ---")
    run_session(
        initial_message=(
            "Fraud ops team. We've detected a pattern of account takeover attempts on "
            "our India payments platform — looks like credential stuffing. Need to log this formally."
        ),
        additional_turns=["Urgent — ongoing active pattern."],  # Turn 2: Urgency
    )
