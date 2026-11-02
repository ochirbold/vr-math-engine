import copy
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from math_engine.compiler import validate_model
from math_engine.contracts import ExecutionRequest
from math_engine.engine import execute
from math_engine.expressions import ModelError
from math_engine.uncertainty import FiniteMeasure, draw

ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT / "examples" / (name + ".json")).read_text())


def run(raw):
    return execute(ExecutionRequest.model_validate(raw))


def test_asymmetric_loss_optimum_matches_weighted_quantile():
    raw = example("scenario_balance")
    before = copy.deepcopy(raw)
    result = run(raw)
    assert raw == before
    assert result.status == "succeeded"
    assert result.solution == {"level": 9}
    assert result.aggregates["target_quantile"] == 9
    assert result.aggregates["mean_requirement"] == pytest.approx(5.6)
    # Independent analytic cost at level 9: .2*2*7 + .5*2*4 = 6.8.
    assert result.objective == pytest.approx(6.8)
    assert result.diagnostics["candidates_evaluated"] == 11
    assert result.diagnostics["optimum_scope"] == "declared_candidates_and_finite_measure"


def test_different_objective_requires_only_spec_change():
    raw = example("scenario_capacity")
    result = run(raw)
    assert result.solution == {"units": 2}
    assert result.objective == pytest.approx(8.25)
    raw["model"]["constraints"] = ["fixed_cost * units <= 4"]
    assert run(raw).solution == {"units": 1}
    raw["model"]["constraints"] = ["units == 0"]
    assert run(raw).status == "infeasible"
    raw["model"]["constraints"] = []
    raw["model"]["objective"] = {"expression": "-(units-2)**2", "sense": "maximize"}
    assert run(raw).solution == {"units": 2}


def test_joint_scenarios_preserve_dependence():
    raw = {"model": {"model_id": "joint", "version": "1", "kind": "scenario_program", "inputs": ["a", "b"],
                     "reductions": {"variance": {"expression": "a+b", "operation": "variance"}}},
           "dataset": {"row_ids": ["1", "2"], "rows": [{"a": 1, "b": 1}, {"a": 3, "b": 3}]}}
    assert run(raw).aggregates["variance"] == 4
    raw["dataset"]["rows"] = [{"a": 1, "b": 3}, {"a": 3, "b": 1}]
    assert run(raw).aggregates["variance"] == 0


def test_sampling_reproducible_and_sum_moments_correct():
    raw = example("scenario_sampling")
    first, second = run(raw), run(raw)
    assert first.aggregates == second.aggregates
    assert first.diagnostics["scenario_checksum"] == second.diagnostics["scenario_checksum"]
    assert first.aggregates["mean_total"] == pytest.approx(10, abs=.3)
    # Independent NB means 3,7 with alpha=.4: variance=10+.4*(9+49)=33.2.
    assert first.aggregates["variance_total"] == pytest.approx(33.2, abs=2)
    assert first.diagnostics["monte_carlo_estimate"]
    raw["model"]["sampling"]["variables"] = dict(reversed(list(raw["model"]["sampling"]["variables"].items())))
    assert run(raw).aggregates == first.aggregates
    raw["model"]["sampling"]["seed"] += 1
    assert run(raw).diagnostics["scenario_checksum"] != first.diagnostics["scenario_checksum"]


def test_weighted_reductions_zero_weights_and_quantile_convention():
    measure = FiniteMeasure([2, 5, 3, 0])
    values = [2, 5, 9, -999]
    assert measure.reduce(values, "expectation") == pytest.approx(5.6)
    for q, expected in [(0, 2), (.2, 2), (.21, 5), (.7, 5), (.8, 9), (1, 9)]:
        assert measure.reduce(values, "quantile", q) == expected
    assert measure.reduce(values, "variance") == pytest.approx(.2*(2-5.6)**2+.5*(5-5.6)**2+.3*(9-5.6)**2)
    # Extreme weights normalize without overflowing their raw sum.
    assert FiniteMeasure([1e308, 1e308]).reduce([1, 3], "expectation") == 2


@pytest.mark.parametrize("weights", [[0, 0], [-1, 2], [float("nan"), 1], []])
def test_invalid_weights(weights):
    with pytest.raises(ModelError):
        FiniteMeasure(weights)


def test_zero_mass_rows_do_not_restrict_support():
    raw = {"model": {"model_id": "support", "version": "1", "kind": "scenario_program", "inputs": ["a", "w"],
                     "weight_column": "w", "reductions": {"log_mean": {"expression": "log(a)"}}},
           "dataset": {"row_ids": ["1", "2"], "rows": [{"a": 1, "w": 1}, {"a": -1, "w": 0}]}}
    assert run(raw).aggregates["log_mean"] == 0
    raw["dataset"]["rows"][1]["w"] = 1
    with pytest.raises(ModelError):
        run(raw)


