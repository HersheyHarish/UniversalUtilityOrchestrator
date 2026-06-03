"""
Build execution layers from planner steps for parallel execution.
"""

from __future__ import annotations

from collections import deque
from typing import Any


def build_execution_layers(steps: list[Any]) -> list[list[Any]]:
    """
    Group steps into layers where each layer can run in parallel.
    Steps in a layer have all dependencies satisfied by prior layers.
    """
    if not steps:
        return []

    graph = {s.step_id: [] for s in steps}
    in_degree = {s.step_id: 0 for s in steps}
    by_id = {s.step_id: s for s in steps}

    for s in steps:
        for dep in s.depends_on:
            if dep in graph:
                graph[dep].append(s.step_id)
                in_degree[s.step_id] += 1

    order_index = {s.step_id: i for i, s in enumerate(steps)}
    queue = deque(sid for sid, deg in in_degree.items() if deg == 0)
    layers: list[list[Any]] = []
    processed = 0

    while queue:
        layer_ids = sorted(queue, key=lambda sid: order_index[sid])
        queue.clear()
        layers.append([by_id[sid] for sid in layer_ids])
        processed += len(layer_ids)

        next_ready: list[int] = []
        for sid in layer_ids:
            for child in graph[sid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_ready.append(child)
        queue.extend(next_ready)

    if processed != len(steps):
        raise ValueError("Plan has cyclic dependencies and cannot be executed")

    return layers
