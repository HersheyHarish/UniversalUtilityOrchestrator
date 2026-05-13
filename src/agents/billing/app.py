from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from src.agents.shared.query_parsing import extract_customer_id, parse_query_dates

from .facts import BillingFactsEngine
from .rag import PolicyRetriever


app = FastAPI(title="Billing Agent")


BASE_DIR = Path(__file__).resolve().parents[2]
POLICY_DIR = BASE_DIR / "data" / "policies"
VECTOR_STORE_DIR = BASE_DIR / "data" / "vector_store"

facts_engine = BillingFactsEngine()
policy_retriever = PolicyRetriever(POLICY_DIR, VECTOR_STORE_DIR)


class BillingPayload(BaseModel):
    query: str
    customer_id: str | int | None = None
    start_date: str | None = None
    end_date: str | None = None
    claimed_amount: float | None = None
    include_details: bool = False
    max_line_items: int = Field(default=10, ge=1, le=20)
    max_citations: int = Field(default=4, ge=1, le=8)


def build_policy_query(query: str, facts: dict[str, Any]) -> str:
    """Create a richer retrieval query from the user question and billing facts.

    The original user query is often too short to retrieve all relevant policy
    rules. Appending the resolved plan name and line items helps the retriever
    surface the sections that explain the exact charges on the invoice.
    """
    line_item_names = ", ".join(item["description"] for item in facts["line_items"])
    return (
        f"{query}. Relevant plan: {facts['account']['plan_name']}. "
        f"Line items: {line_item_names}. "
        "Retrieve policy text about charges, credits, taxes, surcharges, disputes, and billing explanations."
    )


def resolve_billing_inputs(payload: BillingPayload) -> dict[str, Any]:
    """Parse customer, billing window, and claimed amount from the request."""
    customer_id = payload.customer_id
    start_date = payload.start_date
    end_date = payload.end_date
    claimed_amount = payload.claimed_amount

    if customer_id is None:
        customer_id = extract_customer_id(payload.query)
        if customer_id is None:
            account_ids = sorted(facts_engine.data.get("accounts", {}).keys())
            if len(account_ids) == 1:
                customer_id = account_ids[0]

    if start_date is None or end_date is None:
        parsed_start, parsed_end = parse_query_dates(payload.query)
        if start_date is None and parsed_start is not None:
            start_date = parsed_start.isoformat()
        if end_date is None and parsed_end is not None:
            end_date = parsed_end.isoformat()

    if claimed_amount is None:
        amount_patterns = [
            r"\bcharged\s+\$?(\d+(?:\.\d{1,2})?)\b",
            r"\$\s*(\d+(?:\.\d{1,2})?)\b",
            r"\b(\d+(?:\.\d{1,2})?)\s+dollars\b",
        ]
        for pattern in amount_patterns:
            amount_match = re.search(pattern, payload.query, flags=re.IGNORECASE)
            if amount_match:
                claimed_amount = float(amount_match.group(1))
                break

    if customer_id is None:
        raise ValueError("Billing queries must include a customer id, for example `customer CUST-1001`.")

    if start_date is None or end_date is None:
        customer_invoices = facts_engine.data.get("invoices", {}).get(str(customer_id), [])
        if customer_invoices:
            last = customer_invoices[-1]
            if start_date is None:
                start_date = last.get("billing_start")
            if end_date is None:
                end_date = last.get("billing_end")

    if start_date is None or end_date is None:
        raise ValueError(
            "Billing queries must include a date range like `2025-07-01 - 2025-07-31` or a month like `July 2025`."
        )

    return {
        "customer_id": customer_id,
        "start_date": start_date,
        "end_date": end_date,
        "claimed_amount": claimed_amount,
    }


def try_llm_summary(query: str, facts: dict[str, Any], citations: list[dict[str, Any]]) -> str | None:
    """Ask Ollama for a concise explanation, or return None on any failure."""
    model_name = "llama3.1:8b"
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    system_prompt = (
        "You are a billing explanation assistant. "
        "Use only the provided facts and citations. "
        "Do not invent amounts or policies. "
        "Be direct, concrete, and brief. "
        "Do not use generic customer-service filler. "
        "Do not restate obvious metadata unless it helps explain a charge."
    )
    user_prompt = (
        f"User question: {query}\n\n"
        f"Structured facts: {facts}\n\n"
        f"Policy citations: {citations}\n\n"
        "Write a concise explanation in 3 short paragraphs.\n"
        "Paragraph 1: state the total and the biggest charge drivers with exact amounts.\n"
        "Paragraph 2: explain the rules behind those charges or credits using the cited policy facts. "
        "Keep units precise: kWh values are energy quantities, not dollar amounts, so never prefix kWh values with `$`.\n"
        "Paragraph 3: give one practical next step when the facts support it. If there is a seasonal peak surcharge "
        "line item, recommend shifting high-consumption activities outside peak hours to "
        "reduce future surcharges. If there are autopay or paperless credits, say those discounts are already active. "
        "Do not describe taxes or regulatory fees as customer-actionable. "
        "Do not write meta phrases like 'There is no next step mentioned in this explanation.'\n"
        "Avoid headings, markdown bullets, and vague phrases like 'review your account activity' or 'contact customer service' unless a dispute policy clearly applies."
    )
    try:
        llm = ChatOllama(model=model_name, temperature=0, base_url=ollama_base_url, timeout=45)
        response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        return response.content.strip() if isinstance(response.content, str) else None
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"Ollama LLM failed: {exc}")
        return None


def handle_billing_request(payload: BillingPayload) -> dict[str, Any]:
    """Main request pipeline for the standalone billing endpoint."""
    resolved = resolve_billing_inputs(payload)
    facts = facts_engine.explain_window(
        customer_id=resolved["customer_id"],
        start_date=resolved["start_date"],
        end_date=resolved["end_date"],
        claimed_amount=resolved["claimed_amount"],
        max_line_items=payload.max_line_items,
    )
    citations = policy_retriever.retrieve(
        build_policy_query(payload.query, facts),
        top_k=payload.max_citations,
    )

    answer = try_llm_summary(payload.query, facts, citations)
    if not answer:
        raise HTTPException(status_code=500, detail="LLM failed to generate a summary.")

    response = {
        "agent": "billing_agent",
        "status": "completed",
        "message": f"Billing explanation prepared for {facts['customer_id']}.",
        "answer": answer,
    }
    if payload.include_details:
        response["result"] = {
            **facts,
            "policy_citations": citations,
            "answer": answer,
        }
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    """Simple readiness endpoint for local testing and teammate integration."""
    return {"status": "ok", "agent": "billing_agent"}


@app.post("/api/billing_agent")
def billing_agent(payload: BillingPayload) -> dict[str, Any]:
    """HTTP endpoint that returns a billing explanation for the supplied query."""
    try:
        return handle_billing_request(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
