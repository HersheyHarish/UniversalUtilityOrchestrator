from __future__ import annotations
import asyncio
import logging
import socket
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import auth_config_manager
import cosmos
import httpx
from models import (
    AgentCreate,
    AgentDoc,
    AgentReplace,
    AgentStatus,
    AgentUpdate,
    AuthConfig,
    CapabilityAdd,
    CapabilityIndex,
    HealthCheckResult,
    HealthCheckType,
    PingAllResponse,
    RegistryStats,
    StatusPatch,
)

log = logging.getLogger(__name__)

_PROBE_CONCURRENCY = 5


# =============================================================================
# Helpers
# =============================================================================


def _derive_health_url(endpoint_url: str) -> str:
    url = endpoint_url
    if url.endswith("/api/invoke"):
        return url[: -len("/invoke")] + "/health"
    parts = url.split("/api/")
    return parts[0] + "/api/health"


def _derive_tcp_host_port(endpoint_url: str, configured_port: int) -> tuple[str, int]:
    parsed = urlparse(endpoint_url)
    host = parsed.hostname or "localhost"
    if configured_port and configured_port > 0:
        return host, configured_port
    port = parsed.port
    if not port:
        port = 443 if endpoint_url.startswith("https://") else 80
    return host, port

# =============================================================================
# Probe implementations
# =============================================================================

async def _probe_http(agent: dict[str, Any], hc: dict[str, Any]) -> HealthCheckResult:
    health_url = hc.get("health_check_url") or _derive_health_url(agent["endpoint_url"])
    expected = hc.get("expected_http_status") or 200
    timeout = hc.get("http_timeout_seconds") or 10
    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            resp = await client.get(health_url)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        status = "healthy" if resp.status_code == expected else "unhealthy"
        return HealthCheckResult(
            agent_id=agent["id"],
            agent_name=agent["name"],
            endpoint=health_url,
            status=status,
            check_type="http",
            http_code=resp.status_code,
            response_ms=elapsed_ms,
        )
    except httpx.TimeoutException:
        return HealthCheckResult(
            agent_id=agent["id"],
            agent_name=agent["name"],
            endpoint=health_url,
            status="unreachable",
            check_type="http",
            response_ms=int((time.monotonic() - start) * 1000),
            error="Request timed out",
        )
    except Exception as exc:
        return HealthCheckResult(
            agent_id=agent["id"],
            agent_name=agent["name"],
            endpoint=health_url,
            status="unreachable",
            check_type="http",
            error=str(exc),
        )

async def _probe_tcp(agent: dict[str, Any], hc: dict[str, Any]) -> HealthCheckResult:
    host, port = _derive_tcp_host_port(
        agent["endpoint_url"],
        hc.get("tcp_port") or 0,
    )
    timeout = hc.get("tcp_timeout_seconds") or 5
    address = f"{host}:{port}"
    start = time.monotonic()

    try:
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, lambda: socket.create_connection((host, port), timeout=timeout)),
            timeout=float(timeout) + 1,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return HealthCheckResult(
            agent_id=agent["id"],
            agent_name=agent["name"],
            endpoint=address,
            status="healthy",
            check_type="tcp",
            response_ms=elapsed_ms,
        )
    except (socket.timeout, asyncio.TimeoutError, TimeoutError):
        return HealthCheckResult(
            agent_id=agent["id"],
            agent_name=agent["name"],
            endpoint=address,
            status="unreachable",
            check_type="tcp",
            response_ms=int((time.monotonic() - start) * 1000),
            error="TCP connection timed out",
        )
    except Exception as exc:
        return HealthCheckResult(
            agent_id=agent["id"],
            agent_name=agent["name"],
            endpoint=address,
            status="unreachable",
            check_type="tcp",
            error=str(exc),
        )

def _probe_none(agent: dict[str, Any]) -> HealthCheckResult:
    return HealthCheckResult(
        agent_id=agent["id"],
        agent_name=agent["name"],
        endpoint=agent["endpoint_url"],
        status="healthy",
        check_type="none",
        response_ms=0,
    )

async def _probe_one(agent: dict[str, Any]) -> HealthCheckResult:
    hc = agent.get("health_check_config") or {}
    check_type = hc.get("check_type", "http")

    if check_type == HealthCheckType.NONE.value:
        return _probe_none(agent)
    elif check_type == HealthCheckType.TCP.value:
        return await _probe_tcp(agent, hc)
    else:
        return await _probe_http(agent, hc)

