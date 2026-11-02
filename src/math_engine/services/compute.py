import threading
from fastapi import HTTPException
from .common import application
from ..compiler import validate_model
from ..contracts import ExecutionRequest, ModelSpec, StatisticalModelSpec, ScenarioModelSpec, IntegrationModelSpec, IndexedModelSpec, PredictionRequest
from ..expression_types import FUNCTION_CAPABILITIES
from ..isolated import execute_isolated

app = application("Math Execution")
slot = threading.BoundedSemaphore(1)


@app.post("/v1/models/validate")
def validate(model: ModelSpec | StatisticalModelSpec | ScenarioModelSpec | IndexedModelSpec | IntegrationModelSpec):
    return validate_model(model)


@app.get("/v1/capabilities")
def capabilities():
    return {"functions": FUNCTION_CAPABILITIES,
            "backends": {"numerical_integration": "scipy-quad/QUADPACK","linear_program": "linprog/HiGHS", "mixed_integer_program": "milp/HiGHS",
                         "indexed_program": "indexed_linear_milp", "statistical_fit": "likelihood/L-BFGS-B",
                         "scenario_program": ["finite_measure", "finite_enumeration"]},
            "distributions": ["poisson", "negative_binomial"], "observations": ["exact", "right_censored"],
            "milp_capabilities": {"domains": ["continuous", "integer", "binary"],
                                  "positive_part": "exact_graph_with_finite_explicit_bounds",
                                  "indexing": "finite_integer_axes_with_explicit_boundaries",
                                  "information": ["shared", "scenario_specific", "explicit_partitions"]},
            "scenario_capabilities": {"sampling_distributions": ["poisson", "negative_binomial", "normal", "uniform"],
                                      "dependence": ["supplied_joint_scenarios", "explicit_independent_sampling"],
                                      "reductions": ["expectation", "variance", "quantile"],
                                      "decisions": "finite_candidate_grid", "constraints": "all_positive_weight_scenarios"}}


@app.post("/v1/executions")
def execute(request: ExecutionRequest):
    return run(request, "execute")


@app.post("/v1/predictions")
def predict(request: PredictionRequest):
    return run(request, "predict")


def run(request, operation):
    if not slot.acquire(blocking=False):
        raise HTTPException(429, "Compute slot busy; retry later", headers={"Retry-After": "2"})
    try:
        response = execute_isolated(request.model_dump(), operation=operation)
        if "result" in response:
            return response["result"]
        raise HTTPException(422 if response.get("invalid_model") else 504 if response.get("timeout") else 500, response["error"])
    finally:
        slot.release()
