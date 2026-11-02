"""Run a single SKU/branch pilot; synthetic by default, no database connection."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from math_engine.applications.demand import DemandPilotRequest, dataset, run_pilot
from math_engine.applications.synthetic_demand import evaluate_truth, generate


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def markdown(report):
    ev, forecast = report["evaluation"], report["forecast"]
    lines = ["# Нэг SKU × салбарын demand forecast туршилт", "",
             "**Зохиомол өгөгдлийн туршилт. Production чанарын баталгаа биш.**" if report.get("synthetic_evaluation") else "Хэрэглэгчийн өгсөн өгөгдлийн туршилт.", "",
             f"SKU: `{report['sku']}`; салбар: `{report['branch']}`.", "",
             f"Training: {ev['train_start']} → {ev['train_end']} ({ev['training_rows']} өдөр).",
             f"Holdout: {ev['test_start']} → {ev['test_end']} ({ev['test_rows']} өдөр).", "",
             "Holdout-д training-only artifact хэрэглэсэн. Ирээдүйн прогнозын artifact-ийг бүх history дээр тусад нь дахин сургасан.", "",
             "## Holdout үнэлгээ", "", "| Хэмжүүр | Feature NB | Intercept-only censored NB |", "|---|---:|---:|"]
    for key, label in [("observation_nll_mean", "Censoring тооцсон дундаж NLL ↓"),
                       ("exact_subset_mae", "Зөвхөн uncensored дэд олонлогийн MAE ↓")]:
        a, b = ev["metrics"][key], ev["baseline_metrics"][key]
        lines.append(f"| {label} | {a:.4f} | {b:.4f} |" if a is not None and b is not None else f"| {label} | unavailable | unavailable |")
    lines += ["", f"Holdout censor мөр: {ev['metrics']['censored_rows']}; zero-capacity мөр: {ev['metrics']['zero_capacity_rows']}.",
              "Uncensored MAE нь сонгогдсон дэд олонлогийн хэмжүүр; бүх latent demand-ийн алдаа гэж тайлбарлахгүй.", ""]
    synthetic = report.get("synthetic_evaluation")
    if synthetic:
        lines += ["## Зөвхөн simulation-д мэдэгдэх бодит эрэлттэй харьцуулалт", "",
                  "| Holdout хэмжүүр | Feature NB | Baseline |", "|---|---:|---:|"]
        for key in ("latent_mae", "latent_rmse", "true_mean_mae"):
            lines.append(f"| {key} | {synthetic['holdout'][key]:.4f} | {synthetic['baseline_holdout'][key]:.4f} |")
        lines += ["", "Нуугдмал бодит эрэлт ба үүсгэгчийн mean-ийг fit-д өгөөгүй. Test-ээр загвар сонгоогүй.", ""]
    lines += ["## Ирээдүйн прогноз", "", f"Forecast origin: {forecast['origin']}. Ирээдүйн үнэ/урамшууллын өгөгдсөн хувилбарт нөхцөлдсөн.", "",
              "| Хоног | Эхлэх | Дуусах | Хүлээгдэж буй эрэлтийн нийлбэр |", "|---:|---|---|---:|"]
    for h in forecast["horizons"]:
        lines.append(f"| {h['days']} | {h['start']} | {h['end']} | {h['expected_demand']:.2f} |")
    if synthetic:
        lines += ["", "| Хоног | Прогнозын нийлбэр | Үүсгэгчийн true mean нийлбэр | Simulation бодит demand |", "|---:|---:|---:|---:|"]
        for h in synthetic["horizons"]:
            lines.append(f"| {h['days']} | {h['predicted_mean_sum']:.2f} | {h['true_mean_sum']:.2f} | {h['realized_latent_sum']} |")
    lines += ["", "## Хязгаар", "", "- Нэг SKU/салбар; shared болон hierarchical параметр сурахгүй.",
              "- Global optimum болон параметрийн identifiable байдлыг батлахгүй.",
              "- Жилийн нэг Fourier хос, үнэ, урамшууллын feature хэрэглэсэн; бодит seasonality өөр байж болно.",
              "- Daily mean-үүдийг нийлбэрлэсэн; prediction interval гаргаагүй.",
              "- Oracle болон хуучин төслийн өгөгдөлд хандаагүй.", "",
              "Дэлгэрэнгүй үр дүн: `report.json`; оролт: `request.json`; artifact: `evaluation-artifact.json`, `forecast-artifact.json`.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="DemandPilotRequest JSON; omit for synthetic experiment")
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--output", type=Path, default=ROOT / "var" / ("demand-pilot-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    args = parser.parse_args()
    if args.input:
        request, truth = DemandPilotRequest.model_validate_json(args.input.read_text(encoding="utf-8")), None
    else:
        request, truth = generate(args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "request.json", request.model_dump(mode="json"))
    if truth:
        write_json(args.output / "synthetic-truth.json", truth)
    report = run_pilot(request)
    if truth:
        report["synthetic_evaluation"] = evaluate_truth(report, truth)
    write_json(args.output / "report.json", report)
    write_json(args.output / "evaluation-artifact.json", report["evaluation"]["artifact"])
    write_json(args.output / "forecast-artifact.json", report["forecast"]["artifact"])
    write_json(args.output / "prediction-request.json", {"artifact": report["forecast"]["artifact"],
                                                        "dataset": dataset(request.future).model_dump()})
    (args.output / "report.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "test_metrics": report["evaluation"]["metrics"],
                      "baseline_metrics": report["evaluation"]["baseline_metrics"],
                      "forecast": report["forecast"]["horizons"]}, indent=2))


if __name__ == "__main__":
    main()
