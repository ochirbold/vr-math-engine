"""Version 1 wire contracts. No database or application-domain dependencies."""
from __future__ import annotations
from typing import Literal
import math
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator
from . import __version__


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def check_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
        raise ValueError(f"Invalid identifier: {name!r}")


class Dataset(Contract):
    row_ids: list[str] = Field(min_length=1, max_length=10000)
    rows: list[dict[str, float]] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def consistent(self):
        if len(self.row_ids) != len(self.rows) or len(set(self.row_ids)) != len(self.row_ids):
            raise ValueError("row_ids must be unique and match rows")
        columns = set(self.rows[0])
        if len(columns) > 200:
            raise ValueError("At most 200 input columns")
        for name in columns:
            check_name(name)
        for row in self.rows:
            if set(row) != columns or any(not math.isfinite(v) for v in row.values()):
                raise ValueError("Rows must have the same columns and finite numeric values")
        return self


class Formula(Contract):
    target: str
    expression: str = Field(min_length=1, max_length=2000)
    stage: Literal["row", "aggregate", "post"] = "row"


class Decision(Contract):
    size: int | Literal["rows"] = 1
    lower: float | None = 0
    upper: float | None = None
    domain: Literal["continuous", "integer", "binary"] = "continuous"

    @model_validator(mode="after")
    def bounds_valid(self):
        if self.domain == "binary":
            self.lower = max(0, self.lower) if self.lower is not None else 0
            self.upper = min(1, self.upper) if self.upper is not None else 1
        if isinstance(self.size, int) and not 1 <= self.size <= 1000:
            raise ValueError("Decision size must be 1..1000 or 'rows'")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("lower exceeds upper")
        return self


class Objective(Contract):
    sense: Literal["minimize", "maximize"]
    expression: str = Field(min_length=1, max_length=2000)


class ModelSpec(Contract):
    schema_version: Literal["1"] = "1"
    model_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    kind: Literal["calculation", "linear_program", "mixed_integer_program"] = "calculation"
    inputs: list[str] = Field(default_factory=list, max_length=200)
    parameters: list[str] = Field(default_factory=list, max_length=100)
    formulas: list[Formula] = Field(default_factory=list, max_length=200)
    decisions: dict[str, Decision] = Field(default_factory=dict, max_length=100)
    objective: Objective | None = None
    constraints: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_model(self):
        names = self.inputs + self.parameters + [f.target for f in self.formulas] + list(self.decisions)
        for name in names:
            check_name(name)
        if len(set(names)) != len(names):
            raise ValueError("Inputs, parameters, formula targets and decisions must have distinct names")
        if any(not 1 <= len(c) <= 2000 for c in self.constraints):
            raise ValueError("Constraint length must be 1..2000")
        if self.kind in ("linear_program", "mixed_integer_program") and (not self.decisions or self.objective is None):
            raise ValueError("LP requires decisions and an objective")
        if self.kind == "linear_program" and any(d.domain != "continuous" for d in self.decisions.values()):
            raise ValueError("Integer/binary decisions require mixed_integer_program")
        if self.kind == "calculation" and (self.decisions or self.objective or self.constraints):
            raise ValueError("Calculation models cannot contain LP declarations")
        return self


class SolverConfig(Contract):
    time_limit_seconds: float = Field(default=20, gt=0, le=60)
    feasibility_tolerance: float = Field(default=1e-7, ge=1e-9, le=1e-4)
    mip_relative_gap: float = Field(default=0, ge=0, le=0.1)
    mip_node_limit: int = Field(default=100000, ge=1, le=1000000)


class ExecutionRequest(Contract):
    model: ModelSpec | StatisticalModelSpec | ScenarioModelSpec | IndexedModelSpec | IntegrationModelSpec
    dataset: Dataset
    parameters: dict[str, float] = Field(default_factory=dict)
    solver: SolverConfig = Field(default_factory=SolverConfig)


class ExecutionResult(Contract):
    schema_version: Literal["1"] = "1"
    engine_version: str = __version__
    model_id: str
    model_version: str
    status: Literal["succeeded", "infeasible", "unbounded", "failed"]
    row_ids: list[str]
    outputs: list[dict[str, float]] = Field(default_factory=list)
    aggregates: dict[str, float] = Field(default_factory=dict)
    solution: dict[str, float | list[float]] = Field(default_factory=dict)
    objective: float | None = None
    diagnostics: dict = Field(default_factory=dict)
    fitted_artifact: "FittedArtifact | None" = None


