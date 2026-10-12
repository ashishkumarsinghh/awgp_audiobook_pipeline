#!/usr/bin/env python3
"""Run deterministic Checker-style QA for an audiobook project."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.qa.audio_qa import run_audio_qa


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    args = parser.parse_args()
    report = run_audio_qa(args.project)
    print(json.dumps(report["summary"], ensure_ascii=False))
    for finding in report["findings"][:20]:
        print(f"{finding['severity'].upper()} {finding['code']}: {finding['message']} "
              f"{finding.get('chunk_id', '')} page={finding.get('page', '')}")
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
