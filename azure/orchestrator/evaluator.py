"""
Lightweight post-synthesis faithfulness check (optional, env-gated).
"""

from __future__ import annotations

import json
import logging
import os
import re

from json_utils import parse_json_object
from openai_client import get_chat_client, is_foundry_endpoint, model_name_for_role

log = logging.getLogger(__name__)

_EVAL_ENABLED = os.environ.get("ORCHESTRATOR_EVAL_ENABLED", "").lower() == "true"
_JSON_RE = re.compile(r"\{[\s\S]*\}")


_SYSTEM = """You evaluate whether a customer-facing answer faithfully reflects agent outputs.
Return ONLY JSON: {"pass": true|false, "score": 0.0-1.0, "issues": ["..."]}
Fail if the answer contradicts agent data or invents facts not supported by outputs."""


async def evaluate_response(
    user_message: str,
    agent_outputs: str,
    final_response: str,
) -> dict:
    if not _EVAL_ENABLED:
        return {"pass": True, "score": 1.0, "issues": []}

    client = await get_chat_client("default")
    model = model_name_for_role("default")
    prompt = (
        f"Customer question: {user_message}\n\n"
        f"Agent outputs:\n{agent_outputs}\n\n"
        f"Final answer:\n{final_response}"
    )
    try:
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_completion_tokens": 300,
        }
        if not is_foundry_endpoint():
            kwargs["response_format"] = {"type": "json_object"}
        completion = await client.chat.completions.create(**kwargs)
        raw = completion.choices[0].message.content or "{}"
        try:
            data = parse_json_object(raw)
        except json.JSONDecodeError:
            match = _JSON_RE.search(raw)
            data = json.loads(match.group(0)) if match else {"pass": True, "score": 1.0}
        return {
            "pass": bool(data.get("pass", True)),
            "score": float(data.get("score", 1.0)),
            "issues": list(data.get("issues") or []),
        }
    except Exception as exc:
        log.warning("Evaluator failed (non-fatal): %s", exc)
        return {"pass": True, "score": 1.0, "issues": []}
