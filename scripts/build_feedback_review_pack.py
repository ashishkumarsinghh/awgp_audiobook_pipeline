#!/usr/bin/env python3
"""Build a small, labelled listening pack from timestamped checker feedback."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import json as _json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.qa.roman_feedback import resolve_phrase

MANUAL_CHUNK_OVERRIDES = {
    "Rajnagaro mein pahuch": "chunk_0013",
    "gali gali": "chunk_0013",
    "swayam he": "chunk_0018",
    "dubla patla": "chunk_0023",
    "b shunya a shunya": "chunk_0025",
}


def seconds(value):
    parts = [int(x) for x in value.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--feedback", default="benchmarks/feedback/AIH_HINR0791_V1.json")
    parser.add_argument("--window", type=float, default=8.0)
    parser.add_argument("--output", default=None)
    parser.add_argument("--reference-project", default=None,
                        help="Prior version containing the timeline used by the checker timestamps")
    args = parser.parse_args()

    root = Path(args.project)
    master = root / "04_master" / f"{root.name}.mp3"
    feedback = json.loads(Path(args.feedback).read_text(encoding="utf-8"))
    reference_root = Path(args.reference_project) if args.reference_project else root.parent / "HINR0791_MAN_SADHE_JIVAN_SADHEI_Re2014"
    reference_offsets_path = reference_root / "04_master" / "offsets.json"
    target_offsets_path = root / "04_master" / "offsets.json"
    reference_offsets = json.loads(reference_offsets_path.read_text(encoding="utf-8")).get("offsets", []) if reference_offsets_path.is_file() else []
    target_offsets = {x["chunk_id"]: x for x in json.loads(target_offsets_path.read_text(encoding="utf-8")).get("offsets", [])} if target_offsets_path.is_file() else {}
    source_items = _json.loads((root / "01_segments" / "segments.json").read_text(encoding="utf-8"))
    source_by_id = {x["id"]: x for x in source_items}
    target = Path(args.output) if args.output else root / "07_qa" / "feedback_review_pack"
    target.mkdir(parents=True, exist_ok=True)
    entries = []
    for item in feedback.get("entries", []):
        timestamp = item.get("timestamp")
        if not timestamp:
            continue
        issue_id = item["issue_id"]
        original_time = seconds(timestamp)
        reference_chunk = next((x for x in reference_offsets
                                if x["start_seconds"] <= original_time <= x["end_seconds"]), None)
        target_chunk = target_offsets.get(reference_chunk.get("chunk_id")) if reference_chunk else None
        override_id = MANUAL_CHUNK_OVERRIDES.get(item.get("reviewer_text"))
        if override_id and override_id in target_offsets:
            target_chunk = target_offsets[override_id]
            reference_chunk = {"chunk_id": override_id, "start_seconds": original_time}
            within = 0.0
            start = max(0.0, target_chunk["start_seconds"] - 1.0)
            duration = target_chunk["end_seconds"] - target_chunk["start_seconds"] + 2.0
            mapping = {"reference_chunk_id": override_id,
                       "target_chunk_id": override_id,
                       "mapping": "verified_source_chunk_override",
                       "clip_contains_full_segment": True}
        elif target_chunk:
            # Preserve the within-segment position while moving from the
            # checker timeline to the new voice/master timeline.
            within = original_time - reference_chunk["start_seconds"]
            center = target_chunk["start_seconds"] + within
            # The entire target segment is the safe review unit.  The old
            # timestamp identifies a region, but voice speed changes make a
            # guessed word offset unreliable.
            start = max(0.0, target_chunk["start_seconds"] - 1.0)
            duration = target_chunk["end_seconds"] - target_chunk["start_seconds"] + 2.0
            mapping = {"reference_chunk_id": reference_chunk["chunk_id"],
                       "target_chunk_id": target_chunk["chunk_id"],
                       "mapping": "stable_segment_full_segment"}
        else:
            start = max(0.0, original_time - args.window)
            duration = args.window * 2
            mapping = {"mapping": "raw_timestamp_fallback"}
        source_item = source_by_id.get(mapping.get("target_chunk_id"))
        source_match = resolve_phrase(item.get("reviewer_text", ""), source_item.get("source_text", "")) if source_item else None
        clip = target / f"{issue_id}.mp3"
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", str(start),
            "-i", str(master), "-t", str(duration), "-c:a", "libmp3lame", "-b:a", "128k", str(clip)
        ], check=True)
        entries.append({**item, **mapping, "source_match": source_match,
                        "clip": str(clip), "clip_start_seconds": round(start, 2),
                        "clip_end_seconds": round(start + duration, 2),
                        "master": str(master)})

    manifest = {"version": 1, "project": root.name, "window_seconds": args.window,
                "master": str(master), "entries": entries}
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    html = ["<!doctype html><meta charset='utf-8'><title>Feedback review pack</title>",
            f"<h1>{root.name}</h1><p>Review {len(entries)} targeted clips; each is ±{args.window:g}s around the checker timestamp.</p><ol>"]
    for item in entries:
        match = item.get("source_match") or {}
        matched = match.get("sentence", "No source sentence match")
        score = match.get("score", 0)
        html.append(
            f"<li><b>{item['issue_id']}</b> — {item.get('category','')} — page {item.get('page','')} — "
            f"{item['timestamp']} — {item.get('reviewer_text','')}<br>"
            f"<small>Source match ({score:.2f}): {matched}</small><br>"
            f"<audio controls preload='none' src='{Path(item['clip']).name}'></audio></li>"
        )
    html.append("</ol>")
    (target / "index.html").write_text("\n".join(html), encoding="utf-8")
    print(json.dumps({"clips": len(entries), "directory": str(target), "index": str(target / 'index.html')}))


if __name__ == "__main__":
    main()
MANUAL_CHUNK_OVERRIDES = {
    # These first-pass anchors were verified against the actual Devanagari
    # source after the historical timestamps proved too coarse.
    "Rajnagaro mein pahuch": "chunk_0013",
    "gali gali": "chunk_0013",
    "swayam he": "chunk_0018",
    "dubla patla": "chunk_0023",
    "b shunya a shunya": "chunk_0025",
}
