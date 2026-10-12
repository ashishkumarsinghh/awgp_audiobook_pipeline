"""ASR-backed Checker simulation.

The deterministic QA stage proves that artifacts are internally consistent.
This stage actually listens to the rendered WAVs through a Hindi-capable ASR
model and compares what was spoken with the source transcript.
"""
import json
import re
import random
import time
import unicodedata
import wave
import hashlib
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from src.core.corrections import corrections_for, load_corrections


DEVANAGARI_PUNCTUATION = re.compile(r"[।॥!?.,;:()\[\]{}\"'“”‘’—–-]")


def normalize_tokens(text: str) -> List[str]:
    value = unicodedata.normalize("NFC", text or "").casefold()
    value = DEVANAGARI_PUNCTUATION.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.split() if value else []


def _edit_distance(left: List[str], right: List[str]) -> int:
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        next_row = [i]
        for j, b in enumerate(right, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1,
                                row[j - 1] + (a != b)))
        row = next_row
    return row[-1]


def compare_transcript(expected: str, recognized: str) -> Dict[str, Any]:
    expected_tokens = normalize_tokens(expected)
    recognized_tokens = normalize_tokens(recognized)
    expected_devanagari = sum(bool(re.search(r"[\u0900-\u097F]", token)) for token in expected_tokens)
    recognized_devanagari = sum(bool(re.search(r"[\u0900-\u097F]", token)) for token in recognized_tokens)
    if expected_devanagari and recognized_tokens and recognized_devanagari == 0:
        ratio = len(recognized_tokens) / len(expected_tokens) if expected_tokens else 1.0
        return {
            "comparison_mode": "romanized_asr",
            "expected_words": len(expected_tokens),
            "recognized_words": len(recognized_tokens),
            "matched_words": None,
            "coverage": None,
            "word_count_ratio": round(ratio, 4),
            "omissions": [],
            "additions": [],
            "wer": None,
            "cer": None,
        }
    matcher = SequenceMatcher(a=expected_tokens, b=recognized_tokens, autojunk=False)
    omissions: List[str] = []
    additions: List[str] = []
    opcodes = matcher.get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag in ("delete", "replace"):
            omissions.extend(expected_tokens[i1:i2])
        if tag in ("insert", "replace"):
            additions.extend(recognized_tokens[j1:j2])
    matched = sum(block.size for block in matcher.get_matching_blocks())
    coverage = matched / len(expected_tokens) if expected_tokens else 1.0
    return {
        "expected_words": len(expected_tokens),
        "recognized_words": len(recognized_tokens),
        "matched_words": matched,
        "coverage": round(coverage, 4),
        "omissions": omissions,
        "additions": additions,
        "wer": round(_edit_distance(expected_tokens, recognized_tokens) / len(expected_tokens), 4)
        if expected_tokens else 0.0,
        "cer": round(_edit_distance(list(" ".join(expected_tokens)), list(" ".join(recognized_tokens))) /
                   max(1, len(" ".join(expected_tokens))), 4),
    }


class FasterWhisperRecognizer:
    def __init__(self, model_name: str = "small", device: str = "cpu", compute_type: str = "int8"):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "ASR simulation requires faster-whisper. Install it with "
                "'pip install faster-whisper'."
            ) from exc
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: str) -> Tuple[str, float]:
        # Pass PCM directly instead of a filename. This avoids PyAV version
        # differences in the audio decoder and keeps the QA path deterministic.
        import numpy as np
        with wave.open(audio_path, "rb") as audio:
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
            sample_rate = audio.getframerate()
        if sample_rate != 16000 and len(samples):
            target_length = max(1, round(len(samples) * 16000 / sample_rate))
            samples = np.interp(
                np.linspace(0, len(samples) - 1, target_length),
                np.arange(len(samples)),
                samples,
            ).astype(np.float32)
        segments, _ = self.model.transcribe(samples, language="hi", vad_filter=True,
                                             beam_size=5)
        parts = []
        confidence = []
        for segment in segments:
            parts.append(segment.text.strip())
            confidence.append(max(0.0, min(1.0, (segment.avg_logprob + 1.0))))
        return " ".join(parts), (sum(confidence) / len(confidence) if confidence else 0.0)


