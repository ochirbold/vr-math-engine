import argparse
import json
from pathlib import Path
from .contracts import ExecutionRequest, PredictionRequest
from .engine import execute
from .statistics import predict


def main():
    parser = argparse.ArgumentParser(description="Execute a versioned mathematical model without a database")
    parser.add_argument("request", type=Path)
    parser.add_argument("--predict", action="store_true", help="Read a PredictionRequest with an inline fitted artifact")
    args = parser.parse_args()
    text = args.request.read_text(encoding="utf-8")
    result = predict(PredictionRequest.model_validate_json(text)) if args.predict else execute(ExecutionRequest.model_validate_json(text))
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2, allow_nan=False))
    raise SystemExit(0 if result.status == "succeeded" else 2)


if __name__ == "__main__":
    main()
