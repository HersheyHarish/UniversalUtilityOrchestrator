from __future__ import annotations

"""Entry point for the standalone billing agent.

Run as a CLI for interactive testing:    python -m src.agents.billing.cli
"""

from pprint import pprint

from src.agents.billing.app import BillingPayload, app, handle_billing_request


def run_cli() -> None:
    print("Billing agent CLI. Enter a billing query, or type `exit` to quit.")
    while True:
        try:
            query = input("> ").strip()
        except EOFError:
            break

        if not query or query.lower() in {"exit", "quit"}:
            break

        try:
            response = handle_billing_request(BillingPayload(query=query))
            print()
            answer = response.get("answer")
            if answer is None:
                answer = response.get("result", {}).get("answer")
            if answer is None:
                raise KeyError("answer")
            print(answer)
            print()
        except Exception as exc:
            pprint({"status": "failed", "error": str(exc)})


if __name__ == "__main__":
    run_cli()
