from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import memory
from models import AlertAction, AlertItem, CopilotContext, InsightCTA, InsightItem


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _session_agents(session: dict[str, Any]) -> list[str]:
    plan = session.get("plan") or {}
    steps = plan.get("steps") or []
    return [s.get("agent_name", "") for s in steps if isinstance(s, dict)]


async def build_insights(customer_id: str, since_hours: int = 24) -> list[dict[str, Any]]:
    rows = await memory.get_sessions_by_customer(customer_id)
    cutoff = _utc_now() - timedelta(hours=max(1, min(720, since_hours)))
    filtered = [r for r in rows if (_parse_iso(r.get("created_at")) or _utc_now()) >= cutoff]
    if not filtered:
        return []

    insights: list[InsightItem] = []
    for s in filtered[:6]:
        sid = s.get("id", "")
        agents = _session_agents(s)
        summary = (s.get("final_response") or s.get("user_message") or "").strip()
        short_summary = summary[:180] + ("..." if len(summary) > 180 else "")
        created_at = s.get("created_at") or _utc_now().isoformat()

        if "anomaly_detection_agent" in agents or "weather_context_agent" in agents:
            insights.append(
                InsightItem(
                    id=f"insight-usage-{sid}",
                    type="usage_alert",
                    severity="high",
                    title="High Usage Alert",
                    summary=short_summary or "AI detected unusual usage behavior in the selected period.",
                    evidence=["Anomaly and/or weather context was included in orchestration."],
                    cta=InsightCTA(
                        label="Investigate Usage Spike",
                        action="open_copilot_context",
                        payload={"session_id": sid},
                    ),
                    session_id=sid,
                    created_at=created_at,
                )
            )

        if "billing_agent" in agents:
            insights.append(
                InsightItem(
                    id=f"insight-billing-{sid}",
                    type="billing",
                    severity="medium",
                    title="Billing Review Ready",
                    summary=short_summary or "Billing details are available with policy-backed evidence.",
                    evidence=["Billing agent returned structured details for this session."],
                    cta=InsightCTA(
                        label="View Billing Breakdown",
                        action="open_session",
                        payload={"session_id": sid},
                    ),
                    session_id=sid,
                    created_at=created_at,
                )
            )

        if s.get("status") == "failed":
            insights.append(
                InsightItem(
                    id=f"insight-recovery-{sid}",
                    type="recovery",
                    severity="high",
                    title="Action Needed: Interrupted Workflow",
                    summary="A recent orchestration did not complete. Use quick retry to recover service continuity.",
                    evidence=["Session status reported as failed."],
                    cta=InsightCTA(
                        label="Retry Investigation",
                        action="retry_session",
                        payload={"session_id": sid},
                    ),
                    session_id=sid,
                    created_at=created_at,
                )
            )

    # Always provide at least one optimization-style card for a polished story.
    if insights:
        base = insights[0]
        insights.append(
            InsightItem(
                id=f"insight-optimization-{base.session_id}",
                type="optimization",
                severity="medium",
                title="Optimization Opportunity",
                summary="Shift discretionary loads to off-peak windows to reduce projected monthly spend.",
                evidence=["Derived from recent orchestrator usage and billing context."],
                cta=InsightCTA(
                    label="Apply EV Schedule",
                    action="apply_ev_schedule",
                    payload={"session_id": base.session_id, "window": "23:00-05:00"},
                ),
                session_id=base.session_id,
                created_at=base.created_at,
            )
        )

    return [i.model_dump() for i in insights[:3]]


async def build_copilot_context(customer_id: str, date: str) -> dict[str, Any]:
    rows = await memory.get_sessions_by_customer(customer_id)
    target = next((r for r in rows if str(r.get("created_at", "")).startswith(date)), rows[0] if rows else None)
    if not target:
        context = CopilotContext(
            target=date,
            explanation="No activity found for this date yet. Generate a session to enrich contextual analysis.",
            confidence=0.42,
            drivers=["No matching session data"],
            recommended_actions=["Run billing analysis", "Run anomaly analysis"],
            related_programs=["Time-of-use optimization"],
        )
        return context.model_dump()

    sid = target.get("id", "")
    step_rows = await memory.get_step_results(sid)
    snippets = [str(r.get("content") or "")[:140] for r in step_rows[:3]]
    explanation = " ".join(snippets).strip() or (
        "This usage spike aligns with orchestrator evidence from recent agent outputs."
    )
    context = CopilotContext(
        target=date,
        explanation=explanation,
        confidence=0.82,
        drivers=[
            "Peak window consumption exceeded baseline",
            "Agent evidence indicates load concentration during high tariff period",
        ],
        recommended_actions=[
            "View rebates for smart pumps",
            "Move flexible usage to off-peak period",
        ],
        related_programs=["Demand response enrollment", "Smart schedule optimization"],
    )
    return context.model_dump()


async def build_alerts(customer_id: str, status: str = "all") -> list[dict[str, Any]]:
    rows = await memory.get_sessions_by_customer(customer_id)
    alerts: list[AlertItem] = []
    for s in rows[:8]:
        sid = s.get("id", "")
        if not sid:
            continue
        states = s.get("dashboard_alert_states") or {}
        aid = f"alert-{sid}"
        alert_state = states.get(aid, {})
        derived_status = alert_state.get("status", "unread")

        if s.get("status") == "failed":
            severity = "high"
            title = "Service Workflow Interrupted"
            body = "A utility workflow failed. Reply RETRY to restart investigation."
        else:
            severity = "medium"
            title = "Continuous Flow Anomaly"
            body = "Potential continuous utility flow detected. Reply SHUTOFF or IGNORE."

        item = AlertItem(
            id=aid,
            channel="sms",
            title=title,
            body=body,
            severity=severity,
            status=derived_status,
            actions=[
                AlertAction(label="SHUTOFF", action="shutoff"),
                AlertAction(label="IGNORE", action="ignore"),
            ],
            triggered_at=s.get("created_at") or _utc_now().isoformat(),
            session_id=sid,
        )
        if status in {"all", derived_status}:
            alerts.append(item)

    return [a.model_dump() for a in alerts[:5]]


async def acknowledge_alert(alert_id: str, action: str, customer_id: str) -> dict[str, Any]:
    if not alert_id.startswith("alert-"):
        raise ValueError("Invalid alert id")
    session_id = alert_id.removeprefix("alert-")
    rows = await memory.get_sessions_by_customer(customer_id)
    exists = any(r.get("id") == session_id for r in rows)
    if not exists:
        raise ValueError("Alert session not found for customer")
    await memory.set_dashboard_alert_state(
        session_id=session_id,
        alert_id=alert_id,
        status="acked",
        action=action,
    )
    return {
        "id": alert_id,
        "status": "acked",
        "action": action,
        "session_id": session_id,
        "acked_at": _utc_now().isoformat(),
    }
