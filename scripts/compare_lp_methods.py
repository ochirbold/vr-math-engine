"""Compare the engine's HiGHS adapter with SciPy's legacy revised simplex.

This diagnostic uses the same compiled matrix for both methods. It does not
change the API's default backend or require an older SciPy environment.
"""
import argparse
import json
from pathlib import Path
import sys
import warnings

import numpy as np
import scipy
from scipy.optimize import linprog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from math_engine.contracts import ExecutionRequest
from math_engine.engine import execute
from math_engine.linear import ScipySolver


class CaptureMatrix(ScipySolver):
    def solve(self, matrix, config):
        self.matrix = matrix
        return super().solve(matrix, config)


def compare(request):
    if request.model.kind != "linear_program":
        raise ValueError("Comparison requires a linear_program model")
    adapter = CaptureMatrix()
    highs = execute(request, solver=adapter)
    matrix = adapter.matrix
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        revised = linprog(np.asarray(matrix.c) * (-1 if matrix.sense == "maximize" else 1),
                          A_ub=matrix.a_ub or None, b_ub=matrix.b_ub or None,
                          A_eq=matrix.a_eq or None, b_eq=matrix.b_eq or None,
                          bounds=matrix.bounds, method="revised simplex",
                          options={"tol": 1e-10, "maxiter": 10000})
    result = {"status": int(revised.status), "success": bool(revised.success),
              "message": str(revised.message), "iterations": int(revised.nit),
              "warnings": [str(w.message) for w in captured]}
    if revised.success:
        x = np.asarray(revised.x)
        violations = [0.]
        if matrix.a_ub:
            violations.extend((np.asarray(matrix.a_ub) @ x - matrix.b_ub).tolist())
        if matrix.a_eq:
            violations.extend(abs(np.asarray(matrix.a_eq) @ x - matrix.b_eq).tolist())
        for value, (lower, upper) in zip(x, matrix.bounds):
            if lower is not None:
                violations.append(lower - value)
            if upper is not None:
                violations.append(value - upper)
        if not np.isfinite(x).all() or max(violations) > request.solver.feasibility_tolerance * 10:
            raise ValueError("Revised simplex result failed independent feasibility validation")
        result.update(objective=float(np.dot(matrix.c, x) + matrix.constant),
                      variables=dict(zip(matrix.variables, x.tolist())),
                      max_constraint_violation=float(max(violations)))
    return {"scipy_version": scipy.__version__, "request": request.model_dump(),
            "matrix": {"variable_order": matrix.variables, "objective": matrix.c,
                       "A_ub": matrix.a_ub, "b_ub": matrix.b_ub, "A_eq": matrix.a_eq, "b_eq": matrix.b_eq,
                       "bounds": matrix.bounds}, "highs": highs.model_dump(), "revised_simplex": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    request = ExecutionRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
    report = compare(request)
    body = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            file.write(body)
    print(body)
    return 0 if report["highs"]["status"] == "succeeded" and report["revised_simplex"]["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
