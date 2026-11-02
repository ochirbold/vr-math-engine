"""Pure execution entry point: no DB, environment, or shared execution state."""
from time import perf_counter
from .compiler import compile_model
from .contracts import ExecutionRequest, ExecutionResult
from .expressions import Context, ModelError, evaluate, finite_scalar
from .linear import ScipySolver, build_matrix


def execute(request: ExecutionRequest, solver=None) -> ExecutionResult:
    start = perf_counter()
    model = request.model
    if model.kind == "numerical_integration":
        from .integration import integrate
        return integrate(request)
    if model.kind == "indexed_program":
        from .indexed import execute_indexed
        return execute_indexed(request, solver)
    if model.kind == "scenario_program":
        from .scenarios import execute_scenarios
        return execute_scenarios(request, backend=solver)
    if model.kind == "statistical_fit":
        from .statistics import fit
        return fit(request, backend=solver)
    if set(request.parameters) != set(model.parameters):
        raise ModelError("Parameters must exactly match model declarations")
    if any(set(row) != set(model.inputs) for row in request.dataset.rows):
        raise ModelError("Dataset columns must exactly match declared inputs")
    program = compile_model(model)
    rows = [row.copy() for row in request.dataset.rows]
    parameters = request.parameters.copy()
    outputs = [{} for _ in rows]
    aggregates, solution = {}, {}
    objective, diagnostics = None, {}

    def calculate(target, tree, values):
        try:
            return finite_scalar(evaluate(tree, Context(values, rows)))
        except ModelError as exc:
            raise ModelError(f"Formula {target}: {exc}") from exc

    for row, output in zip(rows, outputs):
        for target, tree in program.stages["row"]:
            row[target] = output[target] = calculate(target, tree, parameters | row)
    for target, tree in program.stages["aggregate"]:
        aggregates[target] = calculate(target, tree, parameters | aggregates)
    if model.kind in ("linear_program", "mixed_integer_program"):
        matrix = build_matrix(model, program, rows, parameters | aggregates)
        solved = (solver or ScipySolver()).solve(matrix, request.solver)
        diagnostics = solved["diagnostics"]
        if solved["status"] != "succeeded":
            return ExecutionResult(model_id=model.model_id, model_version=model.version,
                                   status=solved["status"], row_ids=request.dataset.row_ids, diagnostics=diagnostics)
        objective = solved["objective"]
        for name, indices in matrix.groups.items():
            values = [solved["x"][i] for i in indices]
            decision = model.decisions[name]
            solution[name] = values if decision.size == "rows" or len(values) > 1 else values[0]
    for i, (row, output) in enumerate(zip(rows, outputs)):
        mapped = {name: value[i] if model.decisions[name].size == "rows" else value for name, value in solution.items()}
        for target, tree in program.stages["post"]:
            row[target] = output[target] = calculate(target, tree, parameters | row | aggregates | mapped)
    diagnostics["elapsed_seconds"] = perf_counter() - start
    return ExecutionResult(model_id=model.model_id, model_version=model.version, status="succeeded",
                           row_ids=request.dataset.row_ids, outputs=outputs, aggregates=aggregates,
                           solution=solution, objective=objective, diagnostics=diagnostics)
