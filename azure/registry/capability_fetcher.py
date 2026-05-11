from __future__ import annotations
import base64
import json
import logging
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)

_FETCH_TIMEOUT   = 30.0
_CAPABILITY_TASK = (
    "List all your capabilities in structured JSON. "
    "Return a JSON array where each element has 'name' (snake_case identifier) "
    "and 'description' (one sentence explaining what the capability does). "
    "Example: [{\"name\": \"check_balance\", \"description\": \"Returns the current account balance.\"}]. "
    "Return ONLY the JSON array, no prose."
)

# =============================================================================
# Inline auth resolver (plain values — no Key Vault)
# =============================================================================

class _PlainAuth:
    def __init__(self):
        self.headers: dict[str, str] = {}
        self.params:  dict[str, str] = {}

    def apply_to_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if self.headers:
            kwargs["headers"] = {**kwargs.get("headers", {}), **self.headers}
        if self.params:
            kwargs["params"]  = {**kwargs.get("params", {}), **self.params}
        return kwargs


def _resolve_plain(auth_config: dict, auth_secrets: dict) -> _PlainAuth:
    result    = _PlainAuth()
    auth_type = (auth_config or {}).get("auth_type", "none")

    if auth_type == "api_key":
        value    = (auth_secrets or {}).get("api_key_value", "").strip()
        location = auth_config.get("api_key_location", "header")
        key_name = auth_config.get("api_key_name", "x-api-key") or "x-api-key"
        if value:
            if location == "query_param":
                result.params[key_name] = value
            else:
                result.headers[key_name] = value

    elif auth_type == "bearer_token":
        value = (auth_secrets or {}).get("bearer_token_value", "").strip()
        if value:
            result.headers["Authorization"] = f"Bearer {value}"

    elif auth_type == "basic_auth":
        username = (auth_config or {}).get("basic_auth_username", "")
        password = (auth_secrets or {}).get("basic_auth_password_value", "").strip()
        if password:
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            result.headers["Authorization"] = f"Basic {encoded}"

    elif auth_type == "oauth2":
        # OAuth2 requires a token endpoint call — we can't do that with plain values
        # alone without network access. Skip silently; the probe will still be sent
        # without auth and the user will see an auth error if the agent requires it.
        log.warning(
            "capability_fetcher: OAuth2 auth cannot be resolved from plain values "
            "during fetch — request will be sent unauthenticated."
        )

    elif auth_type == "custom":
        entries = (auth_config or {}).get("custom_entries", [])
        secret_vals = (auth_secrets or {}).get("custom_secret_values", [])
        for i, entry in enumerate(entries):
            key       = entry.get("key", "")
            inject_as = entry.get("inject_as", "header")
            # Prefer the plain value stored in the entry itself (non-sensitive custom fields)
            val = entry.get("value")
            if not val and i < len(secret_vals) and secret_vals[i]:
                val = secret_vals[i]
            if key and val:
                if inject_as == "query_param":
                    result.params[key] = val
                else:
                    result.headers[key] = val

    return result


# =============================================================================
# Request body builder
# =============================================================================

