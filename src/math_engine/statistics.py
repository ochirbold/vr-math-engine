"""Generic count-distribution likelihood fitting and artifact-only prediction.

No demand features, database access, HTTP, or implicit censoring inference.
NB2 parameterization: Var(Y) = mu + alpha * mu**2.
"""
import ast
import hashlib
import json
import math
from time import perf_counter

import numpy as np
import scipy
from scipy.optimize import minimize
from scipy.stats import nbinom, poisson

from .contracts import ExecutionResult, FittedArtifact, FeatureTransform
from .expressions import Context, FUNCTIONS, ModelError, evaluate, finite_scalar, parse, references
from .expression_types import SCALAR, infer_shape


def compile_statistics(model):
    names = set(model.inputs + model.parameters) | set(model.trainable)
    if names & FUNCTIONS:
        raise ModelError("Model identifiers cannot shadow registered functions")
    tree = parse(model.predictor)
    used, columns = references(tree)
    if columns or used - names:
        raise ModelError("Predictor may reference only features and declared parameters; no observation columns or aggregates")
    if infer_shape(tree, {n: SCALAR for n in names}).kind != "scalar":
        raise ModelError("Statistical predictor must return a scalar for each row")
    unused = set(model.trainable) - used - {model.dispersion_parameter}
    if unused:
        raise ModelError(f"Unused trainable parameters: {sorted(unused)}")
    # L-BFGS-B uses numerical derivatives; reject known nonsmooth expressions.
    if any(isinstance(n, ast.Call) and n.func.id in {"abs", "min", "max", "NORM", "positive_part"} for n in ast.walk(tree)):
        raise ModelError("Statistical fitting backend requires smooth predictors")
    return tree


def observations(model, dataset):
    spec = model.observation
    columns = set(model.inputs) | {n for n in (spec.response, spec.censored, spec.threshold) if n}
    if any(set(row) != columns for row in dataset.rows):
        raise ModelError("Training columns must exactly match features and observation declarations")
    y = np.array([r[spec.response] for r in dataset.rows])
    if np.any(y < 0) or np.any(y != np.floor(y)) or np.any(y > 1e12):
        raise ModelError("Count responses must be nonnegative integers <= 1e12")
    censored = np.zeros(len(y), dtype=bool)
    threshold = np.zeros(len(y))
    if spec.kind == "right_censored":
        mask = np.array([r[spec.censored] for r in dataset.rows])
        threshold = np.array([r[spec.threshold] for r in dataset.rows])
        if np.any((mask != 0) & (mask != 1)):
            raise ModelError("Censoring indicator must be 0 or 1")
        if np.any(threshold < 0) or np.any(threshold != np.floor(threshold)) or np.any(threshold > 1e12):
            raise ModelError("Censor thresholds must be nonnegative integers <= 1e12")
        censored = mask.astype(bool)
        if np.any(y[censored] != threshold[censored]) or np.any(y[~censored] >= threshold[~censored]):
            raise ModelError("For Y=min(D,A), censored Y must equal A and exact Y must be below A")
    return y, censored, threshold


def log_likelihood(distribution, y, mu, censored, threshold, alpha=None):
    """Log survival uses threshold-1 because integer right censoring includes A."""
    mu = np.asarray(mu, dtype=float)
    if not np.all(np.isfinite(mu)) or np.any(mu <= 0):
        raise ModelError("Distribution mean must be finite and strictly positive")
    if distribution == "poisson":
        family, args = poisson, (mu,)
    elif distribution == "negative_binomial":
        if alpha is None or not math.isfinite(alpha) or alpha <= 0:
            raise ModelError("NB dispersion alpha must be finite and positive")
        family, args = nbinom, (1 / alpha, 1 / (1 + alpha * mu))
    else:
        raise ModelError("Unsupported distribution")
    exact = family.logpmf(y, *args)
    if np.any(censored):
        exact = np.where(censored, family.logsf(threshold - 1, *args), exact)
    if not np.all(np.isfinite(exact)):
        raise ModelError("Non-finite likelihood; check parameter scale and observations")
    return exact


def transformed_rows(model, rows, preprocessing):
    return [{name: finite_scalar((row[name] - preprocessing[name].center) / preprocessing[name].scale)
             for name in model.inputs} for row in rows]


def means(model, tree, rows, parameters):
    values = []
    for row in rows:
        eta = finite_scalar(evaluate(tree, Context(parameters | row, [])))
        try:
            mu = math.exp(eta) if model.link == "log" else eta
        except OverflowError as exc:
            raise ModelError("Log-link overflow") from exc
        if not math.isfinite(mu) or mu <= 0:
            raise ModelError("Mean must be finite and strictly positive")
        values.append(mu)
    return np.asarray(values)


def output_rows(model, mu, parameters):
    alpha = parameters[model.dispersion_parameter] if model.dispersion_parameter else 0
    if alpha < 0 or model.distribution == "negative_binomial" and alpha <= 0:
        raise ModelError("NB dispersion alpha must be positive")
    return [{"mean": finite_scalar(float(m)), "variance": finite_scalar(float(m + alpha * m * m))} for m in mu]


class FitTimeout(Exception):
    pass


class ScipyLikelihoodSolver:
    """Backend consumes a scalar objective, initial values, and bounds, not an LP matrix."""
    def solve(self, objective, initial, bounds, max_iterations):
        return minimize(objective, initial, method="L-BFGS-B", bounds=bounds,
                        options={"maxiter": max_iterations, "maxls": 40, "ftol": 1e-11, "gtol": 1e-6})


