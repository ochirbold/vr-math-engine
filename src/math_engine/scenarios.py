"""Compile and execute user-defined finite scenario analysis/optimization.

No domain identifiers, hard-coded objective, audit gate, or inventory logic.
"""
import ast
from dataclasses import dataclass
import hashlib
from itertools import product
import json
import math
from time import perf_counter

import numpy as np

from .contracts import ExecutionResult, ModelSpec
from .expressions import Context, FUNCTIONS, ModelError, evaluate, finite_scalar, parse, references
from .expression_types import SCALAR, infer_shape
from .uncertainty import DISTRIBUTION_ARGUMENTS, FiniteMeasure, draw


@dataclass
class ScenarioProgram:
    formulas: list
    reductions: dict
    objective: tuple | None
    constraints: list
    sampling_arguments: dict


def scalar_expression(text, allowed):
    tree = parse(text)
    names, columns = references(tree)
    if columns or names - allowed:
        raise ModelError("Expression references unavailable variables or column functions")
    if infer_shape(tree, {n: SCALAR for n in allowed}).kind != "scalar":
        raise ModelError("Scenario expressions must return scalars")
    return tree


def compile_scenarios(model):
    from .compiler import compile_model
    random_names = list(model.sampling.variables) if model.sampling else []
    base = set(model.inputs + model.parameters + random_names + list(model.decisions))
    if (base | set(model.reductions)) & FUNCTIONS:
        raise ModelError("Model identifiers cannot shadow registered functions")
    proxy = ModelSpec(model_id=model.model_id, version=model.version,
                      inputs=model.inputs + random_names + list(model.decisions),
                      parameters=model.parameters, formulas=model.formulas)
    formulas = compile_model(proxy).stages["row"]
    available = base | {name for name, _ in formulas}

    def reduction(spec):
        # Probability is fixed over scenarios and decisions. It may depend on
        # supplied scalar parameters, e.g. cost_b/(cost_a+cost_b).
        probability = scalar_expression(spec.probability, set(model.parameters)) if spec.probability else None
        return (scalar_expression(spec.expression, available), spec.operation, probability)

    constraints = []
    for text in model.constraints:
        tree = parse(text, constraint=True)
        names, columns = references(tree)
        if columns or names - available:
            raise ModelError("Constraint references unavailable variables")
        for side in (tree.left, tree.comparators[0]):
            if infer_shape(side, {n: SCALAR for n in available}).kind != "scalar":
                raise ModelError("Scenario constraints must compare scalars")
        constraints.append(tree)
    sampling_arguments = {}
    if model.sampling:
        for name, spec in model.sampling.variables.items():
            if set(spec.arguments) != DISTRIBUTION_ARGUMENTS[spec.distribution]:
                raise ModelError(f"{name}: expected distribution arguments {sorted(DISTRIBUTION_ARGUMENTS[spec.distribution])}")
            sampling_arguments[name] = {key: scalar_expression(text, set(model.inputs + model.parameters))
                                       for key, text in spec.arguments.items()}
    return ScenarioProgram(formulas, {n: reduction(s) for n, s in model.reductions.items()},
                           reduction(model.objective) if model.objective else None, constraints, sampling_arguments)


class ScenarioTimeout(Exception):
    pass


class FiniteEnumerationSolver:
    """Global optimum on the supplied Cartesian candidate grid and finite measure."""
    def solve(self, score, decisions, sense):
        names = sorted(decisions)
        best, best_value, evaluated = None, None, 0
        for values in product(*(sorted(decisions[n].values) for n in names)):
            choice = dict(zip(names, values))
            value = score(choice)
            evaluated += 1
            if value is None:
                continue
            if best is None or (value < best_value if sense == "minimize" else value > best_value):
                best, best_value = choice, value
        return best, best_value, evaluated