def _build_fetch_body(invocation_config: dict) -> dict[str, Any]:
    template = (invocation_config or {}).get("body_template") or {}

    if not template:
        # Legacy / default schema
        return {
            "task":        _CAPABILITY_TASK,
            "session_id":  "capability-fetch",
            "customer_id": None,
            "context":     {},
        }

    def _render(val: Any) -> Any:
        if isinstance(val, str):
            for token in ("{task}", "{message}", "{input}", "{query}", "{prompt}", "{content}"):
                if token in val:
                    return val.replace(token, _CAPABILITY_TASK)
            # Replace common context tokens with empty values
            val = val.replace("{session_id}",  "capability-fetch")
            val = val.replace("{customer_id}", "")
            val = val.replace("{context}",     "{}")
            val = re.sub(r"\{step_\d+\}", "", val)
            return val
        if isinstance(val, dict):
            return {k: _render(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_render(item) for item in val]
        return val

    rendered = _render(template)

    # If no task token was found in the template, inject the question at the
    # most likely location so the agent actually receives the prompt
    body_str = json.dumps(rendered)
    if _CAPABILITY_TASK not in body_str:
        rendered["_capability_fetch_prompt"] = _CAPABILITY_TASK

    return rendered


# =============================================================================
# Response parsers
# =============================================================================

def _try_json_array(text: str) -> list[dict] | None:
    text = text.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return _normalise_list(data)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try finding a JSON array anywhere in the text
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return _normalise_list(data)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _try_json_object(text: str) -> list[dict] | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)

    try:
        data = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            data = json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            return None

    if not isinstance(data, dict):
        return None

    # Check common field names in priority order
    for key in ("capabilities", "tools", "functions", "actions", "skills",
                "abilities", "methods", "endpoints"):
        if key in data and isinstance(data[key], list):
            return _normalise_list(data[key])

    # Check result / output / response field that might contain the list
    for key in ("result", "output", "response", "data"):
        if key in data:
            val = data[key]
            if isinstance(val, list):
                return _normalise_list(val)
            if isinstance(val, str):
                nested = _try_json_array(val)
                if nested:
                    return nested

    return None


def _normalise_list(items: list) -> list[dict]:
    result = []
    for item in items:
        if isinstance(item, str):
            # Plain string — use as name with empty description
            name = _to_snake(item.strip())
            if name:
                result.append({"name": name, "description": item.strip(),
                               "input_schema": {}, "output_schema": {}})
            continue

        if not isinstance(item, dict):
            continue

        # OpenAI tool format: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        if "function" in item and isinstance(item["function"], dict):
            item = item["function"]

        name = (
            item.get("name") or item.get("function_name") or
            item.get("tool_name") or item.get("id") or ""
        )
        desc = (
            item.get("description") or item.get("summary") or
            item.get("doc") or item.get("help") or ""
        )
        if not name:
            continue

        input_schema  = item.get("parameters") or item.get("input_schema")  or {}
        output_schema = item.get("returns")     or item.get("output_schema") or {}

        result.append({
            "name":          _to_snake(str(name).strip()),
            "description":   str(desc).strip(),
            "input_schema":  input_schema  if isinstance(input_schema, dict)  else {},
            "output_schema": output_schema if isinstance(output_schema, dict) else {},
        })

    return [c for c in result if c["name"]]


def _to_snake(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:60]   # cap length


def _try_extract_from_result_path(resp: dict, result_path: str) -> str | None:
    if not result_path:
        return None
    parts = result_path.split(".")
    node: Any = resp
    try:
        for part in parts:
            node = node[int(part)] if isinstance(node, list) else node[part]
        return str(node) if node else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _parse_response(resp_body: Any, result_path: str) -> list[dict]:
    # If result_path is configured, extract that field first
    if isinstance(resp_body, dict) and result_path:
        extracted = _try_extract_from_result_path(resp_body, result_path)
        if extracted:
            parsed = _try_json_array(extracted) or _try_json_object(extracted)
            if parsed:
                return parsed

    # Try the full response body as-is
    if isinstance(resp_body, list):
        normalised = _normalise_list(resp_body)
        if normalised:
            return normalised

    if isinstance(resp_body, dict):
        parsed = _try_json_object(json.dumps(resp_body))
        if parsed:
            return parsed

    # Convert to string and try text-based extraction
    text = resp_body if isinstance(resp_body, str) else json.dumps(resp_body)
    return _try_json_array(text) or _try_json_object(text) or []


# =============================================================================
# Public entry point
# =============================================================================