async def _persist_health(agent: dict[str, Any], result: HealthCheckResult) -> None:
    agent["last_health_check_at"] = result.checked_at
    agent["last_health_status"] = result.status
    agent["last_health_ms"] = result.response_ms
    if result.status == "healthy" and agent["status"] == "degraded":
        agent["status"] = AgentStatus.ACTIVE.value
    elif result.status in ("unhealthy", "unreachable") and agent["status"] == "active":
        agent["status"] = AgentStatus.DEGRADED.value
    await cosmos.agent_upsert(agent)

# =============================================================================
# CRUD (create/patch/replace updated to carry new config fields)
# =============================================================================

async def create_agent(body: AgentCreate) -> tuple[AgentDoc, bool]:
    existing = await cosmos.agent_get_by_name(body.name)
    if existing:
        return AgentDoc(**existing), False

    resolved_auth = await auth_config_manager.process_and_store(
        agent_name=body.name,
        auth_config=body.auth_config,
        auth_secrets=body.auth_secrets,
    )
    doc = AgentDoc(
        **{k: v for k, v in body.model_dump().items() if k not in ("auth_secrets", "auth_config")},
        auth_config=resolved_auth,
    )
    saved = await cosmos.agent_upsert(doc.model_dump())
    return AgentDoc(**saved), True

async def get_agent(agent_id: str) -> AgentDoc | None:
    raw = await cosmos.agent_get(agent_id)
    return AgentDoc(**raw) if raw else None

async def list_agents(
    status: str | None,
    utility_type: str | None,
    tag: str | None,
) -> list[AgentDoc]:
    rows = await cosmos.agent_list(status, utility_type, tag)
    return [AgentDoc(**r) for r in rows]

async def search_agents(q: str) -> list[AgentDoc]:
    rows = await cosmos.agent_search(q)
    return [AgentDoc(**r) for r in rows]

async def patch_agent(agent_id: str, body: AgentUpdate) -> AgentDoc | None:
    raw = await cosmos.agent_get(agent_id)
    if not raw:
        return None

    updates = body.model_dump(exclude_none=True, exclude={"auth_secrets"})

    if body.auth_config is not None:
        resolved = await auth_config_manager.process_and_store(
            agent_name=raw.get("name", agent_id),
            auth_config=body.auth_config,
            auth_secrets=body.auth_secrets,
        )
        updates["auth_config"] = resolved.model_dump()
    elif body.auth_secrets is not None and raw.get("auth_config"):
        existing_cfg = AuthConfig(**raw["auth_config"])
        resolved = await auth_config_manager.process_and_store(
            agent_name=raw.get("name", agent_id),
            auth_config=existing_cfg,
            auth_secrets=body.auth_secrets,
        )
        updates["auth_config"] = resolved.model_dump()

    for key, val in updates.items():
        if isinstance(val, list):
            raw[key] = [v.model_dump() if hasattr(v, "model_dump") else v for v in val]
        elif isinstance(val, dict):
            raw[key] = val
        elif hasattr(val, "model_dump"):
            raw[key] = val.model_dump()
        else:
            raw[key] = val

    saved = await cosmos.agent_upsert(raw)
    return AgentDoc(**saved)

async def replace_agent(agent_id: str, body: AgentReplace) -> AgentDoc | None:
    raw = await cosmos.agent_get(agent_id)
    if not raw:
        return None

    resolved_auth = await auth_config_manager.process_and_store(
        agent_name=body.name,
        auth_config=body.auth_config,
        auth_secrets=body.auth_secrets,
    )
    updated = AgentDoc(
        **{k: v for k, v in body.model_dump().items() if k not in ("auth_secrets", "auth_config")},
        auth_config=resolved_auth,
        id=raw["id"],
        created_at=raw.get("created_at", datetime.now(timezone.utc).isoformat()),
        last_health_check_at=raw.get("last_health_check_at"),
        last_health_status=raw.get("last_health_status"),
        last_health_ms=raw.get("last_health_ms"),
    )
    saved = await cosmos.agent_upsert(updated.model_dump())
    return AgentDoc(**saved)

async def set_status(agent_id: str, body: StatusPatch) -> AgentDoc | None:
    raw = await cosmos.agent_get(agent_id)
    if not raw:
        return None
    raw["status"] = body.status.value
    if body.reason:
        raw.setdefault("metadata", {})
        raw["metadata"]["status_reason"] = body.reason
        raw["metadata"]["status_changed_at"] = datetime.now(timezone.utc).isoformat()
    saved = await cosmos.agent_upsert(raw)
    return AgentDoc(**saved)

