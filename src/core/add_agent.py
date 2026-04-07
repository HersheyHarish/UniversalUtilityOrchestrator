"""CLI utility for plug-and-play agent registration.

Adds a new agent to agents.json (or removes one) without touching any
orchestrator code.

Usage examples
--------------
# Interactive prompt
python add_agent.py

# Single-line add
python add_agent.py add \
    --name document_parser_agent \
    --description "Extracts structured data from PDF and image documents." \
    --capabilities "Parse PDF invoices" "Extract tables from images" \
    --endpoint http://localhost:8003/document_parser_agent \
    --tags documents parsing ocr \
    --health-check http://localhost:8003/health \
    --version 1.0.0

# Remove an agent
python add_agent.py remove --name document_parser_agent

# List registered agents
python add_agent.py list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path resolution – works whether the script is run from the repo root or
# from src/core/ directly.
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_REGISTRY = _THIS_DIR / "agents.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="add_agent",
        description="Plug-and-play agent registration for the Universal Utility Orchestrator.",
    )
    parser.add_argument(
        "--registry",
        default=str(_DEFAULT_REGISTRY),
        help="Path to agents.json (default: %(default)s)",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # ---- add ----
    add_parser = subparsers.add_parser("add", help="Register a new agent.")
    add_parser.add_argument("--name", required=True, help="Unique snake_case agent name.")
    add_parser.add_argument("--description", required=True, help="What this agent does.")
    add_parser.add_argument(
        "--capabilities",
        nargs="+",
        required=True,
        metavar="CAPABILITY",
        help="One or more natural-language capability statements.",
    )
    add_parser.add_argument("--endpoint", required=True, help="HTTP(S) POST endpoint URL.")
    add_parser.add_argument("--version", default="1.0.0", help="Semantic version (default: 1.0.0).")
    add_parser.add_argument(
        "--status",
        default="active",
        choices=["active", "inactive", "maintenance"],
        help="Lifecycle status (default: active).",
    )
    add_parser.add_argument(
        "--tags",
        nargs="*",
        default=[],
        metavar="TAG",
        help="Space-separated tags for grouping/discovery.",
    )
    add_parser.add_argument("--health-check", dest="health_check", help="HTTP GET health-check URL.")
    add_parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        dest="timeout_seconds",
        help="Per-agent request timeout in seconds (default: 30).",
    )
    add_parser.add_argument(
        "--input-schema",
        dest="input_schema",
        default="{}",
        metavar="JSON",
        help="JSON string describing the agent's expected input payload.",
    )
    add_parser.add_argument(
        "--output-schema",
        dest="output_schema",
        default="{}",
        metavar="JSON",
        help="JSON string describing the agent's response payload.",
    )
    add_parser.add_argument(
        "--author",
        default="",
        help="Author / team name for metadata.",
    )

    # ---- remove ----
    remove_parser = subparsers.add_parser("remove", help="Unregister an agent by name.")
    remove_parser.add_argument("--name", required=True, help="Agent name to remove.")

    # ---- list ----
    subparsers.add_parser("list", help="Print all registered agents.")

    return parser


def _interactive_add(registry_path: Path) -> None:
    """Prompt the user interactively for all required (and optional) fields."""
    print("\n=== UUO Agent Registration Wizard ===\n")

    name = _prompt("Agent name (snake_case, e.g. my_new_agent): ").strip()
    description = _prompt("Short description: ").strip()
    caps_raw = _prompt("Capabilities (comma-separated): ").strip()
    capabilities = [c.strip() for c in caps_raw.split(",") if c.strip()]
    endpoint = _prompt("Endpoint URL (e.g. http://localhost:8004/my_new_agent): ").strip()

    print("\n--- Optional fields (press Enter to skip) ---")
    version = _prompt("Version [1.0.0]: ").strip() or "1.0.0"
    status = _prompt("Status (active/inactive/maintenance) [active]: ").strip() or "active"
    tags_raw = _prompt("Tags (space-separated) []: ").strip()
    tags = tags_raw.split() if tags_raw else []
    health_check = _prompt("Health-check URL [none]: ").strip() or None
    timeout_raw = _prompt("Timeout seconds [30]: ").strip()
    timeout_seconds = int(timeout_raw) if timeout_raw.isdigit() else 30
    author = _prompt("Author []: ").strip()

    agent_dict = {
        "name": name,
        "version": version,
        "status": status,
        "description": description,
        "capabilities": capabilities,
        "tags": tags,
        "endpoint": endpoint,
        "timeout_seconds": timeout_seconds,
        "input_schema": {},
        "output_schema": {},
        "metadata": {"author": author} if author else {},
    }
    if health_check:
        agent_dict["health_check"] = health_check

    _do_add(registry_path, agent_dict)


def _do_add(registry_path: Path, agent_dict: dict) -> None:
    sys.path.insert(0, str(_THIS_DIR))
    from orchestrator import AgentRegistry  # noqa: PLC0415 – local import by design

    registry = AgentRegistry.load(registry_path) if registry_path.exists() else AgentRegistry([], registry_path)
    registry.registry_path = registry_path
    registry.add_agent(agent_dict, persist=True)
    print(f"\nAgent '{agent_dict['name']}' successfully added to {registry_path}.\n")


def _do_remove(registry_path: Path, name: str) -> None:
    sys.path.insert(0, str(_THIS_DIR))
    from orchestrator import AgentRegistry  # noqa: PLC0415

    if not registry_path.exists():
        print(f"[Error] Registry not found: {registry_path}", file=sys.stderr)
        sys.exit(1)

    registry = AgentRegistry.load(registry_path)
    registry.remove_agent(name, persist=True)
    print(f"\nAgent '{name}' removed from {registry_path}.\n")


def _do_list(registry_path: Path) -> None:
    if not registry_path.exists():
        print(f"[Error] Registry not found: {registry_path}", file=sys.stderr)
        sys.exit(1)

    with registry_path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    agents = raw.get("agents", [])
    if not agents:
        print("No agents registered.")
        return

    print(f"\n{'NAME':<35} {'VERSION':<10} {'STATUS':<14} ENDPOINT")
    print("-" * 90)
    for a in agents:
        print(
            f"{a.get('name', ''):<35} "
            f"{a.get('version', '?'):<10} "
            f"{a.get('status', '?'):<14} "
            f"{a.get('endpoint', '')}"
        )
    print()


def _prompt(message: str) -> str:
    try:
        return input(message)
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    registry_path = Path(args.registry)

    if args.command == "add":
        try:
            input_schema = json.loads(args.input_schema)
            output_schema = json.loads(args.output_schema)
        except json.JSONDecodeError as exc:
            print(f"[Error] Invalid JSON for schema argument: {exc}", file=sys.stderr)
            sys.exit(1)

        agent_dict = {
            "name": args.name,
            "version": args.version,
            "status": args.status,
            "description": args.description,
            "capabilities": args.capabilities,
            "tags": args.tags,
            "endpoint": args.endpoint,
            "timeout_seconds": args.timeout_seconds,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "metadata": {"author": args.author} if args.author else {},
        }
        if args.health_check:
            agent_dict["health_check"] = args.health_check

        try:
            _do_add(registry_path, agent_dict)
        except ValueError as exc:
            print(f"[Error] {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "remove":
        try:
            _do_remove(registry_path, args.name)
        except ValueError as exc:
            print(f"[Error] {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list":
        _do_list(registry_path)

    else:
        # No sub-command → interactive wizard
        try:
            _interactive_add(registry_path)
        except ValueError as exc:
            print(f"[Error] {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
