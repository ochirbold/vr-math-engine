"""Single-series demand pilot, outside the generic compiler/solver.

Dates, feature engineering, chronological splits, and horizon aggregation belong
here. The core receives ordinary numeric model specifications and datasets.
"""
from datetime import date, timedelta
import math

import numpy as np
from pydantic import Field, model_validator

from ..contracts import Contract, Dataset, ExecutionRequest, PredictionRequest
from ..engine import execute
from ..expressions import ModelError
from ..statistics import log_likelihood, observations, predict


class PlanDay(Contract):
    date: date
    price: float = Field(gt=0)
    promotion: int = Field(ge=0, le=1, strict=True)


class ObservedDay(PlanDay):
    sales: int = Field(ge=0, le=10**12, strict=True)
    available: int = Field(ge=0, le=10**12, strict=True)
    censored: int = Field(ge=0, le=1, strict=True)

    @model_validator(mode="after")
    def observation_consistency(self):
        if self.censored and self.sales != self.available or not self.censored and self.sales >= self.available:
            raise ValueError("Y=min(D,A) requires censored sales=available, exact sales<available")
        return self


class DemandPilotRequest(Contract):
    sku: str = Field(min_length=1, max_length=100)
    branch: str = Field(min_length=1, max_length=100)
    train_end: date
    history: list[ObservedDay] = Field(min_length=3, max_length=10000)
    future: list[PlanDay] = Field(min_length=90, max_length=90)
    time_limit_seconds: float = Field(default=60, gt=0, le=60)

    @model_validator(mode="after")
    def chronology(self):
        for group in (self.history, self.future):
            if any(b.date != a.date + timedelta(days=1) for a, b in zip(group, group[1:])):
                raise ValueError("Dates must be sorted, unique and daily without gaps")
        if self.future[0].date != self.history[-1].date + timedelta(days=1):
            raise ValueError("Future must start immediately after history")
        if not self.history[0].date <= self.train_end < self.history[-1].date:
            raise ValueError("train_end must leave both training and holdout observations")
        return self


FEATURE_VERSION = "price-promotion-annual-fourier-v1"
FEATURES = ["log_price", "promotion", "season_sin", "season_cos"]


def features(day):
    # Fixed epoch/period, never fitted using test data. This is a pilot basis,
    # not a claim that every product has a sinusoidal annual seasonal pattern.
    angle = 2 * math.pi * (day.date - date(2024, 1, 1)).days / 365.25
    return {"log_price": math.log(day.price / 100.), "promotion": float(day.promotion),
            "season_sin": math.sin(angle), "season_cos": math.cos(angle)}


def dataset(days, *, observed=False, baseline=False):
    rows = []
    for day in days:
        row = {} if baseline else features(day)
        if observed:
            row |= {"sales": float(day.sales), "available": float(day.available), "censored": float(day.censored)}
        rows.append(row)
    return Dataset(row_ids=[d.date.isoformat() for d in days], rows=rows)


def specification(days, *, baseline=False):
    initial = math.log(max(.1, sum(d.sales for d in days) / len(days)))
    trainable = {"intercept": {"initial": min(15., initial), "lower": -15., "upper": 15.},
                 "dispersion": {"initial": .4, "lower": .001, "upper": 20., "transform": "log"}}
    terms = ["intercept"]
    if not baseline:
        for name in FEATURES:
            trainable["coef_" + name] = {"initial": 0., "lower": -5., "upper": 5.}
            terms.append("coef_" + name + " * " + name)
    return {"model_id": "single-series-nb-baseline" if baseline else "single-series-nb",
            "version": "1", "kind": "statistical_fit", "inputs": [] if baseline else FEATURES,
            "standardize": [] if baseline else ["log_price"],
            "trainable": trainable, "predictor": " + ".join(terms), "link": "log",
            "distribution": "negative_binomial", "dispersion_parameter": "dispersion",
            "observation": {"kind": "right_censored", "response": "sales",
                            "censored": "censored", "threshold": "available"}}


