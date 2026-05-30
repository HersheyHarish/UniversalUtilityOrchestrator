"""
schema_mapper.py — LLM-driven request body construction.

Takes a list of RequestSchemaField definitions and available runtime context,
calls GPT-4o to map context onto fields, validates the result, and returns
a clean dict ready to POST to the remote agent.

Rules enforced:
  - Required fields MUST be present → fail with SchemaMapError if missing
  - Optional fields included ONLY if high-confidence → omit otherwise
  - No null / empty-string values in the output
  - No hallucinated extra fields (stripped when strict=True)
  - Invalid JSON → one retry with a stricter prompt
  - All decisions captured in MappingResult for observability

Does NOT touch:
  - http_method, headers, content-type, timeout, retry, response_result_path
"""
from __future__ import annotations
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI


@dataclass
class RequestSchemaField:
    name: str
    description: str = ""
    required: bool = False
    field_type: str = "string"
    default: Any = None
    nested_fields: list["RequestSchemaField"] = field(default_factory=list)


def fields_from_config(request_schema: dict[str, Any]) -> list[RequestSchemaField]:
    """Build RequestSchemaField list from registry invocation_config.request_schema."""
    raw_fields = request_schema.get("fields") or []
    result: list[RequestSchemaField] = []
    for f in raw_fields:
        if isinstance(f, RequestSchemaField):
            result.append(f)
            continue
        nested_raw = f.get("nested_fields") or []
        result.append(
            RequestSchemaField(
                name=f["name"],
                description=f.get("description", ""),
                required=bool(f.get("required", False)),
                field_type=f.get("type") or f.get("field_type") or "string",
                default=f.get("default"),
                nested_fields=fields_from_config({"fields": nested_raw}),
            )
        )
    return result

log = logging.getLogger(__name__)

_OAI_ENDPOINT   = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
_OAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# Cached per cold-start (key fetched by planner's _get_secret helper)
_openai_client: AsyncOpenAI | None = None


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class FieldDecision:
    """Records what the mapper decided for a single field."""
    field_name:  str
    included:    bool
    value:       Any              = None
    reason:      str              = ""
    confidence:  float            = 1.0    # 0.0 – 1.0
    inferred:    bool             = False  # True = LLM had to infer, no direct context


@dataclass
class MappingResult:
    """Full output of one schema_mapper.build() call."""
    body:              dict[str, Any]
    decisions:         list[FieldDecision]  = field(default_factory=list)
    warnings:          list[str]            = field(default_factory=list)
    errors:            list[str]            = field(default_factory=list)
    llm_tokens_used:   int                  = 0
    mapping_latency_ms:int                  = 0
    retry_count:       int                  = 0
    fields_included:   list[str]            = field(default_factory=list)
    fields_skipped:    list[str]            = field(default_factory=list)


class SchemaMapError(Exception):
    """Raised when a required field cannot be populated."""
    pass


# =============================================================================
# OpenAI client
# =============================================================================

async def _get_client() -> AsyncOpenAI | Any:
    from openai_client import get_chat_client, is_foundry_endpoint

    return await get_chat_client("default")


# =============================================================================
# Prompt builder
# =============================================================================

_SYSTEM_PROMPT = """You are a precise request body constructor for an agent orchestration system.

Your job:
Given a set of field definitions and available runtime context, produce ONLY a
valid JSON object containing the values to include in the HTTP request body.

Rules (MUST follow exactly):
1. REQUIRED fields: always include them. Use available context to determine
   the value. If no data exists, INFER the most reasonable value from the task.
2. OPTIONAL fields: include ONLY when you have high-confidence relevant data.
   If uncertain or if no relevant context exists, OMIT the field entirely.
3. NEVER output null, empty string "", or empty array [] for any field.
4. NEVER add fields not listed in the schema.
5. NEVER add explanations, comments, or prose — JSON object ONLY.
6. Coerce values to the correct type (string, number, boolean, array, object).
7. For object fields: recursively apply the same rules to nested fields.

Output: a single JSON object. Nothing else."""

_STRICT_RETRY_SUFFIX = """
IMPORTANT — your previous response was not valid JSON.
Output ONLY a JSON object. No markdown, no code fences, no explanation.
Start your response with { and end with }."""