def execute_scenarios(request, backend=None):
    start = perf_counter()
    model = request.model
    program = compile_scenarios(model)
    if set(request.parameters) != set(model.parameters):
        raise ModelError("Parameters must exactly match declarations")
    if any(set(r) != set(model.inputs) for r in request.dataset.rows):
        raise ModelError("Dataset columns must exactly match declared inputs")
    parameters = request.parameters.copy()
    count = model.sampling.count if model.sampling else len(request.dataset.rows)
    combinations = math.prod(len(d.values) for d in model.decisions.values())
    work = count * (combinations + 1) * max(1, len(model.formulas) + len(model.constraints) + len(model.reductions) + 1)
    if work > 2_000_000:
        raise ModelError("Scenario work exceeds 2000000 evaluations; reduce scenarios, candidates or expressions")

    def deadline():
        if perf_counter() - start > request.solver.time_limit_seconds:
            raise ScenarioTimeout()

    if model.sampling:
        if len(request.dataset.rows) != 1:
            raise ModelError("Independent sampling requires exactly one deterministic context row")
        context = parameters | request.dataset.rows[0]
        # Named streams ensure adding/reordering a different variable does not
        # change existing draws. Reproducibility also pins NumPy version below.
        draws = {}
        for name in sorted(model.sampling.variables):
            spec = model.sampling.variables[name]
            name_seed = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "little")
            rng = np.random.default_rng(np.random.SeedSequence([model.sampling.seed, name_seed]))
            args = {k: finite_scalar(evaluate(t, Context(context, []))) for k, t in program.sampling_arguments[name].items()}
            draws[name] = draw(spec.distribution, args, count, rng)
        rows = [request.dataset.rows[0] | {n: float(v[i]) for n, v in draws.items()} for i in range(count)]
        measure = FiniteMeasure(np.ones(count))
    else:
        rows = [r.copy() for r in request.dataset.rows]
        measure = FiniteMeasure([r[model.weight_column] for r in rows] if model.weight_column else np.ones(count))
    # Zero-mass scenarios are outside the support: neither domain failures nor
    # constraints there should change a probability calculation.
    active = [(row, float(w)) for row, w in zip(rows, measure.weights) if w > 0]
    rows = [r for r, _ in active]
    measure = FiniteMeasure([w for _, w in active])
    checksum_body = {"rows": rows, "weights": measure.weights.tolist()}
    checksum = hashlib.sha256(json.dumps(checksum_body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    diagnostics = {"scenario_count": count, "positive_weight_scenarios": len(rows), "scenario_checksum": checksum,
                   "source": "independent_sampling" if model.sampling else "supplied_joint_scenarios",
                   "numpy_version": np.__version__, "seed": model.sampling.seed if model.sampling else None,
                   "monte_carlo_estimate": model.sampling is not None,
                   "population_optimum_guaranteed": False,
                   "constraint_scope": "all_positive_weight_scenarios",
                   "backend": "finite_enumeration" if model.decisions else "finite_measure",
                   "optimum_scope": "declared_candidates_and_finite_measure" if model.decisions else None}

    def value(tree, context):
        return finite_scalar(evaluate(tree, Context(context, [])))

    def materialize(choice):
        contexts = []
        for i, row in enumerate(rows):
            if i % 32 == 0:
                deadline()
            context = parameters | row | choice
            for name, tree in program.formulas:
                context[name] = value(tree, context)
            for tree in program.constraints:
                left, right = value(tree.left, context), value(tree.comparators[0], context)
                tolerance = request.solver.feasibility_tolerance
                valid = (left <= right + tolerance if isinstance(tree.ops[0], ast.LtE) else
                         left >= right - tolerance if isinstance(tree.ops[0], ast.GtE) else abs(left - right) <= tolerance)
                if not valid:
                    return None
            contexts.append(context)
        return contexts

    def reduce(spec, contexts):
        tree, operation, probability = spec
        q = value(probability, parameters) if probability else None
        return measure.reduce([value(tree, c) for c in contexts], operation, q)

    def score(choice):
        contexts = materialize(choice)
        return None if contexts is None else reduce(program.objective, contexts)

    def result(status, **kwargs):
        diagnostics["elapsed_seconds"] = perf_counter() - start
        # Aggregate-only outputs preserve source snapshot identity, even when
        # Monte Carlo generates a different number of internal scenario rows.
        return ExecutionResult(model_id=model.model_id, model_version=model.version, status=status,
                               row_ids=request.dataset.row_ids, diagnostics=diagnostics, **kwargs)

    try:
        deadline()
        choice, objective = {}, None
        if model.decisions:
            choice, objective, evaluated = (backend or FiniteEnumerationSolver()).solve(score, model.decisions, model.objective.sense)
            diagnostics["candidates_evaluated"] = evaluated
            if choice is None:
                return result("infeasible")
        contexts = materialize(choice)
        aggregates = {n: reduce(spec, contexts) for n, spec in program.reductions.items()}
        deadline()
        return result("succeeded", aggregates=aggregates, solution=choice, objective=objective,
                      outputs=[{} for _ in request.dataset.rows])
    except ScenarioTimeout:
        diagnostics["reason"] = "scenario_time_limit"
        return result("failed")
