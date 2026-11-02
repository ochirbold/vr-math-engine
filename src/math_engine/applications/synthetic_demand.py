"""Reproducible synthetic experiment. Truth is never included in engine inputs."""
from datetime import date, timedelta
import math
import numpy as np

from .demand import DemandPilotRequest


def generate(seed=20261027):
    rng = np.random.default_rng(seed)
    start = date(2024, 1, 1)
    history, future, truth = [], [], []
    coefficients = {"intercept": math.log(14), "log_price": -1.1, "promotion": .65,
                    "season_sin": .4, "season_cos": -.25, "dispersion": .35}
    for i in range(545):
        day = start + timedelta(days=i)
        promo = int(rng.random() < .22)
        price = round(float(rng.uniform(80, 130)), 2)
        angle = 2 * math.pi * i / 365.25
        mean = math.exp(coefficients["intercept"] + coefficients["log_price"] * math.log(price / 100)
                        + coefficients["promotion"] * promo + coefficients["season_sin"] * math.sin(angle)
                        + coefficients["season_cos"] * math.cos(angle))
        latent = int(rng.negative_binomial(1 / coefficients["dispersion"],
                                         1 / (1 + coefficients["dispersion"] * mean)))
        plan = {"date": day.isoformat(), "price": price, "promotion": promo}
        if i < 455:
            # Exogenous capacity, including fully uninformative zero-stock days.
            available = int(rng.choice([0, 10, 18, 30, 50], p=[.025, .2, .3, .3, .175]))
            history.append(plan | {"sales": min(latent, available), "available": available,
                                   "censored": int(latent >= available)})
        else:
            future.append(plan)
        truth.append({"date": day.isoformat(), "latent_demand": latent, "true_mean": mean})
    request = DemandPilotRequest.model_validate({"sku": "SYNTHETIC-SKU-001", "branch": "SYNTHETIC-BRANCH-001",
                                                 "train_end": (start + timedelta(days=364)).isoformat(),
                                                 "history": history, "future": future})
    return request, {"synthetic": True, "seed": seed, "coefficients": coefficients, "rows": truth}


def evaluate_truth(report, truth):
    lookup = {r["date"]: r for r in truth["rows"]}

    def errors(predictions):
        actual = np.array([lookup[p["date"]]["latent_demand"] for p in predictions])
        true_mean = np.array([lookup[p["date"]]["true_mean"] for p in predictions])
        predicted = np.array([p["mean"] for p in predictions])
        denominator = float(actual.sum())
        return {"latent_mae": float(np.abs(actual - predicted).mean()),
                "latent_rmse": float(np.sqrt(np.mean((actual - predicted) ** 2))),
                "latent_wape": float(np.abs(actual - predicted).sum() / denominator) if denominator > 0 else None,
                "true_mean_mae": float(np.abs(true_mean - predicted).mean())}

    return {"synthetic": True, "seed": truth["seed"],
            "note": "Truth is available only in this simulation and is not used for training or model selection",
            "holdout": errors(report["evaluation"]["predictions"]),
            "baseline_holdout": errors(report["evaluation"]["baseline_predictions"]),
            "future": errors(report["forecast"]["daily"]),
            "horizons": [{"days": h["days"], "predicted_mean_sum": h["expected_demand"],
                          "true_mean_sum": sum(lookup[p["date"]]["true_mean"] for p in report["forecast"]["daily"][:h["days"]]),
                          "realized_latent_sum": sum(lookup[p["date"]]["latent_demand"] for p in report["forecast"]["daily"][:h["days"]])}
                         for h in report["forecast"]["horizons"]]}
