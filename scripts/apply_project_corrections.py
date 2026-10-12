"""Apply approved source corrections to an existing segmented project.

This is useful for legacy projects that retain stage-1 segments but no longer
have the original OCR checkpoint. It preserves segment IDs and writes a
recoverable sibling backup before updating the active segments artifact.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.corrections import apply_source_corrections, load_corrections, remove_segments


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    args = parser.parse_args()
    root = Path(args.project)
    path = root / "01_segments" / "segments.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    corrections = load_corrections(str(root))
    corrected = apply_source_corrections(data, corrections)
    corrected = remove_segments(corrected, corrections)
    backup = path.with_suffix(".pre_corrections.json")
    shutil.copyfile(path, backup)
    path.write_text(json.dumps(corrected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"segments_before": len(data), "segments_after": len(corrected),
                      "backup": str(backup), "output": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