def fit_days(days, time_limit, *, baseline=False):
    request = ExecutionRequest.model_validate({"model": specification(days, baseline=baseline),
                                               "dataset": dataset(days, observed=True, baseline=baseline).model_dump(),
                                               "solver": {"time_limit_seconds": time_limit}})
    if not baseline:
        # Reject a model whose requested effects cannot be separated in this
        # pilot. A smaller feature model must be chosen explicitly in that case.
        design = np.array([[1.] + list(features(d).values()) for d in days])
        if np.linalg.matrix_rank(design) < design.shape[1]:
            raise ModelError("Pilot features are collinear or constant; choose a smaller feature model")
    result = execute(request)
    if result.status != "succeeded":
        raise ModelError(f"Pilot fit failed: {result.diagnostics}")
    return result


def prediction(artifact, days, *, baseline=False):
    result = predict(PredictionRequest(artifact=artifact, dataset=dataset(days, baseline=baseline)))
    return [{"date": d.date.isoformat(), **output} for d, output in zip(days, result.outputs)]


def holdout_metrics(artifact, days, predictions, *, baseline=False):
    y, censored, threshold = observations(artifact.model, dataset(days, observed=True, baseline=baseline))
    mu = np.array([p["mean"] for p in predictions])
    scores = log_likelihood("negative_binomial", y, mu, censored, threshold,
                            artifact.fitted_parameters["dispersion"])
    informative = threshold > 0
    exact = ~censored
    return {"rows": len(days), "censored_rows": int(censored.sum()),
            "zero_capacity_rows": int((~informative).sum()),
            "observation_nll_mean": float(-scores.mean()),
            "informative_observation_nll_mean": float(-scores[informative].mean()) if informative.any() else None,
            # This is a selected subset, deliberately NOT called latent-demand MAE.
            "exact_subset_mae": float(np.abs(y[exact] - mu[exact]).mean()) if exact.any() else None,
            "exact_subset_mae_caveat": "Selected uncensored subset; not full latent-demand accuracy"}


def run_pilot(request: DemandPilotRequest):
    training = [d for d in request.history if d.date <= request.train_end]
    holdout = [d for d in request.history if d.date > request.train_end]
    trained = fit_days(training, request.time_limit_seconds)
    baseline = fit_days(training, request.time_limit_seconds, baseline=True)
    test_predictions = prediction(trained.fitted_artifact, holdout)
    baseline_predictions = prediction(baseline.fitted_artifact, holdout, baseline=True)
    # Holdout never enters the evaluation fit. Refit is a separate artifact used
    # only for future forecasts made at the final historical date.
    production = fit_days(request.history, request.time_limit_seconds)
    future = prediction(production.fitted_artifact, request.future)
    metrics = holdout_metrics(trained.fitted_artifact, holdout, test_predictions)
    baseline_metrics = holdout_metrics(baseline.fitted_artifact, holdout, baseline_predictions, baseline=True)
    return {"sku": request.sku, "branch": request.branch, "feature_version": FEATURE_VERSION,
            "evaluation": {"train_start": training[0].date.isoformat(), "train_end": training[-1].date.isoformat(),
                           "test_start": holdout[0].date.isoformat(), "test_end": holdout[-1].date.isoformat(),
                           "training_rows": len(training), "test_rows": len(holdout),
                           "metrics": metrics, "baseline_metrics": baseline_metrics,
                           "nll_improvement_vs_baseline": baseline_metrics["observation_nll_mean"] - metrics["observation_nll_mean"],
                           "predictions": test_predictions, "baseline_predictions": baseline_predictions,
                           "artifact": trained.fitted_artifact.model_dump(mode="json"),
                           "baseline_artifact": baseline.fitted_artifact.model_dump(mode="json"),
                           "diagnostics": trained.diagnostics},
            "forecast": {"origin": request.history[-1].date.isoformat(), "daily": future,
                         "horizons": [{"days": h, "start": future[0]["date"], "end": future[h-1]["date"],
                                       "expected_demand": sum(d["mean"] for d in future[:h])} for h in (7, 30, 90)],
                         "artifact": production.fitted_artifact.model_dump(mode="json"), "diagnostics": production.diagnostics},
            "assumptions": ["One SKU and branch; independent conditional NB observations",
                            "Explicit Y=min(D,A); censor mechanism is ignorable conditional on features",
                            "Holdout covariates treated as known scenarios, not necessarily historical plans",
                            "Future prices/promotions supplied; no automatic future covariate prediction",
                            "No global optimum, parameter identifiability or production accuracy guarantee",
                            "Horizon means are summed; no interval or temporal covariance estimate"]}
