import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.stats import poisson, nbinom

from math_engine.contracts import ExecutionRequest, PredictionRequest, Dataset, FittedArtifact
from math_engine.engine import execute
from math_engine.expressions import Context, ModelError, evaluate, parse
from math_engine.expression_types import infer_shape, SCALAR
from math_engine.statistics import compile_statistics, fit, log_likelihood, predict
from math_engine.storage import JobStore
from math_engine.contracts import JobRequest

ROOT = Path(__file__).resolve().parents[1]


def example(name="poisson"):
    return json.loads((ROOT / "examples" / (name + ".json")).read_text())


def test_poisson_mle_and_artifact_roundtrip():
    request = ExecutionRequest.model_validate(example())
    result = execute(request)
    assert result.status == "succeeded"
    assert result.solution["intercept"] == pytest.approx(math.log(3), abs=1e-5)
    assert result.objective == pytest.approx(-poisson.logpmf([1, 2, 3, 4, 5, 3], 3).sum())
    artifact = FittedArtifact.model_validate_json(result.fitted_artifact.model_dump_json())
    predicted = predict(PredictionRequest(artifact=artifact, dataset=Dataset(row_ids=["new"], rows=[{}])))
    assert predicted.outputs[0]["mean"] == pytest.approx(3, abs=1e-5)
    assert predicted.outputs[0]["variance"] == pytest.approx(3, abs=1e-5)


@pytest.mark.parametrize("family,alpha", [("poisson", None), ("negative_binomial", .5)])
def test_right_censored_likelihood_includes_threshold(family, alpha):
    y, mu, mask, limit = np.array([2., 4.]), np.array([3., 3.]), np.array([False, True]), np.array([4., 4.])
    actual = log_likelihood(family, y, mu, mask, limit, alpha)
    # Independent explicit sum checks the discrete off-by-one, not just logsf call parity.
    pmf = poisson.pmf if family == "poisson" else lambda k, m: nbinom.pmf(k, 2, 2 / (2 + m))
    assert actual[0] == pytest.approx(math.log(pmf(2, 3)))
    assert actual[1] == pytest.approx(math.log(1 - sum(pmf(k, 3) for k in range(4))))


def test_negative_binomial_recovers_seeded_parameters():
    raw = example()
    raw["model"].update(distribution="negative_binomial", dispersion_parameter="alpha")
    raw["model"]["trainable"]["alpha"] = {"initial": .5, "transform": "log", "lower": .001, "upper": 10}
    counts = np.random.default_rng(2026).negative_binomial(2, 2 / 7, size=700)
    raw["dataset"] = {"row_ids": [str(i) for i in range(len(counts))], "rows": [{"count": int(y)} for y in counts]}
    result = execute(ExecutionRequest.model_validate(raw))
    assert result.status == "succeeded"
    assert result.outputs[0]["mean"] == pytest.approx(counts.mean(), rel=.001)
    assert result.solution["alpha"] == pytest.approx(.5, abs=.13)
    assert result.outputs[0]["variance"] > result.outputs[0]["mean"]


def test_standardization_frozen_at_training_not_prediction():
    raw = example()
    raw["model"].update(inputs=["x"], standardize=["x"], predictor="intercept + slope*x", parameters=["slope"])
    raw["parameters"] = {"slope": .2}
    for i, row in enumerate(raw["dataset"]["rows"]):
        row["x"] = i
    result = execute(ExecutionRequest.model_validate(raw))
    artifact = result.fitted_artifact
    assert artifact.preprocessing["x"].center == 2.5
    predicted = predict(PredictionRequest(artifact=artifact, dataset=Dataset(row_ids=["future"], rows=[{"x": 10}])))
    expected = math.exp(result.solution["intercept"] + .2 * (10 - 2.5) / np.std(range(6)))
    assert predicted.outputs[0]["mean"] == pytest.approx(expected)
    bad = artifact.model_copy(deep=True)
    bad.fitted_parameters = {}
    with pytest.raises(ModelError, match="parameters"):
        predict(PredictionRequest(artifact=bad, dataset=Dataset(row_ids=["future"], rows=[{"x": 10}])))


@pytest.mark.parametrize("predictor", ["count + intercept", "COLUMN_SUM('count') + intercept", "[intercept, 2]", "DOT([intercept,1],[2])", "abs(intercept)"])
def test_predictor_rejects_leakage_wrong_shape_and_nonsmooth(predictor):
    raw = example()
    raw["model"]["predictor"] = predictor
    with pytest.raises(ModelError):
        compile_statistics(ExecutionRequest.model_validate(raw).model)


@pytest.mark.parametrize("change", [{"observed": 7}, {"is_censored": .5}, {"limit": -1}])
def test_invalid_censoring(change):
    raw = example("negative_binomial")
    raw["dataset"]["rows"][7].update(change)
    with pytest.raises(ModelError):
        execute(ExecutionRequest.model_validate(raw))


def test_censored_example_fits_and_is_not_naive_clipped_mean():
    request = ExecutionRequest.model_validate(example("negative_binomial"))
    result = execute(request)
    assert result.status == "succeeded"
    assert result.outputs[0]["mean"] > np.mean([r["observed"] for r in request.dataset.rows])
    assert result.diagnostics["censored_rows"] == 2


def test_failure_does_not_publish_artifact():
    class FailingBackend:
        def solve(self, objective, initial, bounds, max_iterations):
            return SimpleNamespace(x=initial, nit=1, success=False, message="iteration limit")
    result = fit(ExecutionRequest.model_validate(example()), FailingBackend())
    assert result.status == "failed" and result.fitted_artifact is None


def test_invalid_initial_domain_is_rejected():
    raw = example()
    raw["model"]["link"] = "identity"
    with pytest.raises(ModelError, match="positive"):
        execute(ExecutionRequest.model_validate(raw))


def test_fit_timeout(monkeypatch):
    import math_engine.statistics as statistics
    times = iter([0., 100.])
    monkeypatch.setattr(statistics, "perf_counter", lambda: next(times))
    result = fit(ExecutionRequest.model_validate(example()))
    assert result.status == "failed" and result.diagnostics["reason"] == "fit_timeout"


def test_log_exp_domains_and_lp_rejection():
    assert evaluate(parse("log(exp(2))"), Context({}, [])) == pytest.approx(2)
    for text in ("log(0)", "sqrt(-1)", "exp(1000)"):
        with pytest.raises(ModelError):
            evaluate(parse(text), Context({}, []))
    raw = example("allocation")
    raw["model"]["objective"]["expression"] = "exp(SUM(allocation))"
    with pytest.raises(ModelError, match="Nonlinear"):
        execute(ExecutionRequest.model_validate(raw))


def test_fitted_artifact_durable_with_job_and_pinned_model(tmp_path):
    request = ExecutionRequest.model_validate(example())
    store = JobStore(tmp_path / "jobs.db")
    store.register(request.model)
    job = store.submit(JobRequest(model_id=request.model.model_id, model_version="1", snapshot_id="test", idempotency_key="fit"))
    claimed = store.claim()
    store.computed(job["id"], claimed["lease"], execute(request))
    reopened = JobStore(tmp_path / "jobs.db").get(job["id"])
    assert reopened["state"] == "SUCCEEDED"
    assert reopened["result"]["fitted_artifact"]["training_rows"] == 6
