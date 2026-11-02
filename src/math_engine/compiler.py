"""Explicit phases and deterministic dependency planning, independent of CVP names."""
from dataclasses import dataclass
from .contracts import ModelSpec
from .expressions import FUNCTIONS, ModelError, parse, references
from .expression_types import SCALAR, Shape, infer_shape


@dataclass
class Program:
    stages: dict
    objective: object
    constraints: list


def validate_model(model):
    if model.kind == "numerical_integration":
        from .integration import compile_integration
        compile_integration(model)
        return {"valid": True, "kind": model.kind, "backend": "scipy-quad/QUADPACK"}
    if model.kind == "indexed_program":
        from .indexed import validate_indexed
        validate_indexed(model)
        return {"valid": True, "kind": model.kind, "backend": "indexed_linear_milp"}
    if model.kind == "scenario_program":
        from .scenarios import compile_scenarios
        compile_scenarios(model)
        return {"valid": True, "kind": model.kind, "backend": "finite_enumeration" if model.decisions else "finite_measure",
                "constraint_scope": "all_positive_weight_scenarios"}
    if model.kind == "statistical_fit":
        from .statistics import compile_statistics
        compile_statistics(model)
        return {"valid": True, "kind": model.kind, "backend": "likelihood/L-BFGS-B", "predictor_shape": "scalar"}
    program = compile_model(model)
    return {"valid": True, "stages": {k: [name for name, _ in v] for k, v in program.stages.items()}}


def compile_model(model: ModelSpec) -> Program:
    all_names = set(model.inputs + model.parameters + [f.target for f in model.formulas]) | set(model.decisions)
    if all_names & FUNCTIONS:
        raise ModelError("Model identifiers cannot shadow registered functions")
    stages = {}
    row_names = set(model.inputs)
    aggregate_names = set(model.parameters)
    for stage in ("row", "aggregate", "post"):
        formulas = {f.target: parse(f.expression) for f in model.formulas if f.stage == stage}
        current = set(formulas)
        available = (row_names | set(model.parameters)) if stage == "row" else aggregate_names
        if stage == "post":
            available = row_names | aggregate_names | set(model.decisions)
        graph = {}
        for target, tree in formulas.items():
            names, columns = references(tree)
            if names - available - current:
                raise ModelError(f"{target}: unknown or wrong-stage variables {sorted(names - available - current)}")
            if columns and stage == "row":
                raise ModelError(f"{target}: column aggregates belong in the aggregate stage")
            if columns - row_names:
                raise ModelError(f"{target}: unknown input/row columns {sorted(columns - row_names)}")
            graph[target] = names & current
        ordered = []
        while graph:
            ready = sorted(name for name, deps in graph.items() if not deps)
            if not ready:
                raise ModelError(f"Circular dependency: {sorted(graph)}")
            for name in ready:
                ordered.append((name, formulas[name]))
                del graph[name]
            for deps in graph.values():
                deps.difference_update(ready)
        stages[stage] = ordered
        if stage == "row":
            row_names |= current
        elif stage == "aggregate":
            aggregate_names |= current
    objective = parse(model.objective.expression) if model.objective else None
    constraints = [parse(text, constraint=True) for text in model.constraints]
    for tree in ([objective] if objective else []) + constraints:
        names, columns = references(tree)
        if names - aggregate_names - set(model.decisions) or columns - row_names:
            raise ModelError("Objective/constraint references an unknown or wrong-stage variable")
    symbols = {name: SCALAR for name in all_names - set(model.decisions)}
    decisions = {name: Shape("vector", None if d.size == "rows" else d.size)
                 if d.size == "rows" or d.size != 1 else SCALAR for name, d in model.decisions.items()}
    for stage, formulas in stages.items():
        scoped = symbols | ({name: SCALAR if model.decisions[name].size == "rows" else shape
                             for name, shape in decisions.items()} if stage == "post" else {})
        for name, tree in formulas:
            if infer_shape(tree, scoped).kind != "scalar":
                raise ModelError(f"Formula {name} must return a scalar")
    if objective is not None and infer_shape(objective, symbols | decisions).kind != "scalar":
        raise ModelError("Objective must return a scalar")
    for tree in constraints:
        left = infer_shape(tree.left, symbols | decisions)
        right = infer_shape(tree.comparators[0], symbols | decisions)
        if left.kind == right.kind == "vector" and left.length is not None and right.length is not None and left.length != right.length:
            raise ModelError("Constraint vector dimensions differ")
    return Program(stages, objective, constraints)
