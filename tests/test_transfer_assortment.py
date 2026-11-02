"""Example-only verification against independent finite enumerations.

The mathematical core is unchanged: both examples use indexed_program.
"""
from itertools import product
import json
import math
from pathlib import Path

import pytest

from math_engine.contracts import ExecutionRequest
from math_engine.engine import execute

ROOT = Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT / "examples" / (name + ".json")).read_text())


def run(raw):
    return execute(ExecutionRequest.model_validate(raw))


def indexed_values(result, name):
    return dict(zip((tuple(x) for x in result.diagnostics["indexed_layout"][name]["indices"]), result.solution[name]))


def transfer_oracle(raw):
    # Independent two-date simulator for this example's t=0 dispatch window.
    rows = raw["dataset"]["rows"]
    branches = {r["b"]: r for r in rows}
    routes = {(r["a"], r["b"]): r for r in rows}
    needs = {(r["b"], r["t"], r["s"]): r["need"] for r in rows}
    weights = {r["s"]: r["prob"] for r in rows}
    initial = [raw["parameters"]["initial_A"], raw["parameters"]["initial_B"]]
    candidates = []
    for ab, ba in product(range(7), repeat=2):
        shipped = {(0, 1): ab, (1, 0): ba}
        if any(q > max(initial[a]-branches[a]["reserve_value"], 0) for (a, b), q in shipped.items()):
            continue
        if any(q and not (branches[a]["gate_value"] == branches[b]["gate_value"] == 1) for (a, b), q in shipped.items()):
            continue
        state = initial[:]
        objective = sum(routes[a,b]["route_cost"]*q for (a,b),q in shipped.items())
        valid = True
        for t in range(2):
            for (a,b), q in shipped.items():
                if t == 0:
                    state[a] -= q
                if t == routes[a,b]["lead_value"]:
                    state[b] += q
            if t == -1 + routes[0,1]["lead_value"]:
                state[1] += raw["parameters"]["pipeline"]
            if any(v < 0 or v > branches[b]["capacity_value"] for b,v in enumerate(state)):
                valid = False
                break
            objective += sum(weights[s]*branches[b]["penalty_value"]*max(needs[b,t,s]-state[b], 0)
                             for b,s in product(range(2), repeat=2))
        if valid:
            candidates.append((objective, ab, ba))
    return min(candidates)


def test_transfer_arrival_reserve_and_total_stock():
    raw = example("indexed_transfer")
    result = run(raw)
    expected, ab, ba = transfer_oracle(raw)
    assert result.status == "succeeded"
    assert result.objective == pytest.approx(expected) == pytest.approx(26)
    transfers, stocks = indexed_values(result, "transfer"), indexed_values(result, "stock")
    assert transfers[0,1,0] == ab == 6
    assert transfers[1,0,0] == ba == 0
    assert all(value == 0 for (a,b,t),value in transfers.items() if a == b or t == 1)
    assert stocks[1,0] == 0  # Six units still in transit cannot satisfy t=0 demand.
    assert stocks[1,1] == 6
    assert stocks[0,0] == stocks[0,1] == 2  # Donor reserve retained.
    assert stocks[0,0] + stocks[1,0] + transfers[0,1,0] == 8
    assert stocks[0,1] + stocks[1,1] == 8


@pytest.mark.parametrize("branch", [0, 1])
def test_unapproved_sender_or_receiver_cannot_transfer(branch):
    raw = example("indexed_transfer")
    for row in raw["dataset"]["rows"]:
        if row["b"] == branch:
            row["gate_value"] = 0
    result = run(raw)
    assert all(q == 0 for q in result.solution["transfer"])
    assert result.objective == pytest.approx(transfer_oracle(raw)[0]) == pytest.approx(45)


def test_receiver_capacity_and_pipeline_arrival():
    raw = example("indexed_transfer")
    for row in raw["dataset"]["rows"]:
        if row["b"] == 1:
            row["capacity_value"] = 5
    result = run(raw)
    assert indexed_values(result, "transfer")[0,1,0] == 5
    assert result.objective == pytest.approx(transfer_oracle(raw)[0]) == pytest.approx(27.5)
    raw = example("indexed_transfer")
    raw["parameters"]["pipeline"] = 1
    result = run(raw)
    assert indexed_values(result, "stock")[1,0] == 1
    assert indexed_values(result, "transfer")[0,1,0] == 5
    assert result.objective == pytest.approx(transfer_oracle(raw)[0])


