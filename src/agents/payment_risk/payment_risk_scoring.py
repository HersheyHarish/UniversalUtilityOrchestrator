"""Risk scoring and tier classification for the Payment Risk & Hardship Agent."""

from __future__ import annotations

from typing import Any

from .payment_risk_models import TIER_RANK, PaymentRiskRequest


def build_payment_summary(
    payment_history: list[dict[str, Any]],
    lookback: int,
) -> dict[str, Any]:
    recent = payment_history[-lookback:] if payment_history else []
    counts = {"on_time": 0, "late": 0, "partial": 0, "missed": 0, "pending": 0}
    for record in recent:
        status = record.get("status", "pending")
        counts[status] = counts.get(status, 0) + 1

    closed_count = (
        counts["on_time"] + counts["late"] + counts["partial"] + counts["missed"]
    )
    on_time_rate = (
        round(counts["on_time"] / closed_count, 3) if closed_count > 0 else None
    )

    return {
        "lookback_invoices": lookback,
        "evaluated_count": len(recent),
        "on_time_count": counts["on_time"],
        "late_count": counts["late"],
        "partial_count": counts["partial"],
        "missed_count": counts["missed"],
        "pending_count": counts["pending"],
        "on_time_rate": on_time_rate,
    }


def calculate_risk_score(
    account_state: dict[str, Any],
    payment_summary: dict[str, Any],
    avg_invoice_usd: float,
) -> float:
    """0–100 score combining shutoff status, days past due, bad payment ratio, and balance ratio."""
    score = 0.0

    if account_state.get("shutoff_warning_active"):
        score += 40

    days_past_due = account_state.get("days_past_due") or 0
    score += min(30.0, days_past_due / 2.0)

    bad_weight = (
        payment_summary["missed_count"] * 3
        + payment_summary["partial_count"] * 2
        + payment_summary["late_count"] * 1
    )
    score += min(25.0, bad_weight * 5.0)

    balance = account_state.get("current_balance_usd") or 0
    if avg_invoice_usd > 0:
        ratio = balance / avg_invoice_usd
        score += min(15.0, ratio * 5.0)

    return round(min(100.0, score), 1)


def classify_risk(
    account_state: dict[str, Any],
    payment_summary: dict[str, Any],
    avg_invoice_usd: float,
    request: PaymentRiskRequest,
) -> tuple[str, list[str]]:
    factors: list[str] = []
    tier = "low"

    days_past_due = account_state.get("days_past_due") or 0
    balance = account_state.get("current_balance_usd") or 0
    shutoff_active = bool(account_state.get("shutoff_warning_active"))

    missed = payment_summary["missed_count"]
    partial = payment_summary["partial_count"]
    late = payment_summary["late_count"]
    bad_count = late + partial + missed

    # Critical first
    if shutoff_active:
        tier = "critical"
        factors.append("Shutoff warning is active.")
    elif days_past_due > 60:
        tier = "critical"
        factors.append(f"{days_past_due} days past due (>60).")
    elif missed >= 3:
        tier = "critical"
        factors.append(
            f"{missed} missed payments in last {payment_summary['lookback_invoices']} invoices."
        )

    # High
    if tier != "critical":
        if days_past_due > 30:
            tier = "high"
            factors.append(f"{days_past_due} days past due (>30).")
        if bad_count >= 2 and TIER_RANK[tier] < TIER_RANK["high"]:
            tier = "high"
            factors.append(
                f"{bad_count} of last {payment_summary['evaluated_count']} payments were "
                "late, partial, or missed."
            )
        if (
            avg_invoice_usd > 0
            and balance > avg_invoice_usd * 1.5
            and TIER_RANK[tier] < TIER_RANK["high"]
        ):
            tier = "high"
            factors.append(
                f"Current balance (${balance:.0f}) exceeds 1.5× average invoice "
                f"(${avg_invoice_usd:.0f})."
            )

    # Moderate
    if tier == "low":
        if days_past_due > 0:
            tier = "moderate"
            factors.append(f"{days_past_due} days past due.")
        elif (late + partial) >= 1:
            tier = "moderate"
            factors.append(f"{late + partial} late/partial payments in lookback.")

    # Bill shock signal can escalate low → moderate but not above
    if (
        request.bill_shock_severity in {"high", "critical"}
        and TIER_RANK[tier] < TIER_RANK["moderate"]
    ):
        tier = "moderate"
        factors.append(
            f"Forecasted bill-shock severity ({request.bill_shock_severity}) elevates near-term risk."
        )

    if not factors:
        factors.append("Account is current with consistent on-time payments.")

    return tier, factors