async def fetch_capabilities(
    endpoint_url:      str,
    auth_config:       dict,
    auth_secrets:      dict,
    invocation_config: dict,
) -> dict[str, Any]:
    if not endpoint_url:
        raise RuntimeError("endpoint_url is required.")
    if not endpoint_url.startswith(("http://", "https://")):
        raise RuntimeError("endpoint_url must start with https:// or http://.")

    warning = None

    # Resolve auth from plain values (no KV)
    auth_type = (auth_config or {}).get("auth_type", "none")
    if auth_type == "oauth2":
        warning = (
            "OAuth2 auth cannot be pre-resolved without a live token endpoint call. "
            "The capability fetch was sent without auth — you may see an auth error below."
        )
    injected = _resolve_plain(auth_config, auth_secrets)

    # Build request body
    body     = _build_fetch_body(invocation_config)
    method   = (invocation_config or {}).get("http_method", "POST").upper()
    ct       = (invocation_config or {}).get("content_type", "application/json")
    extra_hd = (invocation_config or {}).get("extra_static_headers") or {}

    base_headers = {"Content-Type": ct, **extra_hd}

    request_kwargs: dict[str, Any] = {
        "method":  method,
        "url":     endpoint_url,
        "headers": base_headers,
    }
    if "json" in ct.lower():
        request_kwargs["json"] = body
    else:
        request_kwargs["content"] = json.dumps(body).encode()

    request_kwargs = injected.apply_to_kwargs(request_kwargs)

    # Execute request
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            resp = await client.request(**request_kwargs)
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Cannot connect to {endpoint_url}. "
            f"Check that the agent is running and the URL is correct. Detail: {exc}"
        ) from exc
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Request to {endpoint_url} timed out after {int(_FETCH_TIMEOUT)} s. "
            "The agent may be starting up — try again in a few seconds."
        ) from None
    except Exception as exc:
        raise RuntimeError(f"HTTP request failed: {exc}") from exc

    # HTTP error handling
    if resp.status_code == 401:
        raise RuntimeError(
            f"HTTP 401 Unauthorized — the agent rejected the request. "
            "Check your auth configuration and secret values."
        )
    if resp.status_code == 403:
        raise RuntimeError(
            "HTTP 403 Forbidden — the agent denied access. "
            "Verify the API key or token has permission to invoke this agent."
        )
    if resp.status_code == 404:
        raise RuntimeError(
            f"HTTP 404 Not Found — no handler at {endpoint_url}. "
            "Check the endpoint URL (the invoke path, not the base domain)."
        )
    if resp.status_code == 405:
        raise RuntimeError(
            f"HTTP 405 Method Not Allowed — the agent does not accept {method} requests. "
            "Try changing the HTTP method in the Invocation tab."
        )
    if resp.status_code >= 500:
        snippet = resp.text[:300] if resp.text else "(empty body)"
        raise RuntimeError(
            f"HTTP {resp.status_code} Server Error from the remote agent. "
            f"The agent may not support capability discovery. Response: {snippet}"
        )
    if not resp.is_success:
        raise RuntimeError(
            f"HTTP {resp.status_code} from {endpoint_url}: {resp.text[:300]}"
        )

    # Parse response
    raw_text = resp.text
    try:
        resp_body = resp.json()["answer"]
    except Exception:
        resp_body = raw_text

    result_path = (invocation_config or {}).get("response_result_path", "")
    capabilities  = _parse_response(resp_body, result_path)
    strategy_used = "json_array" if capabilities else "none"

    if not capabilities:
        snippet = raw_text[:500] if raw_text else "(empty response)"
        raise RuntimeError(
            "The agent responded but its output could not be parsed as a capability list. "
            "The agent may not support capability auto-discovery, or it returned "
            "an unexpected format.\n\n"
            f"Raw response (first 500 chars):\n{snippet}"
        )

    return {
        "capabilities":    capabilities,
        "raw_response":    raw_text[:800],
        "parse_strategy":  strategy_used,
        "warning":         warning,
    }
