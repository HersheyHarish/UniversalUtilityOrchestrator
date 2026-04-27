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

    def to_dict(self) -> dict[str, Any]:
        """Serialize back to a JSON-compatible dict for persistence."""
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "endpoint": self.endpoint,
            "input_schema": self.input_schema,
            "timeout_seconds": self.timeout_seconds,
        }


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

    # ── Plug-and-play: add / remove / persist ────────────────────────────

    def add_agent(self, agent_dict: dict[str, Any], persist: bool = False) -> None:
        """Register a new agent. Raises ValueError on duplicate name."""
        name = agent_dict.get("name", "")
        if self.get(name):
            raise ValueError(f"Agent '{name}' is already registered.")
        self.agents.append(AgentDefinition.from_dict(agent_dict))
        if persist:
            self._persist()

    def remove_agent(self, name: str, persist: bool = False) -> None:
        """Unregister an agent by name. Raises ValueError if not found."""
        original_count = len(self.agents)
        self.agents = [a for a in self.agents if a.name != name]
        if len(self.agents) == original_count:
            raise ValueError(f"Agent '{name}' not found in registry.")
        if persist:
            self._persist()

    def _persist(self) -> None:
        """Write the current agent list back to the JSON registry file."""
        if self.registry_path is None:
            raise RuntimeError("Cannot persist: no registry_path set.")

        # Preserve full structure from disk, only replace the agents list
        try:
            with self.registry_path.open("r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            existing = {}

        existing["agents"] = [self._agent_to_full_dict(a) for a in self.agents]

        with self.registry_path.open("w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=4, ensure_ascii=False)
            fh.write("\n")

    @staticmethod
    def _agent_to_full_dict(agent: AgentDefinition) -> dict[str, Any]:
        """Convert an AgentDefinition back to the full JSON dict format."""
        d: dict[str, Any] = {
            "name": agent.name,
            "description": agent.description,
            "capabilities": agent.capabilities,
            "endpoint": agent.endpoint,
            "timeout_seconds": agent.timeout_seconds,
            "input_schema": agent.input_schema,
        }
        return d

    # ── Scoring helpers ──────────────────────────────────────────────────

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