class JobRequest(Contract):
    model_id: str
    model_version: str
    snapshot_id: str
    parameters: dict[str, float] = Field(default_factory=dict)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    persist: bool = False
    idempotency_key: str = Field(min_length=1, max_length=200)


class WritebackRequest(Contract):
    job_id: str
    snapshot_id: str
    row_ids: list[str]
    outputs: list[dict[str, float]]


class Trainable(Contract):
    initial: float
    lower: float | None = None
    upper: float | None = None
    transform: Literal["identity", "log"] = "identity"

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.lower is not None and self.initial < self.lower or self.upper is not None and self.initial > self.upper:
            raise ValueError("Initial parameter must be inside its bounds")
        if self.lower is not None and self.upper is not None and self.lower >= self.upper:
            raise ValueError("Trainable bounds must have positive width")
        if self.transform == "log" and (self.initial <= 0 or self.lower is not None and self.lower <= 0 or self.upper is not None and self.upper <= 0):
            raise ValueError("Log-transformed parameter and its bounds must be positive")
        return self


class ObservationSpec(Contract):
    response: str
    kind: Literal["exact", "right_censored"] = "exact"
    censored: str | None = None
    threshold: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.kind == "right_censored" and (not self.censored or not self.threshold):
            raise ValueError("Right censoring requires explicit indicator and threshold columns")
        if self.kind == "exact" and (self.censored or self.threshold):
            raise ValueError("Exact observations cannot declare censoring columns")
        names = [n for n in (self.response, self.censored, self.threshold) if n]
        for name in names:
            check_name(name)
        if len(set(names)) != len(names):
            raise ValueError("Observation columns must be distinct")
        return self


class StatisticalModelSpec(Contract):
    schema_version: Literal["1"] = "1"
    model_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    kind: Literal["statistical_fit"] = "statistical_fit"
    inputs: list[str] = Field(default_factory=list, max_length=200)
    parameters: list[str] = Field(default_factory=list, max_length=100)
    trainable: dict[str, Trainable] = Field(min_length=1, max_length=32)
    predictor: str = Field(min_length=1, max_length=2000)
    link: Literal["log", "identity"] = "log"
    distribution: Literal["poisson", "negative_binomial"] = "poisson"
    dispersion_parameter: str | None = None
    observation: ObservationSpec
    standardize: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=500, ge=1, le=2000)

    @model_validator(mode="after")
    def valid(self):
        names = self.inputs + self.parameters + list(self.trainable)
        observation_names = [n for n in (self.observation.response, self.observation.censored, self.observation.threshold) if n]
        for name in names:
            check_name(name)
        if len(set(names)) != len(names) or set(names) & set(observation_names):
            raise ValueError("Features, fixed/trainable parameters and observations must have distinct names")
        if len(set(self.standardize)) != len(self.standardize) or set(self.standardize) - set(self.inputs):
            raise ValueError("Standardization must name distinct input features")
        if self.distribution == "negative_binomial":
            if self.dispersion_parameter not in set(self.trainable) | set(self.parameters):
                raise ValueError("Negative Binomial requires a declared dispersion parameter")
            if self.dispersion_parameter in self.trainable:
                spec = self.trainable[self.dispersion_parameter]
                if spec.transform != "log" and (spec.lower is None or spec.lower <= 0):
                    raise ValueError("Dispersion needs a log transform or a positive lower bound")
        elif self.dispersion_parameter is not None:
            raise ValueError("Poisson has no dispersion parameter")
        return self


class FeatureTransform(Contract):
    center: float = 0
    scale: float = Field(default=1, gt=0)


class FittedArtifact(Contract):
    schema_version: Literal["1"] = "1"
    model: StatisticalModelSpec
    fitted_parameters: dict[str, float]
    fixed_parameters: dict[str, float]
    preprocessing: dict[str, FeatureTransform]
    training_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_rows: int = Field(ge=1)
    engine_version: str = __version__
    backend: str
    negative_log_likelihood: float