def select_risk_sample(project_dir: str, *, sample_percent: float = 10.0, max_chunks: int = 24,
                       seed: int = 20261002) -> List[Dict[str, Any]]:
    """Select a fast, reproducible listening sample.

    Always include chunks touched by pronunciation corrections, then fill with
    a seeded random sample so repeated runs are comparable.
    """
    root = Path(project_dir)
    segments_path = root / "01_segments" / "segments.json"
    segments = json.loads(segments_path.read_text(encoding="utf-8"))
    corrections = load_corrections(str(root))
    risky = []
    for item in segments:
        if any((rule.get("find") or rule.get("find_text")) in item.get("source_text", "")
               for rule in corrections_for("phonetics", corrections)):
            risky.append(item)
    selected_ids = {item["id"] for item in risky}
    target = min(max_chunks, max(len(risky), round(len(segments) * sample_percent / 100)))
    remaining = [item for item in segments if item["id"] not in selected_ids]
    random.Random(seed).shuffle(remaining)
    for item in remaining:
        if len(risky) >= target:
            break
        risky.append(item)
    return risky[:max_chunks]


def run_checker_simulation(project_dir: str, recognizer: Any, *, min_coverage: float = 0.90,
                           items: Optional[List[Dict[str, Any]]] = None,
                           progress: bool = True, cache_dir: Optional[str] = None,
                           model_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    root = Path(project_dir)
    segments_path = root / "01_segments" / "segments.json"
    segments = items if items is not None else json.loads(segments_path.read_text(encoding="utf-8"))
    audio_dir = root / "05_audio_chunks"
    findings: List[Dict[str, Any]] = []
    chunk_reports: List[Dict[str, Any]] = []
    cache_root = Path(cache_dir) if cache_dir else root / "07_qa" / "asr_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    settings_key = json.dumps(model_settings or {"recognizer": type(recognizer).__name__}, sort_keys=True)

    started = time.monotonic()
    total = len(segments)
    for index, item in enumerate(segments, 1):
        chunk_id = item["id"]
        audio_path = audio_dir / f"{chunk_id}.wav"
        digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()
        cache_key = hashlib.sha256((digest + settings_key).encode()).hexdigest()
        cache_path = cache_root / f"{cache_key}.json"
        cached = None
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if isinstance(cached, dict) and cached.get("audio_sha256") == digest:
            recognized, confidence = cached.get("recognized_text", ""), float(cached.get("confidence", 0.0))
            cache_status = "hit"
        else:
            recognized, confidence = recognizer.transcribe(str(audio_path))
            cache_path.write_text(json.dumps({"version": 1, "audio_sha256": digest,
                                               "settings": model_settings or {},
                                               "recognized_text": recognized,
                                               "confidence": confidence}, ensure_ascii=False, indent=2), encoding="utf-8")
            cache_status = "miss"
        elapsed = time.monotonic() - started
        if progress:
            rate = index / elapsed if elapsed else 0
            eta = (total - index) / rate if rate else 0
            print(f"ASR {index}/{total} | {elapsed:.1f}s elapsed | ETA {eta:.1f}s | {chunk_id}", flush=True)
        comparison = compare_transcript(item.get("source_text", ""), recognized)
        report = {
            "chunk_id": chunk_id,
            "page": item.get("page"),
            "paragraph": item.get("paragraph"),
            "confidence": round(confidence, 4),
            "cache": cache_status,
            "recognized_text": recognized,
            **comparison,
        }
        chunk_reports.append(report)
        if comparison.get("comparison_mode") == "romanized_asr":
            ratio = comparison["word_count_ratio"]
            if ratio < 0.75 or ratio > 1.35:
                findings.append({
                    "severity": "warning",
                    "code": "transcript_length_anomaly",
                    "message": "Romanized ASR word count differs materially from source.",
                    **report,
                })
        elif comparison["coverage"] < min_coverage:
            findings.append({
                "severity": "warning",
                "code": "transcript_mismatch",
                "message": "ASR transcript does not cover the source text sufficiently.",
                **report,
            })
        elif comparison["additions"] or comparison["omissions"]:
            findings.append({
                "severity": "warning",
                "code": "transcript_difference",
                "message": "ASR found a localized addition or omission.",
                **report,
            })
        if confidence < 0.45:
            findings.append({
                "severity": "warning",
                "code": "asr_low_confidence",
                "message": "ASR confidence is low; human listening is required.",
                **report,
            })

    blockers = sum(item["severity"] == "blocker" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    report = {
        "version": 1,
        "project": root.name,
        "status": "fail" if blockers else ("review" if warnings else "pass"),
        "model": type(recognizer).__name__,
        "model_settings": model_settings or {},
        "summary": {"chunks": len(segments), "blockers": blockers, "warnings": warnings,
                     "sample": items is not None},
        "findings": findings,
        "chunks": chunk_reports,
    }
    target = root / "07_qa" / "checker_simulation.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
