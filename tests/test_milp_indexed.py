from itertools import product
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from math_engine.contracts import ExecutionRequest
from math_engine.engine import execute
from math_engine.expressions import ModelError

ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT / "examples" / (name + ".json")).read_text())


def run(raw):
    return execute(ExecutionRequest.model_validate(raw))


def scalar(expression="3*x+7", sense="maximize", domain="integer", lower=0, upper=5, constraints=None):
    return {"model": {"model_id": "integer-test", "version": "1", "kind": "mixed_integer_program",
                      "decisions": {"x": {"domain": domain, "lower": lower, "upper": upper}},
                      "objective": {"sense": sense, "expression": expression},
                      "constraints": ["x <= 2.7"] if constraints is None else constraints},
            "dataset": {"row_ids": ["1"], "rows": [{}]}}


def test_integer_domain_not_rounding_a_relaxed_lp():
    result = run(scalar())
    assert result.solution == {"x": 2}
    assert result.objective == 13
    assert result.diagnostics["objective_bound"] == 13
    assert result.diagnostics["mip_gap"] == 0
    assert result.diagnostics["max_integrality_violation"] == 0
    assert run(scalar(domain="binary")).solution == {"x": 1}
    assert run(scalar(lower=.2, upper=.8, constraints=[])).status == "infeasible"


def test_integer_cannot_silently_use_lp_contract():
    raw = scalar()
    raw["model"]["kind"] = "linear_program"
    with pytest.raises(ValidationError):
        run(raw)


@pytest.mark.parametrize("expression,sense,expected", [
    ("positive_part(x)", "maximize", 3),
    ("-positive_part(x)", "minimize", -3),
    ("positive_part(x)", "minimize", 0),
    ("positive_part(positive_part(x)-1)", "maximize", 2)])
def test_positive_part_exact_graph_under_both_signs(expression, sense, expected):
    result = run(scalar(expression, sense, "continuous", -2, 3, []))
    assert result.status == "succeeded"
    assert result.objective == pytest.approx(expected)


def test_positive_part_in_equality_not_epigraph():
    raw = scalar("y", "maximize", "continuous", -2, 3, ["x == -1", "y == positive_part(x)"])
    raw["model"]["decisions"]["y"] = {"lower": 0, "upper": 4}
    result = run(raw)
    assert result.solution["y"] == 0
    assert result.solution["x"] == -1
    with pytest.raises(ModelError, match="finite explicit"):
        run(scalar("positive_part(x)", upper=None))


def test_indexed_allocation_matches_independent_exhaustive_solution():
    raw = example("indexed_allocation")
    result = run(raw)
    candidates = []
    for a in product(range(5), range(6), range(4)):
        if sum(a) <= 7:
            value = sum(r["prob"]*(4*max(r["need"]-r["on_hand"]-a[r["b"]], 0)+a[r["b"]]) for r in raw["dataset"]["rows"])
            candidates.append((value, a))
    expected, choice = min(candidates)
    assert result.status == "succeeded"
    assert result.objective == pytest.approx(expected)
    assert result.solution["allocation"] == list(choice) == [3, 3, 1]
    assert sum(result.solution["allocation"]) <= 7
    assert result.diagnostics["max_constraint_violation"] < 1e-7


def test_time_balance_lead_and_moq_against_enumeration():
    result = run(example("indexed_replenishment"))
    assert result.status == "succeeded"
    # Independent simulator: enumerate shared orders; demand consumed after
    # arrivals, unmet demand lost, one-period lead, no terminal salvage value.
    candidates = []
    for q in product([0, 2, 3, 4, 5, 6], repeat=2):
        total = 0.
        for path in ([1, 1], [3, 4]):
            stock = 2
            for t, d in enumerate(path):
                stock += q[t-1] if t else 0
                unmet = max(d-stock, 0)
                stock = max(stock-d, 0)
                total += .5*(2*int(q[t]>0)+q[t]+.2*stock+6*unmet)
        candidates.append((total, q))
    expected, q = min(candidates)
    assert result.objective == pytest.approx(expected) == pytest.approx(9.5)
    assert result.solution["order"] == list(q) == [4, 0]
    assert result.solution["placed"] == [1, 0]
    assert result.solution["unmet"] == [0, 1, 0, 0]