class PredictionRequest(Contract):
    artifact: FittedArtifact
    dataset: Dataset


class RandomVariable(Contract):
    distribution: Literal["poisson", "negative_binomial", "normal", "uniform"]
    arguments: dict[str, str] = Field(max_length=2)


class IndependentSampling(Contract):
    dependence: Literal["independent"]
    seed: int = Field(ge=0, le=2**32-1, strict=True)
    count: int = Field(default=1000, ge=1, le=10000, strict=True)
    variables: dict[str, RandomVariable] = Field(min_length=1, max_length=100)


class ScenarioReduction(Contract):
    expression: str = Field(min_length=1, max_length=2000)
    operation: Literal["expectation", "variance", "quantile"] = "expectation"
    probability: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def quantile_probability(self):
        if (self.operation == "quantile") != (self.probability is not None):
            raise ValueError("Only quantile requires a probability expression")
        return self


class ScenarioObjective(ScenarioReduction):
    sense: Literal["minimize", "maximize"] = "minimize"


class CandidateDecision(Contract):
    values: list[float] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.values)) != len(self.values):
            raise ValueError("Decision candidates must be distinct")
        return self


class ScenarioModelSpec(Contract):
    schema_version: Literal["1"] = "1"
    model_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    kind: Literal["scenario_program"] = "scenario_program"
    inputs: list[str] = Field(default_factory=list, max_length=200)
    parameters: list[str] = Field(default_factory=list, max_length=100)
    # Without sampling, each dataset row is one JOINT scenario, preserving dependence.
    # With sampling, exactly one dataset row supplies deterministic context.
    sampling: IndependentSampling | None = None
    weight_column: str | None = None
    formulas: list[Formula] = Field(default_factory=list, max_length=100)
    decisions: dict[str, CandidateDecision] = Field(default_factory=dict, max_length=8)
    objective: ScenarioObjective | None = None
    constraints: list[str] = Field(default_factory=list, max_length=50)
    reductions: dict[str, ScenarioReduction] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def valid(self):
        names = self.inputs + self.parameters + list(self.decisions) + [f.target for f in self.formulas]
        if self.sampling:
            names += list(self.sampling.variables)
        for name in names + list(self.reductions):
            check_name(name)
        if len(names) != len(set(names)):
            raise ValueError("Input, parameter, random variable, formula and decision names must be distinct")
        if self.weight_column and (self.sampling or self.weight_column not in self.inputs):
            raise ValueError("weight_column must be a supplied scenario input; unavailable with sampling")
        if any(f.stage != "row" for f in self.formulas):
            raise ValueError("Scenario formulas use row stage only; use reductions for aggregates")
        if bool(self.decisions) != (self.objective is not None):
            raise ValueError("Optimization requires both candidate decisions and an objective")
        if not self.objective and not self.reductions:
            raise ValueError("Declare reductions or an optimization objective")
        if self.constraints and not self.decisions:
            raise ValueError("Constraints require decisions")
        if any(not 1 <= len(c) <= 2000 for c in self.constraints):
            raise ValueError("Constraint length must be 1..2000")
        if math.prod(len(d.values) for d in self.decisions.values()) > 10000:
            raise ValueError("At most 10000 joint decision candidates")
        return self


class IndexedTable(Contract):
    axes: list[str] = Field(default_factory=list, max_length=4)
    column: str


class BoundaryValue(Contract):
    index: list[int] = Field(max_length=4)
    expression: str = Field(min_length=1, max_length=2000)


class InformationPartition(Contract):
    at: dict[str, int]
    groups: list[list[int]] = Field(min_length=1, max_length=100)


class IndexedDecision(Contract):
    axes: list[str] = Field(default_factory=list, max_length=4)
    domain: Literal["continuous", "integer", "binary"] = "continuous"
    lower: float | None = 0
    upper: float | None = None
    boundary: list[BoundaryValue] = Field(default_factory=list, max_length=1000)
    information: Literal["scenario_specific"] | list[InformationPartition] | None = None


class IndexedExpression(Contract):
    over: list[str] = Field(default_factory=list, max_length=4)
    expression: str = Field(min_length=1, max_length=2000)


