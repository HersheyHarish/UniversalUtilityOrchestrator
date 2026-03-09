from __future__ import annotations
from planner import ExecutionPlan, PlanStep


class DAGCreator:
    def build_execution_layers(self, plan: ExecutionPlan) -> list[list[PlanStep]]:
        """
        Build the execution layers for the given execution plan.
        """
        step_lookup = {step.id: step for step in plan.steps}
        if len(step_lookup) != len(plan.steps):
            raise ValueError("Duplicate step IDs are not allowed")

        # Initialize indegree counts and adjacency list for the dependency graph
        indegree: dict[str, int] = {step.id: 0 for step in plan.steps}
        graph: dict[str, list[str]] = {step.id: [] for step in plan.steps}
        
        # Build the dependency graph and calculate indegrees
        for step in plan.steps:
            for dependency in step.dependencies:
                if dependency not in step_lookup:
                    raise ValueError(f"Plan references unknown dependency: {dependency}")
                graph[dependency].append(step.id)
                indegree[step.id] += 1

        ordered_ids = [step.id for step in plan.steps]
        ready = [step_id for step_id in ordered_ids if indegree[step_id] == 0]
        layers: list[list[PlanStep]] = []
        processed_count = 0

        while ready:
            # Process all steps that are currently ready (indegree 0)
            current_layer_ids = ready
            layers.append([step_lookup[step_id] for step_id in current_layer_ids])
            processed_count += len(current_layer_ids)

            next_ready: list[str] = []
            for step_id in current_layer_ids:
                for child in graph[step_id]:
                    indegree[child] -= 1
                    if indegree[child] == 0:
                        next_ready.append(child)

            ready = sorted(next_ready, key=ordered_ids.index)

        if processed_count != len(plan.steps):
            raise ValueError("Plan has cyclic dependencies and cannot be executed")

        return layers