@pytest.mark.parametrize("mutation", ["missing_dependence", "unknown_family", "wrong_arguments", "cyclic_sampling", "extra_rows", "bad_probability", "bad_shape", "bad_domain", "undeclared_parameter"])
def test_invalid_scenario_specs(mutation):
    raw = example("scenario_sampling")
    sampling = raw["model"]["sampling"]
    if mutation == "missing_dependence":
        del sampling["dependence"]
    elif mutation == "unknown_family":
        sampling["variables"]["a"]["distribution"] = "arbitrary"
    elif mutation == "wrong_arguments":
        sampling["variables"]["a"]["arguments"] = {"stddev": "1"}
    elif mutation == "cyclic_sampling":
        sampling["variables"]["a"]["arguments"]["mean"] = "b"
    elif mutation == "extra_rows":
        raw["dataset"] = {"row_ids": ["a", "b"], "rows": [{}, {}]}
    elif mutation == "bad_probability":
        raw["model"]["reductions"]["q80_total"]["probability"] = "1.1"
    elif mutation == "bad_shape":
        raw["model"]["reductions"]["mean_total"]["expression"] = "[a,b]"
    elif mutation == "bad_domain":
        raw["parameters"]["dispersion"] = -1
    else:
        raw["parameters"]["undeclared"] = 1
    with pytest.raises((ModelError, ValidationError)):
        run(raw)


def test_sampling_families_and_domain_checks():
    rng = np.random.default_rng(42)
    assert draw("poisson", {"mean": 0}, 10, rng).tolist() == [0]*10
    assert np.mean(draw("normal", {"mean": 3, "stddev": 2}, 10000, rng)) == pytest.approx(3, abs=.1)
    uniform = draw("uniform", {"lower": -2, "upper": 4}, 10000, rng)
    assert uniform.min() >= -2 and uniform.max() <= 4
    for family, args in [("normal", {"mean": 0, "stddev": 0}), ("uniform", {"lower": 4, "upper": 4})]:
        with pytest.raises(ModelError):
            draw(family, args, 10, rng)


def test_work_budget_and_time_limit(monkeypatch):
    raw = example("scenario_sampling")
    raw["model"]["decisions"] = {"choice": {"values": list(range(1000))}}
    raw["model"]["objective"] = {"expression": "positive_part(total-choice)"}
    with pytest.raises(ModelError, match="work exceeds"):
        run(raw)
    import math_engine.scenarios as scenarios
    ticks = iter([0, 100, 101])
    monkeypatch.setattr(scenarios, "perf_counter", lambda: next(ticks))
    result = run(example("scenario_balance"))
    assert result.status == "failed"
    assert result.solution == {} and result.diagnostics["reason"] == "scenario_time_limit"


def test_existing_lp_still_rejects_nonlinear_positive_part():
    raw = example("allocation")
    raw["model"]["objective"]["expression"] = "positive_part(SUM(allocation))"
    with pytest.raises(ModelError, match="Nonlinear"):
        run(raw)


def test_validation_reports_backend_capability():
    model = ExecutionRequest.model_validate(example("scenario_capacity")).model
    assert validate_model(model)["backend"] == "finite_enumeration"


def test_multiple_decisions_and_deterministic_tie_break():
    raw = {"model": {"model_id": "choices", "version": "1", "kind": "scenario_program",
                     "decisions": {"a": {"values": [1, 0]}, "b": {"values": [1, 0]}},
                     "constraints": ["a+b <= 1"], "objective": {"expression": "3*a+2*b", "sense": "maximize"}},
           "dataset": {"row_ids": ["1"], "rows": [{}]}}
    assert run(raw).solution == {"a": 1, "b": 0}
    raw["model"]["objective"]["expression"] = "a+b"
    # Equal score: ascending candidates in sorted variable-name order wins.
    assert run(raw).solution == {"a": 0, "b": 1}


def test_quantile_objective_uses_risk_not_mean():
    raw = {"model": {"model_id": "risk", "version": "1", "kind": "scenario_program", "inputs": ["x"],
                     "decisions": {"a": {"values": [0, 1]}},
                     "objective": {"expression": "a*3+(1-a)*x", "operation": "quantile", "probability": "0.95"}},
           "dataset": {"row_ids": ["1", "2", "3", "4"], "rows": [{"x": 0}, {"x": 0}, {"x": 0}, {"x": 8}]}}
    assert run(raw).solution == {"a": 1}
    raw["model"]["objective"] = {"expression": "a*3+(1-a)*x"}
    assert run(raw).solution == {"a": 0}
