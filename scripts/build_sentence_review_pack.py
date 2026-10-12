#!/usr/bin/env python3
"""Create exact-sentence feedback audition clips.

Unlike timestamp extraction, each optional clip is synthesized from the exact
source sentence selected by the romanized-feedback matcher.  It is labelled as
diagnostic audio and is never mistaken for proof about the existing master.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.types import SpeechSegment
from src.normalize.pronunciation import PronunciationDictionary
from src.qa.roman_feedback import resolve_phrase
from src.synthesis.providers import GoogleCloudTTSProvider


def sentences(text):
    return [x.strip() for x in re.split(r"(?<=[।॥!?])\s+|(?<=\.)\s+(?=[A-Z\u0900-\u097F])", text or "") if x.strip()]


def spoken_text(source, config):
    value = PronunciationDictionary("configs/improved_pronunciation.json").apply(source, context="prose")
    for rule in config.get("corrections", []):
        if rule.get("stage") != "phonetics" or rule.get("approved") is False:
            continue
        find = rule.get("find") or rule.get("find_text")
        replace = rule.get("replace") or rule.get("tts_override")
        if find and replace is not None:
            value = value.replace(find, replace)
    return value


async def synthesize(items, output, voice):
    provider = GoogleCloudTTSProvider(voice)
    output.mkdir(parents=True, exist_ok=True)
    for item in items:
        if item["status"] != "candidate":
            continue
        segment = SpeechSegment(
            source_text=item["source_sentence"], normalized_text=item["source_sentence"],
            pronunciation_text=item["spoken_sentence"], segment_type="review_sentence",
            rate="+0%", pitch="+0Hz", volume="+0%", pause_after_ms=300,
            page=item.get("page"), paragraph=item.get("paragraph"),
        )
        path = output / f"{item['issue_id']}.wav"
        await provider.synthesize(segment, str(path))
        item["diagnostic_audio"] = str(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--feedback", default="benchmarks/feedback/AIH_HINR0791_V1.json")
    parser.add_argument("--synthesize", action="store_true", help="Call Google Cloud TTS for approved-confidence candidates")
    parser.add_argument("--voice", default="hi-IN-Neural2-B")
    args = parser.parse_args()
    root = Path(args.project)
    feedback = json.loads(Path(args.feedback).read_text(encoding="utf-8"))
    segments = json.loads((root / "01_segments" / "segments.json").read_text(encoding="utf-8"))
    phonetics = {x["id"]: x for x in json.loads((root / "02_phonetics" / "phonetics.json").read_text(encoding="utf-8"))}
    config = json.loads(Path("configs/improved_pronunciation.json").read_text(encoding="utf-8"))
    config["corrections"] = json.loads((root / "project_corrections.json").read_text(encoding="utf-8")).get("corrections", [])
    entries = []
    for feedback_item in feedback.get("entries", []):
        note = feedback_item.get("reviewer_text", "")
        candidates = []
        for segment in segments:
            for sentence in sentences(segment.get("source_text", "")):
                match = resolve_phrase(note, sentence)
                if match:
                    candidates.append({**match, "segment": segment})
        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0] if candidates else None
        status = "candidate" if best and best["score"] >= 0.72 and feedback_item.get("timestamp") else "needs_human_selection"
        item = {**feedback_item, "status": status, "match_score": best["score"] if best else 0,
                "segment_id": best["segment"]["id"] if best else None,
                "page": best["segment"].get("page") if best else feedback_item.get("page"),
                "paragraph": best["segment"].get("paragraph") if best else None,
                "source_sentence": best["sentence"] if best else None,
                "spoken_sentence": spoken_text(best["sentence"], config) if best else None,
                "alternatives": [{"segment_id": x["segment"]["id"], "sentence": x["sentence"], "score": x["score"]}
                                for x in candidates[:3]]}
        entries.append(item)
    target = root / "07_qa" / "sentence_review_pack"
    target.mkdir(parents=True, exist_ok=True)
    if args.synthesize:
        asyncio.run(synthesize(entries, target / "audio", args.voice))
    report = {"version": 1, "project": root.name,
              "policy": "Diagnostic clips are synthesized from exact candidate sentences; master audio is not silently altered.",
              "entries": entries}
    (target / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html = ["<!doctype html><meta charset='utf-8'><title>Sentence review pack</title>",
            f"<h1>{root.name}</h1><p>Exact sentence candidates; unresolved matches require selection.</p><ol>"]
    for item in entries:
        audio = Path(item["diagnostic_audio"]).relative_to(target).as_posix() if item.get("diagnostic_audio") else ""
        html.append(f"<li><b>{item['issue_id']}</b> — {item.get('reviewer_text','')} — status: {item['status']} — score: {item['match_score']:.2f}<br>"
                    f"<span>Source: {item.get('source_sentence') or 'No confident match'}</span><br>"
                    f"<span>Spoken: {item.get('spoken_sentence') or 'Human selection required'}</span><br>"
                    + (f"<audio controls preload='none' src='{audio}'></audio>" if audio else "") + "</li>")
    html.append("</ol>")
    (target / "index.html").write_text("\n".join(html), encoding="utf-8")
    print(json.dumps({"entries": len(entries), "candidates": sum(x['status'] == 'candidate' for x in entries),
                      "needs_human_selection": sum(x['status'] != 'candidate' for x in entries),
                      "index": str(target / 'index.html')}))


if __name__ == "__main__":
    main()