def _build_user_prompt(
    fields: list[dict],
    context: dict[str, Any],
    retry: bool = False,
) -> str:
    fields_text = json.dumps(fields, indent=2)
    context_text = json.dumps(context, indent=2, default=str)
    prompt = f"""Field definitions:
{fields_text}

Available context:
{context_text}

Construct the request body JSON object now."""
    if retry:
        prompt += _STRICT_RETRY_SUFFIX
    return prompt


def _fields_to_prompt_dicts(schema_fields: list) -> list[dict]:
    """Convert RequestSchemaField objects to plain dicts for the prompt."""
    result = []
    for f in schema_fields:
        d: dict[str, Any] = {
            "name":        f.name,
            "description": f.description,
            "required":    f.required,
            "type":        f.field_type if isinstance(f.field_type, str) else f.field_type.value,
        }
        if f.default is not None:
            d["default"] = f.default
        if f.nested_fields:
            d["nested_fields"] = _fields_to_prompt_dicts(f.nested_fields)
        result.append(d)
    return result


# =============================================================================
# Validation and post-processing
# =============================================================================

def _validate_and_clean(
    raw: dict[str, Any],
    schema_fields: list,
    strict: bool,
    json_schema: dict | None,
) -> tuple[dict[str, Any], list[FieldDecision], list[str]]:
    """
    1. Remove empty/null values.
    2. Strip non-schema fields if strict=True.
    3. Enforce required fields with defaults as last resort.
    4. Run JSON Schema validation if provided.
    Returns (clean_body, decisions, warnings).
    """
    warnings: list[str] = []
    decisions: list[FieldDecision] = []
    field_by_name = {f.name: f for f in schema_fields}
    allowed_names = set(field_by_name.keys())

    # Step 1: strip nulls, empty strings, empty collections
    def _strip_empty(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _strip_empty(v) for k, v in obj.items()
                    if v is not None and v != "" and v != [] and v != {}}
        if isinstance(obj, list):
            cleaned = [_strip_empty(item) for item in obj if item is not None]
            return [x for x in cleaned if x != "" and x != {} and x != []]
        return obj

    cleaned = _strip_empty(raw)

    # Step 2: strip extra fields if strict
    if strict:
        extra = set(cleaned.keys()) - allowed_names
        for k in extra:
            warnings.append(f"Stripped extra field '{k}' (not in schema, strict=True)")
        cleaned = {k: v for k, v in cleaned.items() if k in allowed_names}

    # Step 3: enforce required fields
    for f in schema_fields:
        if f.name in cleaned:
            decisions.append(FieldDecision(
                field_name=f.name,
                included=True,
                value=cleaned[f.name],
                confidence=1.0,
            ))
        elif f.required:
            # Try default
            if f.default is not None:
                cleaned[f.name] = f.default
                decisions.append(FieldDecision(
                    field_name=f.name,
                    included=True,
                    value=f.default,
                    reason="required field used default value",
                    confidence=0.5,
                    inferred=True,
                ))
                warnings.append(
                    f"Required field '{f.name}' missing from LLM output — "
                    f"used default value: {f.default!r}"
                )
            else:
                # Will be caught by caller as SchemaMapError
                decisions.append(FieldDecision(
                    field_name=f.name,
                    included=False,
                    reason="required field missing, no default available",
                    confidence=0.0,
                ))
        else:
            decisions.append(FieldDecision(
                field_name=f.name,
                included=False,
                reason="optional field not included (insufficient context or confidence)",
                confidence=0.0,
            ))

    # Step 4: JSON Schema validation (optional)
    if json_schema and cleaned:
        try:
            import jsonschema
            jsonschema.validate(instance=cleaned, schema=json_schema)
        except ImportError:
            warnings.append(
                "jsonschema package not installed — skipping JSON Schema validation. "
                "Add jsonschema to requirements.txt."
            )
        except Exception as exc:
            warnings.append(f"JSON Schema validation warning: {exc}")

    return cleaned, decisions, warnings


# =============================================================================
# Main entry point
# =============================================================================