async def delete_agent(agent_id: str) -> bool:
    return await cosmos.agent_hard_delete(agent_id)

async def add_capability(agent_id: str, body: CapabilityAdd) -> AgentDoc | None:
    raw = await cosmos.agent_get(agent_id)
    if not raw:
        return None
    caps: list[dict] = raw.get("capabilities", [])
    if any(c["name"] == body.name for c in caps):
        return AgentDoc(**raw)
    caps.append(body.model_dump())
    raw["capabilities"] = caps
    saved = await cosmos.agent_upsert(raw)
    return AgentDoc(**saved)

async def remove_capability(agent_id: str, cap_name: str) -> AgentDoc | None:
    raw = await cosmos.agent_get(agent_id)
    if not raw:
        return None
    raw["capabilities"] = [c for c in raw.get("capabilities", []) if c["name"] != cap_name]
    saved = await cosmos.agent_upsert(raw)
    return AgentDoc(**saved)

# =============================================================================
# Health probing (public)
# =============================================================================

async def ping_agent(agent_id: str) -> HealthCheckResult | None:
    raw = await cosmos.agent_get(agent_id)
    if not raw:
        return None
    result = await _probe_one(raw)
    await _persist_health(raw, result)
    return result

async def ping_all_active() -> PingAllResponse:
    agents = await cosmos.agent_list(status="active")
    if not agents:
        return PingAllResponse(checked=0, healthy=0, degraded=0, results=[])

    sem = asyncio.Semaphore(_PROBE_CONCURRENCY)

    async def bounded(a: dict) -> HealthCheckResult:
        async with sem:
            return await _probe_one(a)

    results = list(await asyncio.gather(*[bounded(a) for a in agents]))
    for agent, result in zip(agents, results):
        await _persist_health(agent, result)

    healthy = sum(1 for r in results if r.status == "healthy")
    return PingAllResponse(
        checked=len(results),
        healthy=healthy,
        degraded=len(results) - healthy,
        results=results,
    )

# =============================================================================
# Discovery & analytics
# =============================================================================

async def get_capability_index() -> list[CapabilityIndex]:
    rows = await cosmos.agent_capabilities_all()
    grouped: dict[str, dict] = {}
    for row in rows:
        n = row["cap_name"]
        if n not in grouped:
            grouped[n] = {"capability_name": n, "description": row["cap_description"], "agent_names": []}
        if row["agent_name"] not in grouped[n]["agent_names"]:
            grouped[n]["agent_names"].append(row["agent_name"])
    return [
        CapabilityIndex(
            capability_name=v["capability_name"],
            description=v["description"],
            agent_count=len(v["agent_names"]),
            agent_names=sorted(v["agent_names"]),
        )
        for v in sorted(grouped.values(), key=lambda x: x["capability_name"])
    ]

async def get_stats() -> RegistryStats:
    rows = await cosmos.agent_stats_raw()
    by_status: dict[str, int] = defaultdict(int)
    by_utype: dict[str, int] = defaultdict(int)
    by_auth_type: dict[str, int] = defaultdict(int)
    by_hc_type: dict[str, int] = defaultdict(int)
    all_tags: set[str] = set()
    total_caps = 0
    last_reg: str | None = None
    last_health: str | None = None

    for row in rows:
        by_status[row["status"]] += 1

        for u in row.get("utility_types", []):
            by_utype[u] += 1

        for t in row.get("tags", []):
            all_tags.add(t)

        total_caps += len(row.get("capabilities", []))

        auth_cfg = row.get("auth_config") or {}
        auth_type = auth_cfg.get("auth_type", "none")
        if auth_type == "none" and row.get("api_key_secret_name"):
            auth_type = "api_key (legacy)"
        by_auth_type[auth_type] += 1

        hc_cfg = row.get("health_check_config") or {}
        hc_type = hc_cfg.get("check_type", "http")
        by_hc_type[hc_type] += 1

        if row.get("created_at") and (not last_reg or row["created_at"] > last_reg):
            last_reg = row["created_at"]
        if row.get("last_health_check_at") and (not last_health or row["last_health_check_at"] > last_health):
            last_health = row["last_health_check_at"]

    return RegistryStats(
        total=len(rows),
        by_status=dict(by_status),
        by_utility_type=dict(by_utype),
        by_auth_type=dict(by_auth_type),
        by_health_check_type=dict(by_hc_type),
        total_capabilities=total_caps,
        unique_tags=sorted(all_tags),
        last_registered_at=last_reg,
        last_health_check_at=last_health,
    )

