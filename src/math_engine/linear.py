"""Symbolic linear matrix builder and a replaceable SciPy adapter."""
import ast
from dataclasses import dataclass, field
from typing import Protocol
import numpy as np
from scipy.optimize import linprog, milp, Bounds, LinearConstraint
from .expressions import Context, ModelError, evaluate, elementwise, finite_scalar


@dataclass
class Affine:
    constant: float = 0.0
    terms: dict[int, float] = field(default_factory=dict)

    @staticmethod
    def of(value):
        return value if isinstance(value, Affine) else Affine(finite_scalar(value))

    def __add__(self, other):
        other = self.of(other)
        terms = self.terms.copy()
        for key, value in other.terms.items():
            terms[key] = terms.get(key, 0) + value
        return Affine(self.constant + other.constant, {k: v for k, v in terms.items() if v != 0})

    __radd__ = __add__

    def __neg__(self):
        return Affine(-self.constant, {k: -v for k, v in self.terms.items()})

    def __sub__(self, other):
        return self + -self.of(other)

    def __rsub__(self, other):
        return self.of(other) + -self

    def __mul__(self, other):
        other = self.of(other)
        if self.terms and other.terms:
            raise ModelError("Nonlinear product of decision variables")
        terms = {k: v * other.constant for k, v in self.terms.items()}
        terms.update({k: v * self.constant for k, v in other.terms.items()})
        return Affine(self.constant * other.constant, {k: v for k, v in terms.items() if v != 0})

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self.of(other)
        if other.terms or other.constant == 0:
            raise ModelError("Division requires a nonzero constant denominator")
        return self * (1 / other.constant)

    def __rtruediv__(self, other):
        return self.of(other) / self

    def __pow__(self, exponent):
        if self.terms:
            if exponent == 1:
                return self
            if exponent == 0:
                return Affine(1)
            raise ModelError("Nonlinear power of a decision variable")
        return Affine(finite_scalar(self.constant ** exponent))


@dataclass
class MatrixModel:
    c: list[float]
    constant: float
    a_ub: list[list[float]]
    b_ub: list[float]
    a_eq: list[list[float]]
    b_eq: list[float]
    bounds: list[tuple]
    variables: list[str]
    groups: dict[str, list[int]]
    constraint_sources: dict[str, list[str]]
    sense: str
    integrality: list[int] = field(default_factory=list)


def build_matrix(model, program, rows, values):
    environment = values.copy()
    variables, bounds, groups, integrality = [], [], {}, []
    for name in sorted(model.decisions):
        decision = model.decisions[name]
        size = len(rows) if decision.size == "rows" else decision.size
        if len(variables) + size > 1000:
            raise ModelError("At most 1000 decision variables per execution")
        indices = list(range(len(variables), len(variables) + size))
        groups[name] = indices
        vector = decision.size == "rows" or size > 1
        variables.extend(f"{name}[{i}]" if vector else name for i in range(size))
        bounds.extend([(decision.lower, decision.upper)] * size)
        integrality.extend([int(decision.domain != "continuous")] * size)
        symbols = [Affine(0, {index: 1.0}) for index in indices]
        environment[name] = symbols if vector else symbols[0]
    extra = []

    def positive_part(raw):
        value = Affine.of(raw)
        if not value.terms:
            return Affine(max(0., value.constant))
        lower = upper = value.constant
        for index, coefficient in value.terms.items():
            lo, hi = bounds[index]
            if lo is None or hi is None:
                raise ModelError("Decision-dependent positive_part requires finite explicit variable bounds")
            lower += coefficient * (lo if coefficient >= 0 else hi)
            upper += coefficient * (hi if coefficient >= 0 else lo)
        lower, upper = finite_scalar(lower), finite_scalar(upper)
        if lower >= 0:
            return value
        if upper <= 0:
            return Affine(0)
        if len(variables) + 2 > 1000:
            raise ModelError("Positive-part auxiliaries exceed 1000 variable limit")
        index = len(variables)
        variables.extend([f"__positive_{index}", f"__switch_{index}"])
        bounds.extend([(0, upper), (0, 1)])
        integrality.extend([0, 1])
        y, z = Affine(0, {index: 1}), Affine(0, {index+1: 1})
        # Exact graph y=max(0,value), not merely an epigraph that can change
        # meaning under maximization, a negative coefficient, or an equality.
        extra.extend([(value-y, "positive_part:y>=expression"),
                      (y-upper*z, "positive_part:y<=upper*switch"),
                      (y-value-lower*z+lower, "positive_part:upper_graph")])
        return y

    context = Context(environment, rows, positive_part if model.kind == "mixed_integer_program" else None)
    objective = Affine.of(evaluate(program.objective, context))
    inequalities, equalities = [], []
    for source, tree in zip(model.constraints, program.constraints):
        left, right = evaluate(tree.left, context), evaluate(tree.comparators[0], context)
        differences = elementwise(left, right, lambda a, b: Affine.of(a) - b)
        for difference in differences if isinstance(differences, list) else [differences]:
            if isinstance(tree.ops[0], ast.Eq):
                equalities.append((difference, source))
            else:
                inequalities.append((-difference if isinstance(tree.ops[0], ast.GtE) else difference, source))
    inequalities.extend(extra)
    n = len(variables)
    if (len(inequalities) + len(equalities)) * n > 1_000_000:
        raise ModelError("Dense matrix exceeds deployment cell limit")

    def coefficients(value):
        value = Affine.of(value)
        return [finite_scalar(value.terms.get(i, 0)) for i in range(n)], finite_scalar(value.constant)

    objective, offset = coefficients(objective)
    aub, bub, aeq, beq = [], [], [], []
    sources = {"inequality": [], "equality": []}
    for pairs, matrix_rows, rhs, key in ((inequalities, aub, bub, "inequality"), (equalities, aeq, beq, "equality")):
        for difference, source in pairs:
            row, bias = coefficients(difference)
            matrix_rows.append(row)
            rhs.append(-bias)
            sources[key].append(source)
    return MatrixModel(objective, offset, aub, bub, aeq, beq, bounds, variables, groups, sources, model.objective.sense, integrality)


