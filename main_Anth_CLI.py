"""
main_Anth_CLI.py
================
Interactive CLI entry point.

The only things this file is responsible for now: reading input from the
terminal, printing SmartIntake's responses, and asking "start a new
session?" at the end — pure I/O, no business logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY, OUTPUT_DIR
from session import IntakeSession

Path(OUTPUT_DIR).mkdir(exist_ok=True)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

EXIT_COMMANDS = {"exit", "quit", "q"}


def run_interactive_session() -> None:
    """Run an interactive CLI chat session with explicit user confirmation
    before saving. Delegates all extraction/validation/memory logic to
    session.IntakeSession — see module docstring above.
    """
    session = IntakeSession(client=client)

    print(f"\n{'=' * 60}")
    print("SmartIntake — Interactive Regulatory Intake CLI")
    print("Type 'exit', 'quit', or 'q' to end the session.")
    print(f"{'=' * 60}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSession interrupted. Exiting...")
            return

        if not user_input:
            continue

        if user_input.lower() in EXIT_COMMANDS:
            print("Exiting SmartIntake. Goodbye!")
            return

        # --- Confirmation gate ------------------------------------------
        if session.awaiting_confirmation:
            confirmed = IntakeSession.is_affirmative(user_input)
            outcome = session.submit_confirmation(confirmed)

            if outcome.kind == "saved":
                print(
                    f"\n✓ Record confirmed and saved successfully: {outcome.filepath}"
                )
                print(json.dumps(outcome.record.model_dump(), indent=2))
                print("\n" + "-" * 60)
                choice = (
                    input("Would you like to start a new intake session? (y/n): ")
                    .strip()
                    .lower()
                )
                if choice == "y":
                    return run_interactive_session()
                print("Thank you for using SmartIntake. Goodbye!")
                return

            # correction_requested
            print(f"\nSmartIntake: {outcome.message}\n")
            continue

        # --- Normal turn processing --------------------------------------
        outcome = session.handle_message(user_input)

        if outcome.kind == "out_of_scope":
            print(f"\nSmartIntake: {outcome.message}\n")
        elif outcome.kind == "error":
            print(f"\nSmartIntake: {outcome.message}\n")
        elif outcome.kind == "assistant_text":
            print(f"\nSmartIntake: {outcome.message}\n")
        elif outcome.kind == "followup":
            print(f"\nSmartIntake: {outcome.message}\n")
        elif outcome.kind == "confirmation_request":
            print(f"\nSmartIntake:\n{outcome.message}")
            print(
                "SmartIntake: Does this look correct and can I save this record? (y/n): "
            )


if __name__ == "__main__":
    run_interactive_session()
