from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class AgentDefinition:
    name: str
    description: str
    capabilities: list[str]
    endpoint: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentDefinition":
        return cls(
            name=payload["name"],
            description=payload.get("description", ""),
            capabilities=payload.get("capabilities", []),
            endpoint=payload["endpoint"],
            input_schema=payload.get("input_schema", {}),
            timeout_seconds=int(payload.get("timeout_seconds", 30)),
        )

class AgentRegistry:
    def __init__(self, agents: list[AgentDefinition], registry_path: Path | None = None):
        self.agents = agents
        self.registry_path = registry_path

    @classmethod
    def load(cls, path: Path) -> "AgentRegistry":
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        agents = [AgentDefinition.from_dict(item) for item in raw.get("agents", [])]
        return cls(agents=agents, registry_path=path)

    def get(self, agent_name: str) -> AgentDefinition | None:
        return next((agent for agent in self.agents if agent.name == agent_name), None)

    def list_brief_with_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": agent.name,
                "description": agent.description,
                "capabilities": agent.capabilities,
                "input_schema": agent.input_schema,
            }
            for agent in self.agents
        ]

    def select_by_capabilities(self, required_capabilities: list[str]) -> AgentDefinition | None:
        """
        Select an agent from the registry based on required capabilities.
        """
        if not self.agents:
            return None
        if not required_capabilities:
            return self.agents[0]

        scored_agents: list[tuple[float, AgentDefinition]] = []
        for agent in self.agents:
            score = self._match_score(required_capabilities, agent.capabilities)
            scored_agents.append((score, agent))

        scored_agents.sort(key=lambda item: item[0], reverse=True)
        top_score, top_agent = scored_agents[0]
        return top_agent if top_score > 0 else None

    def _match_score(self, required: list[str], offered: list[str]) -> float:
        """
        Calculate a match score between required and offered capabilities.
        """
        offered_text = " ".join(offered).lower()
        offered_tokens = self._tokenize(offered_text)
        score = 0.0

        for capability in required:
            query = capability.lower().strip()
            if not query:
                continue
            if query in offered_text:
                score += 1.0
                continue

            req_tokens = self._tokenize(query)
            if not req_tokens:
                continue

            overlap = len(req_tokens.intersection(offered_tokens))
            score += overlap / len(req_tokens)

        return score

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))
