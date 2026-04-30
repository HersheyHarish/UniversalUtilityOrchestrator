"""Tier-driven hardship and outreach recommendations."""

from __future__ import annotations

from typing import Any


def _payment_plan_recommendation(
    balance: float,
    installments: int,
    priority: str,
    rationale: str,
) -> dict[str, Any]:
    details = (
        {
            "balance_usd": round(balance, 2),
            "suggested_installments": installments,
            "per_installment_usd": round(balance / installments, 2),
        }
        if balance > 0
        else None
    )
    return {
        "type": "payment_plan",
        "priority": priority,
        "rationale": rationale,
        "details": details,
    }


def build_recommendations(
    tier: str,
    account_state: dict[str, Any],
    payment_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    balance = float(account_state.get("current_balance_usd") or 0)
    autopay = bool(account_state.get("autopay_enabled"))

    if tier == "critical":
        recommendations.append({
            "type": "immediate_outreach",
            "priority": "critical",
            "rationale": (
                "Customer is at imminent risk of disconnection or has serious delinquency. "
                "Direct outreach within 24h is the highest priority."
            ),
            "details": {"channel": "phone", "urgency": "within_24h"},
        })
        recommendations.append({
            "type": "hardship_review",
            "priority": "high",
            "rationale": (
                "Severe delinquency often indicates financial hardship; eligibility review "
                "for assistance programs is warranted."
            ),
            "details": None,
        })
        recommendations.append(_payment_plan_recommendation(
            balance, installments=6, priority="high",
            rationale="Splitting the outstanding balance over 6 months avoids further escalation.",
        ))

    elif tier == "high":
        recommendations.append(_payment_plan_recommendation(
            balance, installments=3, priority="high",
            rationale="Splitting current balance into installments avoids further delinquency.",
        ))
        recommendations.append({
            "type": "hardship_review",
            "priority": "medium",
            "rationale": (
                "Pattern of late or partial payments may indicate financial strain; "
                "eligibility review for assistance programs recommended."
            ),
            "details": None,
        })
        recommendations.append({
            "type": "due_date_adjustment",
            "priority": "low",
            "rationale": "Aligning due date with paycheck cadence may reduce late payments.",
            "details": None,
        })

    elif tier == "moderate":
        recommendations.append({
            "type": "due_date_adjustment",
            "priority": "medium",
            "rationale": "Aligning the due date with paycheck cadence often resolves occasional late payments.",
            "details": None,
        })
        if not autopay:
            recommendations.append({
                "type": "autopay_enrollment",
                "priority": "medium",
                "rationale": "Autopay would prevent future late payments without manual intervention.",
                "details": None,
            })
        if balance > 0:
            recommendations.append(_payment_plan_recommendation(
                balance, installments=2, priority="low",
                rationale="Optional installment plan if the balance feels burdensome.",
            ))

    return recommendations
