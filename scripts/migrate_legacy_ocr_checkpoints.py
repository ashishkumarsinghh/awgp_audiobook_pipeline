"""Bind legacy page checkpoints to an exact PDF before a Stage 0 rebuild."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("checkpoint_dir", type=Path)
    parser.add_argument("book_name")
    args = parser.parse_args()

    digest = hashlib.sha256(Path(args.pdf).read_bytes()).hexdigest()
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", args.book_name)
    legacy = sorted(args.checkpoint_dir.glob(f"{safe}_page_*.txt"))
    if not legacy:
        raise SystemExit("No legacy checkpoints found.")
    migrated = 0
    for source in legacy:
        suffix = source.name[source.name.index("_page_"):]
        target = args.checkpoint_dir / f"{safe}_{digest[:20]}{suffix}"
        if not target.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        migrated += 1
    manifest = {
        "book_name": safe,
        "source_sha256": digest,
        "total_pages": migrated,
        "completed_pages": migrated,
        "pages": [int(p.stem.rsplit("_", 1)[-1]) for p in legacy],
        "migrated_from_legacy": True,
    }
    (args.checkpoint_dir / "ocr_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Bound {migrated} legacy checkpoints to {digest[:20]}.")


if __name__ == "__main__":
    main()
