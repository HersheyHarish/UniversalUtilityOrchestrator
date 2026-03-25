"""
Evaluator service for the orchestrator.

Evaluates whether a completed run satisfied the user's goal, using the same
LLM pattern as the planning service. Inputs: user query, plan, step results,
and final answer. Output: structured EvaluationResult (goal_met, score,
summary, issues, retry_recommended).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama


# Evaluation contract (Step 1–2): inputs are user_query, plan_dict, step_results, final_answer.
# Output is this dataclass.


@dataclass
class EvaluationResult:
    """Structured result of evaluating an orchestration run."""

    goal_met: bool
    score: float
    summary: str
    issues: list[str] = field(default_factory=list)
    retry_recommended: bool = False


class EvaluationService:
    """
    Evaluates whether a completed orchestration run satisfied the user's goal.
    Uses the same LLM and JSON-extraction pattern as PlanningService.
    """

    def __init__(self, model: ChatOllama):
        self.model = model

    def evaluate(
        self,
        user_query: str,
        plan_dict: dict[str, Any],
        step_results: dict[str, dict[str, Any]],
        final_answer: str,
    ) -> EvaluationResult:
        """
        Run evaluation and return a structured result.

        Args:
            user_query: Original sanitized user request.
            plan_dict: Serialized plan (goal + steps).
            step_results: Map of step_id -> {status, agent, objective, output|error}.
            final_answer: Synthesized answer shown to the user.

        Returns:
            EvaluationResult with goal_met, score, summary, issues, retry_recommended.
        """
        prompt = self._build_prompt(user_query, plan_dict, step_results, final_answer)
        try:
            raw = self.model.invoke(prompt).content
            return self._parse_response(raw)
        except Exception as exc:
            print(f"[Evaluator] Failed to evaluate with LLM: {exc}")
            return self._fallback_result(step_results, final_answer)

    def _build_prompt(
        self,
        user_query: str,
        plan_dict: dict[str, Any],
        step_results: dict[str, dict[str, Any]],
        final_answer: str,
    ) -> list[Any]:
        system_message = (
            "You are an evaluation service for a multi-agent orchestrator. "
            "You assess whether the run satisfied the user's goal. "
            "Return ONLY valid JSON. Do not include markdown or explanations.\n\n"
            "JSON schema:\n"
            "{\n"
            '  "goal_met": true or false,\n'
            '  "score": 0.0 to 1.0,\n'
            '  "summary": "string",\n'
            '  "issues": ["string"],\n'
            '  "retry_recommended": true or false\n'
            "}\n\n"
            "Rules:\n"
            "- goal_met: true only if the final answer addresses the user request adequately.\n"
            "- score: 0.0–1.0 overall quality (1.0 = fully satisfied).\n"
            "- summary: one or two sentences explaining your assessment.\n"
            "- issues: list of specific problems, or empty if none.\n"
            "- retry_recommended: true if a retry with a different plan might help."
        )
        user_message = (
            f"User request: {user_query}\n\n"
            f"Plan:\n{json.dumps(plan_dict, indent=2)}\n\n"
            f"Step results:\n{json.dumps(step_results, indent=2, default=str)}\n\n"
            f"Final answer:\n{final_answer}"
        )
        return [
            SystemMessage(content=system_message),
            HumanMessage(content=user_message),
        ]

    def _parse_response(self, raw_response: str) -> EvaluationResult:
        payload = self._extract_json_object(raw_response)
        goal_met = bool(payload.get("goal_met", False))
        try:
            score = float(payload.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        summary = str(payload.get("summary") or "").strip() or "No summary provided."
        raw_issues = payload.get("issues")
        if isinstance(raw_issues, list):
            issues = [str(i).strip() for i in raw_issues if str(i).strip()]
        else:
            issues = []
        retry_recommended = bool(payload.get("retry_recommended", False))
        return EvaluationResult(
            goal_met=goal_met,
            score=score,
            summary=summary,
            issues=issues,
            retry_recommended=retry_recommended,
        )

    def _fallback_result(
        self,
        step_results: dict[str, dict[str, Any]],
        final_answer: str,
    ) -> EvaluationResult:
        """Produce a safe default when LLM evaluation fails."""
        failed = [sid for sid, r in step_results.items() if r.get("status") == "failed"]
        goal_met = len(failed) == 0 and bool(final_answer.strip())
        return EvaluationResult(
            goal_met=goal_met,
            score=0.5,
            summary="Evaluation could not be completed; fallback based on step status and answer presence.",
            issues=failed if failed else [],
            retry_recommended=bool(failed),
        )

    @staticmethod
    def _extract_json_object(raw_response: str) -> dict[str, Any]:
        raw_response = raw_response.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_response, flags=re.DOTALL)
        candidate = fenced.group(1) if fenced else raw_response
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in evaluator response")
        return json.loads(candidate[start : end + 1])
