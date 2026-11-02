from datetime import timedelta
import json

import pytest
from pydantic import ValidationError

from math_engine.applications.demand import DemandPilotRequest, dataset, fit_days, run_pilot
from math_engine.applications.synthetic_demand import evaluate_truth, generate
from math_engine.contracts import FittedArtifact, PredictionRequest
from math_engine.expressions import ModelError
from math_engine.statistics import predict


@pytest.fixture(scope="module")
def experiment():
    request, truth = generate()
    report = run_pilot(request)
    return request, truth, report


def test_synthetic_censored_nb_end_to_end(experiment):
    request, truth, report = experiment
    ev, future = report["evaluation"], report["forecast"]
    assert (ev["training_rows"], ev["test_rows"]) == (365, 90)
    assert ev["artifact"]["training_rows"] == 365
    assert future["artifact"]["training_rows"] == 455
    assert ev["artifact"]["training_checksum"] != future["artifact"]["training_checksum"]
    assert ev["diagnostics"]["converged"] and future["diagnostics"]["converged"]
    assert 0 < ev["metrics"]["censored_rows"] < 90
    assert ev["metrics"]["observation_nll_mean"] < ev["baseline_metrics"]["observation_nll_mean"]
    oracle = evaluate_truth(report, truth)
    assert oracle["holdout"]["true_mean_mae"] < oracle["baseline_holdout"]["true_mean_mae"]
    assert abs(future["artifact"]["fitted_parameters"]["dispersion"] - .35) < .15
    # NB fit should recover expected demand rather than clipped sales; the
    # synthetic known means are used only here as an independent validation.
    actual_mean_sum = oracle["horizons"][-1]["true_mean_sum"]
    assert abs(future["horizons"][-1]["expected_demand"] / actual_mean_sum - 1) < .2
    assert "latent_demand" not in json.dumps(request.model_dump(mode="json"))
    assert "true_mean" not in json.dumps(ev["artifact"])


def test_horizons_dates_and_saved_artifact_prediction(experiment):
    request, _, report = experiment
    artifact = FittedArtifact.model_validate(report["forecast"]["artifact"])
    prediction = predict(PredictionRequest(artifact=artifact, dataset=dataset(request.future)))
    for horizon in report["forecast"]["horizons"]:
        h = horizon["days"]
        assert horizon["start"] == request.future[0].date.isoformat()
        assert horizon["end"] == (request.future[0].date + timedelta(days=h-1)).isoformat()
        assert horizon["expected_demand"] == pytest.approx(sum(p["mean"] for p in prediction.outputs[:h]))


def test_holdout_and_future_never_enter_evaluation_fit(monkeypatch, experiment):
    import math_engine.applications.demand as demand
    request, _, report = experiment
    # Instrument the fit boundary, retaining the real predictions and metrics.
    # Every fit input is recorded; no hidden all-history feature fit is permitted.
    calls = []
    from types import SimpleNamespace

    def recorded_fit(days, time_limit, *, baseline=False):
        calls.append([d.date for d in days])
        artifact = report["evaluation"]["baseline_artifact" if baseline else "artifact"]
        if len(days) == 455:
            artifact = report["forecast"]["artifact"]
        return SimpleNamespace(fitted_artifact=FittedArtifact.model_validate(artifact), diagnostics={})

    monkeypatch.setattr(demand, "fit_days", recorded_fit)
    modified = request.model_copy(deep=True)
    for day in modified.history:
        if day.date > request.train_end:
            day.sales, day.available, day.censored = 0, 100, 0
    revised = run_pilot(modified)
    assert len(calls) == 3
    assert calls[0] == calls[1] == [d.date for d in request.history[:365]]
    assert calls[2] == [d.date for d in request.history]
    assert revised["evaluation"]["predictions"] == report["evaluation"]["predictions"]
    assert revised["evaluation"]["metrics"] != report["evaluation"]["metrics"]


@pytest.mark.parametrize("case", ["gap", "duplicate", "future_overlap", "no_holdout", "fractional_count", "bad_censor", "short_future", "truth_in_input"])
def test_reject_ambiguous_or_leaking_input(case):
    request, _ = generate()
    raw = request.model_dump(mode="json")
    if case == "gap":
        del raw["history"][20]
    elif case == "duplicate":
        raw["history"][20]["date"] = raw["history"][19]["date"]
    elif case == "future_overlap":
        raw["future"][0]["date"] = raw["history"][-1]["date"]
    elif case == "no_holdout":
        raw["train_end"] = raw["history"][-1]["date"]
    elif case == "fractional_count":
        raw["history"][0]["sales"] = .5
    elif case == "bad_censor":
        raw["history"][0].update(sales=10, available=10, censored=0)
    elif case == "short_future":
        raw["future"].pop()
    else:
        raw["history"][0]["latent_demand"] = 42
    with pytest.raises(ValidationError):
        DemandPilotRequest.model_validate(raw)


def test_constant_features_require_explicit_model_change():
    request, _ = generate()
    for day in request.history:
        day.price = 100.
    with pytest.raises(ModelError, match="collinear"):
        fit_days(request.history[:365], 60)


def test_generator_reproducible_and_exogenous_capacity():
    first, truth = generate()
    second, truth_again = generate()
    assert first == second and truth == truth_again
    # No mixed SKU/branch rows, missing dates or implicit equality inference.
    for day, hidden in zip(first.history, truth["rows"]):
        assert day.sales == min(day.available, hidden["latent_demand"])
        assert day.censored == int(hidden["latent_demand"] >= day.available)
