"""Checker-style automated QA for a generated audiobook.

This stage deliberately separates deterministic checks from optional ASR.  It
can therefore run in CI without a model, while leaving precise chunk/time
locations for a human checker when a perceptual model is not installed.
"""
import json
import hashlib
import math
import statistics
import wave
from array import array
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.core.corrections import corrections_for, load_corrections, is_approved
from src.synthesis.audio.io import validate_mp3, validate_wav


def _finding(code: str, severity: str, message: str, **context: Any) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **context}


def _word_count(text: str) -> int:
    return len([word for word in (text or "").split() if word.strip()])


def _audio_metrics(path: Path) -> Dict[str, float]:
    with wave.open(str(path), "rb") as audio:
        frames = audio.readframes(audio.getnframes())
        samples = array("h", frames)
    if not samples:
        return {"peak": 0.0, "rms": 0.0, "silence_ratio": 1.0, "clipped_ratio": 0.0}
    peak = max(abs(sample) for sample in samples) / 32768.0
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
    silence = sum(abs(sample) < 164 for sample in samples) / len(samples)
    clipped = sum(abs(sample) >= 32700 for sample in samples) / len(samples)
    return {
        "peak": round(peak, 6),
        "rms": round(rms, 6),
        "silence_ratio": round(silence, 6),
        "clipped_ratio": round(clipped, 6),
    }


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def run_audio_qa(project_dir: str, *, report_path: str | None = None) -> Dict[str, Any]:
    root = Path(project_dir)
    segments_path = root / "01_segments" / "segments.json"
    phonetics_path = root / "02_phonetics" / "phonetics.json"
    manifest_path = root / "05_audio_chunks" / "manifest.json"
    audio_dir = root / "05_audio_chunks"
    master_path = root / "04_master" / f"{root.name}.mp3"

    segments = _load_json(segments_path, [])
    phonetics = _load_json(phonetics_path, [])
    manifest = _load_json(manifest_path, {})
    chunks = manifest.get("chunks", {}) if isinstance(manifest, dict) else {}
    corrections = load_corrections(str(root))
    findings: List[Dict[str, Any]] = []
    chunk_reports: List[Dict[str, Any]] = []

    if not segments:
        findings.append(_finding("segments_missing", "blocker", "No segment artifact found."))
    if len(segments) != len(phonetics):
        findings.append(_finding("stage_count_mismatch", "blocker", "Segments and phonetics counts differ.",
                                 segments=len(segments), phonetics=len(phonetics)))
    if len(segments) != len(chunks):
        findings.append(_finding("audio_count_mismatch", "blocker", "Phonetics and audio manifest counts differ.",
                                 phonetics=len(phonetics), audio=len(chunks)))

    for index, (source, speech) in enumerate(zip(segments, phonetics)):
        chunk_id = source.get("id")
        location = {"chunk_id": chunk_id, "page": source.get("page"), "paragraph": source.get("paragraph")}
        if source.get("source_text") != speech.get("source_text"):
            findings.append(_finding("source_drift", "blocker", "Phonetics changed source text.", **location))
        if source.get("page") is None or source.get("paragraph") is None:
            findings.append(_finding("missing_provenance", "blocker", "Chunk has no page/paragraph provenance.", **location))
        if "[???????]" in source.get("source_text", ""):
            findings.append(_finding("unresolved_ocr", "blocker", "Chunk contains unresolved OCR.", **location))
        manifest_record = chunks.get(chunk_id, {})
        if manifest_record.get("source_text_sha256") and manifest_record["source_text_sha256"] != hashlib.sha256(source.get("source_text", "").encode("utf-8")).hexdigest():
            findings.append(_finding("manifest_source_drift", "blocker", "Audio manifest is for different source text.", **location))

    offsets = _load_json(root / "04_master" / "offsets.json", {})
    offset_items = offsets.get("offsets", []) if isinstance(offsets, dict) else []
    if offset_items and [item.get("chunk_id") for item in offset_items] != [item.get("id") for item in segments]:
        findings.append(_finding("timeline_order_mismatch", "blocker", "Master playback offsets do not match segment order."))

    for rule in corrections_for("phonetics", corrections):
        needle = rule.get("find") or rule.get("find_text")
        replacement = rule.get("replace") or rule.get("tts_override")
        if not needle or replacement is None:
            continue
        for item in phonetics:
            if needle in item.get("source_text", "") and replacement not in item.get("pronunciation_text", ""):
                findings.append(_finding("pronunciation_contract", "blocker",
                                         f"Required pronunciation fix is missing for {needle}.",
                                         chunk_id=item.get("id"), page=item.get("page"),
                                         paragraph=item.get("paragraph"), source=needle))

    for rule in corrections.get("corrections", []):
        if rule.get("stage") == "segment" and not is_approved(rule):
            findings.append(_finding(
                "unapproved_editorial_change", "warning",
                "A proposed editorial segment change is not delivery-approved; verify that the current artifact was not built from it.",
                requested_change=rule.get("find") or rule.get("find_text"),
                reason=rule.get("reason", ""),
            ))

    speeds: List[float] = []
    for item in phonetics:
        chunk_id = item.get("id")
        record = chunks.get(chunk_id, {})
        path = audio_dir / f"{chunk_id}.wav"
        location = {"chunk_id": chunk_id, "page": item.get("page"), "paragraph": item.get("paragraph")}
        if record.get("status") != "complete":
            findings.append(_finding("audio_incomplete", "blocker", "Audio manifest entry is not complete.", **location))
            continue
        try:
            duration = validate_wav(path)
            metrics = _audio_metrics(path)
        except (OSError, ValueError) as exc:
            findings.append(_finding("audio_invalid", "blocker", str(exc), **location))
            continue
        words = _word_count(item.get("source_text", ""))
        wpm = round(words / duration * 60, 1) if duration else 0.0
        if wpm:
            speeds.append(wpm)
        if metrics["clipped_ratio"] > 0.001:
            findings.append(_finding("clipping", "blocker", "Chunk contains clipped samples.", **location,
                                     clipped_ratio=metrics["clipped_ratio"]))
        # Short headings and fragments legitimately contain long structural
        # pauses; do not classify them as bad narration from silence alone.
        if words >= 8 and metrics["silence_ratio"] > 0.65:
            findings.append(_finding("excessive_silence", "warning", "Chunk is mostly digital silence.", **location,
                                     silence_ratio=metrics["silence_ratio"]))
        # WPM is meaningful only across a sufficiently long speech sample.
        # For short chunks the neural voice's lead-in/outro dominates timing.
        if words >= 12 and wpm and (wpm < 90 or wpm > 200):
            findings.append(_finding("pace_outlier", "warning", "Chunk speech rate is outside the QA envelope.", **location,
                                     measured_wpm=wpm))
        chunk_reports.append({**location, "duration_seconds": round(duration, 3), "word_count": words,
                              "measured_wpm": wpm, **metrics})

    if speeds:
        median = statistics.median(speeds)
        if median < 110 or median > 180:
            findings.append(_finding("book_pace", "warning", "Book median speech rate is outside the QA envelope.",
                                     median_wpm=round(median, 1)))

    try:
        validate_mp3(master_path)
    except ValueError as exc:
        findings.append(_finding("master_invalid", "blocker", str(exc), path=str(master_path)))

    blockers = sum(item["severity"] == "blocker" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    report = {
        "version": 1,
        "project": root.name,
        "status": "fail" if blockers else ("review" if warnings else "pass"),
        "summary": {"segments": len(segments), "phonetics": len(phonetics), "audio_chunks": len(chunks),
                     "blockers": blockers, "warnings": warnings},
        "findings": findings,
        "chunks": chunk_reports,
        "asr": {"status": "not_run", "reason": "No ASR adapter was requested by this deterministic run."},
    }
    target = Path(report_path) if report_path else root / "07_qa" / "report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