def build_dashboard_html(agents: list[dict[str, Any]], stats: RegistryStats) -> str:
    STATUS_COLORS = {
        "active": ("#d4edda", "#155724"),
        "inactive": ("#f8d7da", "#721c24"),
        "degraded": ("#fff3cd", "#856404"),
    }
    AUTH_COLORS = {
        "none": ("#e9ecef", "#495057"),
        "api_key": ("#e0e7ff", "#3730a3"),
        "bearer_token": ("#dcfce7", "#15803d"),
        "basic_auth": ("#fef3c7", "#92400e"),
        "oauth2": ("#ede9fe", "#5b21b6"),
        "custom": ("#fce7f3", "#9d174d"),
    }
    HC_COLORS = {
        "http": ("#e0f2fe", "#0369a1"),
        "tcp": ("#fef9c3", "#854d0e"),
        "none": ("#f1f5f9", "#334155"),
    }

    def badge(val: str, m: dict) -> str:
        bg, fg = m.get(val, ("#e9ecef", "#495057"))
        return (
            f'<span style="background:{bg};color:{fg};padding:2px 6px;'
            f'border-radius:10px;font-size:10px;font-weight:500">{val}</span>'
        )

    rows = ""
    for a in agents:
        caps = ", ".join(c["name"] for c in a.get("capabilities", []))
        auth_t = (a.get("auth_config") or {}).get("auth_type", "none")
        hc_t = (a.get("health_check_config") or {}).get("check_type", "http")
        inv_tpl = (a.get("invocation_config") or {}).get("body_template") or {}
        ms_str = f"{a['last_health_ms']} ms" if a.get("last_health_ms") else "—"
        rows += f"""<tr>
          <td><strong>{a["name"]}</strong><br><small style="color:#6c757d">{a["id"][:8]}…</small></td>
          <td>{badge(a["status"], STATUS_COLORS)}</td>
          <td>{badge(auth_t, AUTH_COLORS)}</td>
          <td>{badge(hc_t, HC_COLORS)}</td>
          <td style="font-size:11px">{", ".join(inv_tpl.keys()) if inv_tpl else "default"}</td>
          <td style="font-size:11px">{caps[:40] or "—"}</td>
          <td style="font-size:12px">{ms_str}</td>
          <td style="font-size:11px;color:#6c757d">{a.get("updated_at", "")[:10]}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta http-equiv="refresh" content="60">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Registry</title>
<style>
body{{font-family:-apple-system,sans-serif;margin:0;padding:24px;background:#f8f9fa;color:#212529}}
h1{{font-size:20px;font-weight:600;margin:0 0 4px}}
p{{font-size:12px;color:#6c757d;margin:0 0 16px}}
.bar{{background:#fff;border:1px solid #dee2e6;border-radius:8px;padding:10px 16px;margin-bottom:8px;font-size:12px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
th{{background:#f1f3f5;text-align:left;padding:8px 10px;font-size:10px;font-weight:600;color:#495057;border-bottom:1px solid #dee2e6}}
td{{padding:8px 10px;border-bottom:1px solid #f1f3f5;vertical-align:top}}
tr:last-child td{{border-bottom:none}}
tr:hover{{background:#f8f9fa}}
</style></head><body>
<h1>Agent Registry</h1>
<p>{len(agents)} agents · refreshes every 60 s</p>
<div class="bar"><strong>Status:</strong> {"".join(f"&nbsp;<strong>{k}</strong>:{v}" for k, v in stats.by_status.items())}
&emsp;<strong>Auth:</strong> {"".join(f"&nbsp;<strong>{k}</strong>:{v}" for k, v in stats.by_auth_type.items())}
&emsp;<strong>Health check:</strong> {"".join(f"&nbsp;<strong>{k}</strong>:{v}" for k, v in stats.by_health_check_type.items())}
</div>
<table><thead><tr>
  <th>Name</th><th>Status</th><th>Auth</th><th>HC type</th>
  <th>Body fields</th><th>Capabilities</th><th>Last ping</th><th>Updated</th>
</tr></thead><tbody>{rows}</tbody></table>
</body></html>"""