async def build(
    schema_fields:    list,           # list[RequestSchemaField]
    strict:           bool,
    json_schema:      dict | None,
    task:             str,
    session_id:       str,
    customer_id:      str | None,
    prior_outputs:    dict[int, str],
    context_note:     str,
) -> MappingResult:
    """
    Build the request body for one agent invocation using the schema fields.

    Args:
        schema_fields  — list of RequestSchemaField (from InvocationConfig.request_schema)
        strict         — strip extra fields from LLM output
        json_schema    — optional JSON Schema for additional post-validation
        task           — planner-assigned task string
        session_id     — orchestrator session
        customer_id    — customer context
        prior_outputs  — dict[step_id → result_text] from earlier steps
        context_note   — optional planner note

    Returns:
        MappingResult with .body (the dict to POST) and .decisions for tracing

    Raises:
        SchemaMapError — if a required field is missing and has no default
    """
    t_start = time.monotonic()
    result  = MappingResult(body={})

    if not schema_fields:
        return result   # no schema — caller falls back to body_template or defaults

    # Build context dict
    context: dict[str, Any] = {
        "task":        task,
        "session_id":  session_id,
        "customer_id": customer_id or "",
    }
    for step_id, output in prior_outputs.items():
        context[f"step_{step_id}_output"] = output
    if context_note:
        context["planner_note"] = context_note

    prompt_fields = _fields_to_prompt_dicts(schema_fields)

    # ── LLM call (with one retry on JSON parse failure) ───────────────────────
    raw_body: dict[str, Any] = {}
    tokens_used = 0

    for attempt in range(2):
        if attempt > 0:
            result.retry_count += 1
            result.warnings.append("LLM returned invalid JSON — retrying with stricter prompt")

        try:
            client     = await _get_client()
            user_msg   = _build_user_prompt(prompt_fields, context, retry=(attempt > 0))

            response = await client.chat.completions.create(
                model=_OAI_DEPLOYMENT,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.0,   # deterministic — never hallucinate
                max_tokens=1000,
            )
            tokens_used += response.usage.total_tokens if response.usage else 0
            raw_text    = response.choices[0].message.content or "{}"
            raw_body    = json.loads(raw_text)
            break   # success

        except json.JSONDecodeError as exc:
            if attempt == 0:
                log.warning("schema_mapper: JSON parse failed (attempt 1): %s", exc)
                continue   # retry
            # Second failure — return empty body, let validation catch required fields
            result.errors.append(f"LLM returned invalid JSON after retry: {exc}")
            raw_body = {}
            break

        except Exception as exc:
            result.errors.append(f"LLM call failed: {type(exc).__name__}: {exc}")
            log.error("schema_mapper: LLM call failed: %s", exc, exc_info=True)
            raw_body = {}
            break

    result.llm_tokens_used = tokens_used

    # ── Validate, clean, enforce required ─────────────────────────────────────
    body, decisions, warnings = _validate_and_clean(
        raw_body, schema_fields, strict, json_schema
    )
    result.decisions = decisions
    result.warnings.extend(warnings)
    result.fields_included = [d.field_name for d in decisions if d.included]
    result.fields_skipped  = [d.field_name for d in decisions if not d.included]

    # ── Check all required fields present ────────────────────────────────────
    missing_required = [
        d.field_name for d in decisions
        if not d.included and any(
            f.name == d.field_name and f.required for f in schema_fields
        )
    ]
    if missing_required:
        raise SchemaMapError(
            f"Required field(s) could not be populated: {missing_required}. "
            "Check that your agent schema descriptions match the available context "
            "or provide a default value for each required field."
        )

    # Log skipped optional fields as warnings
    for d in decisions:
        if not d.included:
            log.info(
                "schema_mapper: skipped optional field '%s' — %s",
                d.field_name, d.reason
            )
            result.warnings.append(
                f"Optional field '{d.field_name}' omitted: {d.reason}"
            )

    result.body              = body
    result.mapping_latency_ms = int((time.monotonic() - t_start) * 1000)

    log.info(
        "schema_mapper: built body with %d fields (%d included, %d skipped) "
        "in %dms, %d tokens",
        len(schema_fields),
        len(result.fields_included),
        len(result.fields_skipped),
        result.mapping_latency_ms,
        result.llm_tokens_used,
    )
    return result
