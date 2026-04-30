"""Assemble the final response from resolved inputs and classification outputs."""

from __future__ import annotations

from typing import Any

from .payment_risk_scoring import (
    build_payment_summary,
    calculate_risk_score,
    classify_risk,
)
from .hardship_action_recommendations import build_recommendations
from .payment_risk_models import PaymentRiskRequest


def build_summary(
    customer_id: str,
    risk_tier: str,
    account_state: dict[str, Any],
    recommendations: list[dict[str, Any]],
) -> str:
    balance = float(account_state.get("current_balance_usd") or 0)
    days_past_due = account_state.get("days_past_due") or 0

    if risk_tier == "low":
        return (
            f"Customer {customer_id} is current with no risk indicators. "
            "No proactive support action needed."
        )

    headline = {
        "moderate": "shows early warning signs of payment difficulty",
        "high": "is at high risk of delinquency",
        "critical": "is at critical risk of disconnection",
    }.get(risk_tier, "shows risk indicators")

    parts = [f"Customer {customer_id} {headline}."]
    if balance > 0 or days_past_due > 0:
        parts.append(
            f"Current balance ${balance:.0f}; {days_past_due} days past due."
        )
    if recommendations:
        top = recommendations[0]
        parts.append(f"Top recommended action: `{top['type']}` ({top['priority']}).")
    return " ".join(parts)


def build_response(resolved: dict[str, Any]) -> dict[str, Any]:
    customer_id = resolved["customer_id"]
    payments_account = resolved["payments_account"]
    invoices = resolved["invoices"]
    request: PaymentRiskRequest = resolved["params"]

    payment_history = payments_account.get("payment_history", [])
    payment_summary = build_payment_summary(payment_history, request.lookback_invoices)

    invoice_totals = [
        float(inv["total"]) for inv in invoices if "total" in inv
    ][-request.lookback_invoices:]
    avg_invoice = (
        sum(invoice_totals) / len(invoice_totals) if invoice_totals else 0.0
    )

    risk_score = calculate_risk_score(payments_account, payment_summary, avg_invoice)
    risk_tier, factors = classify_risk(payments_account, payment_summary, avg_invoice, request)
    recommendations = build_recommendations(risk_tier, payments_account, payment_summary)
    summary = build_summary(customer_id, risk_tier, payments_account, recommendations)

    active_plan = next(
        (p for p in payments_account.get("payment_plans", []) if p.get("status") == "active"),
        None,
    )
    active_assistance = next(
        (a for a in payments_account.get("assistance_history", []) if a.get("status") == "active"),
        None,
    )

    return {
        "agent": "payment_risk_hardship_agent",
        "status": "completed",
        "customer_id": customer_id,
        "as_of": resolved["as_of"].isoformat(),
        "risk_tier": risk_tier,
        "risk_score": risk_score,
        "current_balance_usd": round(float(payments_account.get("current_balance_usd") or 0), 2),
        "days_past_due": int(payments_account.get("days_past_due") or 0),
        "delinquency_stage": payments_account.get("delinquency_stage", "current"),
        "shutoff_warning_active": bool(payments_account.get("shutoff_warning_active")),
        "shutoff_warning_date": payments_account.get("shutoff_warning_date"),
        "autopay_enabled": bool(payments_account.get("autopay_enabled")),
        "average_invoice_usd": round(avg_invoice, 2),
        "payment_summary": payment_summary,
        "prior_support": {
            "payment_plans_count": len(payments_account.get("payment_plans", [])),
            "active_payment_plan": active_plan,
            "assistance_enrollments_count": len(payments_account.get("assistance_history", [])),
            "active_assistance_program": active_assistance,
        },
        "contributing_factors": factors,
        "recommendations": recommendations,
        "summary": summary,
    }
