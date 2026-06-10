"""One-shot LLM baseline: single Azure OpenAI call, no tools, no retrieval.

Returns the same shape as a deployed-orchestrator run so the eval harness can
treat both systems uniformly:

    {
      "response": str,
      "agents_used": [],            # baseline has none
      "total_latency_ms": int,
      "planner_tokens": 0,
      "synth_tokens": 0,
      "total_tokens": int,          # prompt + completion
    }

Env vars (set via `source azure/.env.deploy` then export the OpenAI ones):
    AZURE_OPENAI_ENDPOINT       e.g. https://llm-ua-aryag01.services.ai.azure.com
    AZURE_OPENAI_API_KEY        pulled from Key Vault (see metrics/README.md)
    AZURE_OPENAI_DEPLOYMENT     default: gpt-4o
    AZURE_OPENAI_API_VERSION    default: 2024-10-21
"""

from __future__ import annotations

import os
import time

from openai import AzureOpenAI

_SYSTEM = """You are a customer support assistant for a utility company.
Answer the customer's question as completely and accurately as you can using
ONLY general knowledge. You do not have access to billing, meter, weather, or
outage systems — answer the question to the best of your ability anyway and
be explicit when you are guessing or lack data.

Guidelines:
- Address the customer directly.
- If the query references a customer ID like CUST-1001, treat that customer as
  a generic residential account.
- Keep responses focused and grounded — do not invent specific numbers."""


def _client() -> AzureOpenAI:
    endpoint_raw = os.environ["AZURE_OPENAI_ENDPOINT"]
    endpoint = endpoint_raw.split("/openai")[0].split("/api/")[0].rstrip("/")
    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )


def run(query: str, customer_id: str | None = None) -> dict:
    """Single LLM call. Returns a dict matching the orchestrator's run shape."""
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    client = _client()

    user_msg = query
    if customer_id:
        user_msg = f"[customer_id={customer_id}] {query}"

    started = time.perf_counter()
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_completion_tokens=1500,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    text = resp.choices[0].message.content or ""
    usage = resp.usage
    total_tokens = usage.total_tokens if usage else 0

    return {
        "response": text,
        "agents_used": [],
        "total_latency_ms": latency_ms,
        "planner_tokens": 0,
        "synth_tokens": total_tokens,
        "total_tokens": total_tokens,
    }


if __name__ == "__main__":
    import json
    out = run("Why was CUST-1001 charged so much for July 2019?", "CUST-1001")
    print(json.dumps(out, indent=2))