def fit(request, backend=None):
    start = perf_counter()
    model = request.model
    tree = compile_statistics(model)
    if set(request.parameters) != set(model.parameters):
        raise ModelError("Fixed parameters must exactly match declarations")
    y, censored, threshold = observations(model, request.dataset)
    if np.all(censored):
        raise ModelError("This fitting backend requires at least one exact observation")
    preprocessing = {}
    for name in model.inputs:
        values = np.asarray([r[name] for r in request.dataset.rows])
        center, scale = (float(values.mean()), float(values.std())) if name in model.standardize else (0., 1.)
        if not math.isfinite(center) or not math.isfinite(scale):
            raise ModelError("Feature scale exceeds numeric range")
        preprocessing[name] = FeatureTransform(center=center, scale=scale if scale > 0 else 1.)
    rows = transformed_rows(model, request.dataset.rows, preprocessing)
    names = sorted(model.trainable)

    def encode_value(value, spec):
        return math.log(value) if value is not None and spec.transform == "log" else value

    initial = [encode_value(model.trainable[n].initial, model.trainable[n]) for n in names]
    bounds = [(encode_value(model.trainable[n].lower, model.trainable[n]),
               encode_value(model.trainable[n].upper, model.trainable[n])) for n in names]

    def decode(x):
        try:
            return {n: finite_scalar(math.exp(float(v)) if model.trainable[n].transform == "log" else float(v))
                    for n, v in zip(names, x)}
        except OverflowError as exc:
            raise ModelError("Parameter transform overflow") from exc

    def nll(x):
        if perf_counter() - start > request.solver.time_limit_seconds:
            raise FitTimeout()
        parameters = request.parameters | decode(x)
        mu = means(model, tree, rows, parameters)
        return finite_scalar(float(-log_likelihood(model.distribution, y, mu, censored, threshold,
                                                   parameters.get(model.dispersion_parameter)).sum()))

    # Invalid starting values are schema/domain errors, not optimizer failures.
    try:
        nll(initial)
    except FitTimeout:
        return ExecutionResult(model_id=model.model_id, model_version=model.version, status="failed",
                               row_ids=request.dataset.row_ids, diagnostics={"reason": "fit_timeout"})

    def objective(x):
        try:
            return nll(x) / len(y)
        except ModelError:
            return 1e100  # finite rejection penalty; final point must pass strict evaluation

    try:
        solved = (backend or ScipyLikelihoodSolver()).solve(objective, initial, bounds, model.max_iterations)
        value = nll(solved.x)
    except FitTimeout:
        return ExecutionResult(model_id=model.model_id, model_version=model.version, status="failed",
                               row_ids=request.dataset.row_ids, diagnostics={"reason": "fit_timeout"})
    except ModelError as exc:
        return ExecutionResult(model_id=model.model_id, model_version=model.version, status="failed",
                               row_ids=request.dataset.row_ids, diagnostics={"reason": str(exc)})
    diagnostics = {"backend": "scipy.optimize.minimize/L-BFGS-B", "iterations": int(solved.nit),
                   "converged": bool(solved.success), "message": str(solved.message),
                   "elapsed_seconds": perf_counter() - start, "censored_rows": int(censored.sum()),
                   "global_optimum_guaranteed": False, "identifiability_verified": False}
    if not solved.success:
        return ExecutionResult(model_id=model.model_id, model_version=model.version, status="failed",
                               row_ids=request.dataset.row_ids, diagnostics=diagnostics)
    fitted = decode(solved.x)
    diagnostics["parameters_at_bounds"] = [n for n in names if any(
        b is not None and math.isclose(fitted[n], b, rel_tol=1e-5, abs_tol=1e-7)
        for b in (model.trainable[n].lower, model.trainable[n].upper))]
    body = json.dumps(request.dataset.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False)
    artifact = FittedArtifact(model=model, fitted_parameters=fitted, fixed_parameters=request.parameters,
                              preprocessing=preprocessing, training_checksum=hashlib.sha256(body.encode()).hexdigest(),
                              training_rows=len(y), backend=f"scipy/{scipy.__version__}/L-BFGS-B",
                              negative_log_likelihood=value)
    parameters = request.parameters | fitted
    return ExecutionResult(model_id=model.model_id, model_version=model.version, status="succeeded",
                           row_ids=request.dataset.row_ids, outputs=output_rows(model, means(model, tree, rows, parameters), parameters),
                           solution=fitted, objective=value, diagnostics=diagnostics, fitted_artifact=artifact)


def predict(request):
    artifact, dataset = request.artifact, request.dataset
    model = artifact.model
    tree = compile_statistics(model)
    if set(artifact.fitted_parameters) != set(model.trainable) or set(artifact.fixed_parameters) != set(model.parameters):
        raise ModelError("Artifact parameters do not match its model")
    if set(artifact.preprocessing) != set(model.inputs) or any(set(r) != set(model.inputs) for r in dataset.rows):
        raise ModelError("Prediction requires exactly the fitted feature schema")
    for name, spec in model.trainable.items():
        value = artifact.fitted_parameters[name]
        if spec.lower is not None and value < spec.lower or spec.upper is not None and value > spec.upper or spec.transform == "log" and value <= 0:
            raise ModelError("Artifact parameter violates model domain")
    for name, transform in artifact.preprocessing.items():
        if name not in model.standardize and (transform.center != 0 or transform.scale != 1):
            raise ModelError("Artifact preprocessing does not match model declarations")
    parameters = artifact.fixed_parameters | artifact.fitted_parameters
    rows = transformed_rows(model, dataset.rows, artifact.preprocessing)
    return ExecutionResult(model_id=model.model_id, model_version=model.version, status="succeeded", row_ids=dataset.row_ids,
                           outputs=output_rows(model, means(model, tree, rows, parameters), parameters),
                           diagnostics={"operation": "prediction", "training_checksum": artifact.training_checksum})
