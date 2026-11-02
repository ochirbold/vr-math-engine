"""Reusable finite probability measures and explicit independent sampling."""
import numpy as np
import math
from .expressions import ModelError, finite_scalar


DISTRIBUTION_ARGUMENTS = {"poisson": {"mean"}, "negative_binomial": {"mean", "dispersion"},
                          "normal": {"mean", "stddev"}, "uniform": {"lower", "upper"}}


def expected_capped_count(distribution, mean, cap, dispersion=None):
    """E[min(X,cap)] for a nonnegative count, including fractional caps.

Uses truncated first-moment identities and a survival function; it neither
clips the mean nor truncates an infinite probability sum numerically.
NB2 uses Var(X)=mean+dispersion*mean**2. No application-domain meaning here.
"""
    from scipy.stats import nbinom, poisson
    mean, cap = finite_scalar(mean), finite_scalar(cap)
    if mean < 0 or not 0 <= cap <= 1e12:
        raise ModelError("Capped count requires mean >= 0 and cap in [0, 1e12]")
    if distribution == "negative_binomial":
        if dispersion is None or finite_scalar(dispersion) <= 0:
            raise ModelError("NB dispersion must be positive")
        r = 1. / dispersion
        p = 1. / (1. + dispersion * mean)
        if not math.isfinite(r) or not math.isfinite(p) or p <= 0 or mean > 0 and p >= 1:
            raise ModelError("NB parameters outside supported numerical range")
    elif distribution != "poisson":
        raise ModelError("Unsupported capped count distribution")
    if cap == 0 or mean == 0:
        return 0.
    n = math.floor(cap)
    if distribution == "poisson":
        value = mean * poisson.cdf(n-1, mean) + cap * poisson.sf(n, mean)
    else:
        value = mean * nbinom.cdf(n-1, r+1, p) + cap * nbinom.sf(n, r, p)
    value = finite_scalar(float(value))
    upper = min(mean, cap)
    if value < -1e-9 or value > upper + 1e-9 * max(1., upper):
        raise ModelError("Capped expectation failed numerical bounds validation")
    return max(0., min(value, upper))


class FiniteMeasure:
    def __init__(self, weights):
        w = np.asarray(weights, dtype=float)
        if w.ndim != 1 or not len(w) or not np.isfinite(w).all() or (w < 0).any() or not (w > 0).any():
            raise ModelError("Scenario weights must be finite, nonnegative, with positive total mass")
        # Scale first to avoid overflow when legitimate raw weights are large.
        scaled = w / w.max()
        self.weights = scaled / scaled.sum()

    def reduce(self, values, operation, probability=None):
        x = np.asarray(values, dtype=float)
        if x.shape != self.weights.shape or not np.isfinite(x).all():
            raise ModelError("Reduction requires one finite scalar per scenario")
        active = self.weights > 0
        x, w = x[active], self.weights[active]
        with np.errstate(over="ignore", invalid="ignore"):
            if operation == "expectation":
                value = np.dot(w, x)
            elif operation == "variance":
                mean = np.dot(w, x)
                value = np.dot(w, (x - mean) ** 2)
            elif operation == "quantile":
                if probability is None or not 0 <= probability <= 1:
                    raise ModelError("Quantile probability must be in [0, 1]")
                order = np.argsort(x, kind="stable")
                cumulative = np.cumsum(w[order])
                cumulative[-1] = 1.
                index = min(int(np.searchsorted(cumulative, probability, side="left")), len(x)-1)
                value = x[order[index]]
            else:
                raise ModelError("Unsupported probability reduction")
        return finite_scalar(float(value))


def draw(distribution, arguments, count, rng):
    if set(arguments) != DISTRIBUTION_ARGUMENTS.get(distribution):
        raise ModelError(f"Invalid arguments for distribution {distribution}")
    args = {k: finite_scalar(v) for k, v in arguments.items()}
    try:
        if distribution == "poisson":
            if args["mean"] < 0:
                raise ModelError("Poisson mean must be nonnegative")
            values = rng.poisson(args["mean"], count)
        elif distribution == "negative_binomial":
            mu, alpha = args["mean"], args["dispersion"]
            if mu <= 0 or alpha <= 0:
                raise ModelError("Negative Binomial mean and dispersion must be positive")
            values = rng.negative_binomial(1 / alpha, 1 / (1 + alpha * mu), count)
        elif distribution == "normal":
            if args["stddev"] <= 0:
                raise ModelError("Normal stddev must be positive")
            values = rng.normal(args["mean"], args["stddev"], count)
        else:
            if args["lower"] >= args["upper"]:
                raise ModelError("Uniform lower must be less than upper")
            values = rng.uniform(args["lower"], args["upper"], count)
    except (ValueError, OverflowError) as exc:
        raise ModelError(f"Sampling domain error: {exc}") from exc
    if not np.isfinite(values).all():
        raise ModelError("Sampling produced non-finite values")
    return values.astype(float)