def test_lead_beyond_horizon_does_not_create_early_stock():
    raw = example("indexed_transfer")
    for row in raw["dataset"]["rows"]:
        row["lead_value"] = 2
    raw["model"]["decisions"]["transfer"]["boundary"] += [
        {"index": [a,b,-2], "expression": "0"} for a,b in product(range(2), repeat=2)]
    result = run(raw)
    assert all(q == 0 for q in result.solution["transfer"])
    assert result.objective == pytest.approx(transfer_oracle(raw)[0]) == pytest.approx(45)


def test_audit_gate_is_binary_input_not_a_fractional_permission():
    raw = example("indexed_transfer")
    for row in raw["dataset"]["rows"]:
        if row["b"] == 1:
            row["gate_value"] = .5
    assert run(raw).status == "infeasible"


def assortment_oracle(raw, forced=None):
    rows = raw["dataset"]["rows"]
    items = {r["i"]: r for r in rows}
    rho = {(r["i"],r["j"]): r["rho_value"] for r in rows}
    best = None
    for f in product(*(range(int(items[i]["max_value"])+1) for i in range(3))):
        if sum(items[i]["width_value"]*f[i] for i in range(3)) > raw["parameters"]["shelf_capacity"]:
            continue
        if forced is not None and tuple(f) != tuple(forced):
            continue
        selected = [int(v > 0) for v in f]
        # Literal supplied formula: substitution is NOT gated by selected[i].
        demand = [selected[i]*(items[i]["base_value"]+items[i]["eta_value"]*math.log1p(f[i]))
                  + sum(rho[i,j]*items[j]["base_value"]*(1-selected[j]) for j in range(3) if j != i)
                  for i in range(3)]
        sales = [min(demand[i], items[i]["stock_value"]) for i in range(3)]
        profit = sum(items[i]["margin_value"]*sales[i]-items[i]["setup_value"]*selected[i] for i in range(3))
        if best is None or profit > best[0]:
            best = (profit, f, selected, demand, sales)
    return best


def test_assortment_matches_original_nonlinear_formula_enumeration():
    raw = example("indexed_assortment")
    result = run(raw)
    profit, facings, selected, demand, sales = assortment_oracle(raw)
    assert result.status == "succeeded"
    assert result.objective == pytest.approx(profit)
    assert result.solution["facings"] == list(facings)
    assert result.solution["selected"] == selected
    assert result.solution["modeled_demand"] == pytest.approx(demand)
    assert result.solution["sales"] == pytest.approx(sales)
    levels = indexed_values(result, "level")
    for i in range(3):
        assert sum(levels[i,k] for k in range(4)) == 1
        assert levels[i,int(facings[i])] == 1


@pytest.mark.parametrize("facings", [(0,0,0), (2,1,0), (0,0,3), (1,1,1)])
def test_level_encoding_exact_including_absent_skus_and_stock_caps(facings):
    raw = example("indexed_assortment")
    raw["model"]["constraints"] += [{"expression": f"facings[{i}] == {f}"} for i,f in enumerate(facings)]
    result = run(raw)
    profit, _, _, demand, sales = assortment_oracle(raw, forced=facings)
    assert result.objective == pytest.approx(profit)
    assert result.solution["modeled_demand"] == pytest.approx(demand)
    assert result.solution["sales"] == pytest.approx(sales)


def test_literal_formula_retains_substitution_to_unselected_items():
    raw = example("indexed_assortment")
    raw["parameters"]["shelf_capacity"] = 0
    result = run(raw)
    assert result.solution["selected"] == [0,0,0]
    assert result.solution["facings"] == [0,0,0]
    assert result.solution["sales"] == pytest.approx([1.1,1.4,.9])
    assert result.objective == pytest.approx(15.5)


@pytest.mark.parametrize("case", ["negative", "column_sum", "diagonal"])
def test_invalid_substitution_coefficients_are_infeasible(case):
    raw = example("indexed_assortment")
    for row in raw["dataset"]["rows"]:
        if case == "negative" and (row["i"],row["j"]) == (0,1):
            row["rho_value"] = -.1
        elif case == "column_sum" and row["j"] == 0 and row["i"] != 0:
            row["rho_value"] = .7
        elif case == "diagonal" and row["i"] == row["j"]:
            row["rho_value"] = .1
    assert run(raw).status == "infeasible"