def test_information_sets_prevent_future_information_leakage():
    raw = example("indexed_information")
    result = run(raw)
    assert result.objective == 6
    assert result.solution["choice"] == [3, 3, 2, 4]
    assert result.diagnostics["information_equalities"] == 1
    # Explicit perfect-information relaxation costs less. Without this check a
    # stochastic compiler could accidentally report the clairvoyant answer.
    raw["model"]["decisions"]["choice"]["information"] = "scenario_specific"
    clairvoyant = run(raw)
    assert clairvoyant.objective == 5
    assert clairvoyant.solution["choice"] == [1, 3, 2, 4]


@pytest.mark.parametrize("case", ["missing_partition", "overlap", "unknown_scenario", "missing_information", "unbound_axis", "bad_index", "unsafe", "shadow_sum"])
def test_reject_invalid_index_or_information(case):
    raw = example("indexed_information")
    spec = raw["model"]["decisions"]["choice"]
    if case == "missing_partition":
        spec["information"].pop()
    elif case == "overlap":
        spec["information"][0]["groups"] = [[0, 1], [1]]
    elif case == "unknown_scenario":
        spec["information"][0]["groups"] = [[0, 2]]
    elif case == "missing_information":
        del spec["information"]
    elif case == "unbound_axis":
        raw["model"]["constraints"][0]["over"] = ["t"]
    elif case == "bad_index":
        raw["model"]["constraints"][0]["expression"] = "choice[t,choice[t,s]] >= 0"
    elif case == "unsafe":
        raw["model"]["constraints"][0]["expression"] = "choice.__class__ == 0"
    else:
        raw["model"]["constraints"][0]["expression"] = "SUM_OVER(t, choice[t,s]) >= 0"
    with pytest.raises((ModelError, ValidationError)):
        run(raw)


@pytest.mark.parametrize("case", ["missing_boundary", "boundary_override", "duplicate_boundary", "missing_data", "conflicting_data", "bad_probability", "fractional_axis"])
def test_reject_ambiguous_boundary_or_data(case):
    raw = example("indexed_replenishment")
    if case == "missing_boundary":
        raw["model"]["decisions"]["order"]["boundary"] = []
    elif case == "boundary_override":
        raw["model"]["decisions"]["order"]["boundary"][0]["index"] = [0]
    elif case == "duplicate_boundary":
        raw["model"]["decisions"]["order"]["boundary"] *= 2
    elif case == "missing_data":
        raw["dataset"]["rows"].pop()
        raw["dataset"]["row_ids"].pop()
    elif case == "conflicting_data":
        raw["dataset"]["rows"][2]["prob"] = .7
    elif case == "bad_probability":
        for row in raw["dataset"]["rows"]:
            row["prob"] = .4
    else:
        raw["dataset"]["rows"][0]["t"] = .5
    with pytest.raises((ModelError, ValidationError)):
        run(raw)


def test_milp_limit_or_fractional_incumbent_never_published_as_optimal(monkeypatch):
    import math_engine.linear as linear
    monkeypatch.setattr(linear, "milp", lambda *a, **kw: SimpleNamespace(status=1, message="time limit", x=np.array([2.])))
    limited = run(scalar())
    assert limited.status == "failed" and limited.solution == {}
    assert limited.diagnostics["limit_reached"]
    monkeypatch.setattr(linear, "milp", lambda *a, **kw: SimpleNamespace(status=0, message="bad incumbent", x=np.array([1.4])))
    fractional = run(scalar())
    assert fractional.status == "failed" and fractional.solution == {}
    assert "Integrality" in fractional.diagnostics["message"]