class SolverAdapter(Protocol):
    def solve(self, matrix: MatrixModel, config) -> dict: ...


class ScipySolver:
    def solve(self, matrix, config):
        sign = -1 if matrix.sense == "maximize" else 1
        integer = np.array(matrix.integrality or [0]*len(matrix.c), dtype=int)
        if integer.any():
            constraints = []
            if matrix.a_ub:
                constraints.append(LinearConstraint(np.asarray(matrix.a_ub), -np.inf, matrix.b_ub))
            if matrix.a_eq:
                constraints.append(LinearConstraint(np.asarray(matrix.a_eq), matrix.b_eq, matrix.b_eq))
            result = milp(np.asarray(matrix.c)*sign, integrality=integer,
                          bounds=Bounds([lo if lo is not None else -np.inf for lo, _ in matrix.bounds],
                                        [hi if hi is not None else np.inf for _, hi in matrix.bounds]),
                          constraints=constraints,
                          options={"time_limit": config.time_limit_seconds, "mip_rel_gap": config.mip_relative_gap,
                                   "node_limit": config.mip_node_limit})
        else:
            result = linprog(np.asarray(matrix.c) * sign,
                         A_ub=matrix.a_ub or None, b_ub=matrix.b_ub or None,
                         A_eq=matrix.a_eq or None, b_eq=matrix.b_eq or None,
                         bounds=matrix.bounds, method="highs",
                         options={"time_limit": config.time_limit_seconds,
                                  "primal_feasibility_tolerance": config.feasibility_tolerance,
                                  "dual_feasibility_tolerance": config.feasibility_tolerance})
        status = {0: "succeeded", 2: "infeasible", 3: "unbounded"}.get(result.status, "failed")
        diagnostics = {"solver": "scipy-highs-milp" if integer.any() else "scipy-highs", "solver_status": int(result.status), "message": result.message,
                       "variable_order": matrix.variables, "constraint_sources": matrix.constraint_sources}
        if integer.any():
            for key in ("mip_gap", "mip_node_count", "mip_dual_bound"):
                value = getattr(result, key, None)
                if value is not None and np.isfinite(value):
                    diagnostics[key] = float(value) if key != "mip_node_count" else int(value)
            if "mip_dual_bound" in diagnostics:
                diagnostics["objective_bound"] = sign*diagnostics.pop("mip_dual_bound") + matrix.constant
            diagnostics["requested_mip_relative_gap"] = config.mip_relative_gap
            diagnostics["limit_reached"] = int(result.status) == 1
        if status != "succeeded":
            return {"status": status, "diagnostics": diagnostics}
        x = result.x
        if not np.all(np.isfinite(x)):
            return {"status": "failed", "diagnostics": {**diagnostics, "message": "Non-finite solution"}}
        if integer.any():
            deviation = float(np.max(np.abs(x[integer != 0] - np.rint(x[integer != 0]))))
            diagnostics["max_integrality_violation"] = deviation
            if deviation > config.feasibility_tolerance * 10:
                return {"status": "failed", "diagnostics": {**diagnostics, "message": "Integrality validation failed"}}
            x = x.copy()
            x[integer != 0] = np.rint(x[integer != 0])
        violations = [0.0]
        if matrix.a_ub:
            violations.extend((np.asarray(matrix.a_ub) @ x - matrix.b_ub).tolist())
        if matrix.a_eq:
            violations.extend(np.abs(np.asarray(matrix.a_eq) @ x - matrix.b_eq).tolist())
        for value, (lower, upper) in zip(x, matrix.bounds):
            if lower is not None:
                violations.append(lower - value)
            if upper is not None:
                violations.append(value - upper)
        diagnostics["max_constraint_violation"] = float(max(violations))
        if max(violations) > config.feasibility_tolerance * 10:
            return {"status": "failed", "diagnostics": {**diagnostics, "message": "Residual validation failed"}}
        return {"status": status, "x": x.tolist(),
                "objective": finite_scalar(float(np.dot(matrix.c, x) + matrix.constant)), "diagnostics": diagnostics}
