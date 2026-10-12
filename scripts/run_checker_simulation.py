#!/usr/bin/env python3
"""Listen to every generated chunk with a Hindi ASR model and compare it."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.qa.checker_simulator import FasterWhisperRecognizer, run_checker_simulation, select_risk_sample


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--model", default="tiny", help="faster-whisper model; tiny is the fast default")
    parser.add_argument("--min-coverage", type=float, default=0.90)
    parser.add_argument("--sample-percent", type=float, default=10.0)
    parser.add_argument("--max-chunks", type=int, default=24)
    parser.add_argument("--all", action="store_true", help="transcribe every chunk; slow release audit")
    args = parser.parse_args()
    try:
        recognizer = FasterWhisperRecognizer(args.model)
    except RuntimeError as exc:
        target = Path(args.project) / "07_qa" / "checker_simulation.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        report = {"version": 1, "project": Path(args.project).name,
                  "status": "not_evaluated", "model": args.model,
                  "summary": {"chunks": 0, "blockers": 0, "warnings": 0, "sample": not args.all},
                  "findings": [{"severity": "review", "code": "recognition_not_evaluated",
                                "message": str(exc)}], "chunks": []}
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("NOT_EVALUATED: " + str(exc))
        return 0
    items = None if args.all else select_risk_sample(args.project, sample_percent=args.sample_percent,
                                                      max_chunks=args.max_chunks)
    if items is not None:
        print(f"Selected {len(items)} risk-sample chunks from the full audiobook.", flush=True)
    report = run_checker_simulation(args.project, recognizer, min_coverage=args.min_coverage, items=items,
                                    model_settings={"backend": "faster-whisper", "model": args.model,
                                                     "language": "hi", "device": "cpu", "compute_type": "int8"})
    print(json.dumps(report["summary"], ensure_ascii=False))
    for finding in report["findings"][:40]:
        print(f"{finding['severity'].upper()} {finding['code']}: {finding['message']} "
              f"{finding.get('chunk_id', '')} page={finding.get('page', '')}")
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