class IndexedObjective(Contract):
    sense: Literal["minimize", "maximize"] = "minimize"
    terms: list[IndexedExpression] = Field(min_length=1, max_length=100)


class IndexedModelSpec(Contract):
    schema_version: Literal["1"] = "1"
    model_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    kind: Literal["indexed_program"] = "indexed_program"
    inputs: list[str] = Field(default_factory=list, max_length=200)
    parameters: list[str] = Field(default_factory=list, max_length=100)
    axes: dict[str, list[int]] = Field(min_length=1, max_length=4)
    tables: dict[str, IndexedTable] = Field(default_factory=dict, max_length=100)
    decisions: dict[str, IndexedDecision] = Field(min_length=1, max_length=100)
    objective: IndexedObjective
    constraints: list[IndexedExpression] = Field(default_factory=list, max_length=500)
    scenario_axis: str | None = None
    probability_table: str | None = None

    @model_validator(mode="after")
    def valid(self):
        names = list(self.axes) + list(self.tables) + list(self.decisions) + self.parameters
        for name in names + self.inputs:
            check_name(name)
        if len(set(names)) != len(names) or len(set(self.inputs)) != len(self.inputs):
            raise ValueError("Indexed symbols must have distinct names")
        for axis, values in self.axes.items():
            if not values or len(values) > 1000 or len(set(values)) != len(values):
                raise ValueError("Axes require 1..1000 unique integer labels")
        specs = list(self.tables.values()) + list(self.decisions.values())
        for spec in specs:
            if len(set(spec.axes)) != len(spec.axes) or set(spec.axes) - set(self.axes):
                raise ValueError("Unknown or duplicate tensor axes")
        for term in self.objective.terms + self.constraints:
            if len(set(term.over)) != len(term.over) or set(term.over) - set(self.axes):
                raise ValueError("Unknown or duplicate expansion axes")
        for table in self.tables.values():
            if table.column not in self.inputs or set(table.axes) - set(self.inputs):
                raise ValueError("Tables require declared column and axis columns in inputs")
        if (self.scenario_axis is None) != (self.probability_table is None):
            raise ValueError("Scenario axis and probability table must be declared together")
        if self.scenario_axis is not None:
            if self.scenario_axis not in self.axes or self.probability_table not in self.tables or self.tables[self.probability_table].axes != [self.scenario_axis]:
                raise ValueError("Probability table must be indexed by the declared scenario axis")
        for decision in self.decisions.values():
            Decision(lower=decision.lower, upper=decision.upper, domain=decision.domain)
            has_scenario = self.scenario_axis is not None and self.scenario_axis in decision.axes
            if has_scenario != (decision.information is not None):
                raise ValueError("Scenario-indexed decisions require explicit information; shared decisions omit it")
        if sum(math.prod(len(self.axes[a]) for a in d.axes) for d in self.decisions.values()) > 1000:
            raise ValueError("At most 1000 expanded decisions")
        if sum(math.prod(len(self.axes[a]) for a in t.over) for t in self.constraints + self.objective.terms) > 5000:
            raise ValueError("At most 5000 expanded terms/constraints")
        return self


class IntegrationModelSpec(Contract):
    schema_version: Literal["1"] = "1"
    model_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    kind: Literal["numerical_integration"] = "numerical_integration"
    inputs: list[str] = Field(default_factory=list, max_length=200)
    parameters: list[str] = Field(default_factory=list, max_length=100)
    variable: str = "x"
    expression: str = Field(min_length=1, max_length=2000)
    lower: str = Field(min_length=1, max_length=2000)
    upper: str = Field(min_length=1, max_length=2000)
    absolute_tolerance: float = Field(default=1e-8, ge=1e-12, le=1)
    relative_tolerance: float = Field(default=1e-8, ge=1e-12, le=1)
    subdivision_limit: int = Field(default=100, ge=1, le=1000, strict=True)
    evaluation_limit: int = Field(default=100000, ge=1, le=1000000, strict=True)

    @model_validator(mode="after")
    def valid(self):
        names = self.inputs + self.parameters + [self.variable]
        for name in names:
            check_name(name)
        if len(names) != len(set(names)):
            raise ValueError("Integration symbols must be distinct")
        return self


ExecutionRequest.model_rebuild()
ExecutionResult.model_rebuild()
