"""Resumable synthesis keyed by narration inputs, provider and audio content."""
import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path
from src.core.artifacts import write_json, validate_segments
from src.core.types import SpeechSegment
from src.synthesis.audio.io import validate_wav


def fingerprint(item, provider, voice):
    payload = {"version": 1, "provider": provider, "voice": voice, "segment": item}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def audio_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def _word_count(text: str) -> int:
    return len([token for token in (text or "").split() if token.strip()])


def as_segment(item, audio_dir):
    fields = {k: v for k, v in item.items() if k in SpeechSegment.__dataclass_fields__}
    fields["normalized_text"] = item.get("normalized_text", item["source_text"])
    fields["pronunciation_text"] = item.get("pronunciation_text", item["source_text"])
    fields["audio_file"] = str(Path(audio_dir) / f"{item['id']}.wav")
    return SpeechSegment(**fields)


def load_manifest(audio_dir):
    try:
        with open(Path(audio_dir) / "manifest.json", encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def is_current(item, record, audio_dir, provider, voice, *, verify_audio=True):
    if not isinstance(record, dict) or record.get("status") != "complete":
        return False
    if record.get("fingerprint") != fingerprint(item, provider, voice):
        return False
    path = Path(audio_dir) / f"{item['id']}.wav"
    try:
        if not verify_audio:
            stat = path.stat()
            return stat.st_size == record.get("size_bytes") and stat.st_mtime_ns == record.get("mtime_ns")
        validate_wav(path)
        return record.get("sha256") == audio_digest(path)
    except (OSError, ValueError):
        return False


async def synthesize_segments(data, audio_dir, tts, provider, *, attempts=2, concurrency=3, timeout=90):
    validate_segments(data)
    if attempts < 1 or concurrency < 1 or timeout <= 0:
        raise ValueError("Synthesis attempts, concurrency and timeout must be positive.")
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = audio_dir / "manifest.json"
    old = load_manifest(audio_dir).get("chunks", {})
    if not isinstance(old, dict):
        old = {}
    voice = tts.voice
    records = {}
    for item in data:
        chunk_id = item["id"]
        record = old.get(chunk_id, {})
        records[chunk_id] = record if is_current(item, record, audio_dir, provider, voice) else {
            "status": "pending", "fingerprint": fingerprint(item, provider, voice)
        }

    for item in data:
        record = records[item["id"]]
        if record["status"] == "complete":
            stat = (audio_dir / f"{item['id']}.wav").stat()
            record.update(size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)

    def persist():
        write_json(manifest_path, {"version": 1, "provider": provider, "voice": voice, "chunks": records})

    persist()
    semaphore = asyncio.Semaphore(concurrency)

    async def generate(item):
        chunk_id = item["id"]
        record = records[chunk_id]
        if record["status"] == "complete":
            return
        async with semaphore:
            record["status"] = "running"
            persist()
            for attempt in range(attempts):
                record["attempt"] = attempt + 1
                persist()
                try:
                    with tempfile.TemporaryDirectory(prefix=".tts-", dir=audio_dir) as temporary:
                        target = Path(temporary) / "chunk.wav"
                        segment = as_segment(item, audio_dir)
                        await asyncio.wait_for(tts.synthesize(segment, str(target)), timeout=timeout)
                        duration = validate_wav(target)
                        digest = audio_digest(target)
                        os.replace(target, audio_dir / f"{chunk_id}.wav")
                    stat = (audio_dir / f"{chunk_id}.wav").stat()
                    words = _word_count(item.get("source_text", ""))
                    wpm = round(words / duration * 60, 1) if duration else 0
                    record.update(status="complete", duration_seconds=duration, sha256=digest,
                                  size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
                                  word_count=words, measured_wpm=wpm)
                    # Provider pace varies by voice and language. Keep the
                    # measured value visible so editors can correct outliers
                    # instead of silently accepting a drifting reading speed.
                    record["pace_warning"] = bool(wpm and (wpm < 115 or wpm > 175))
                    record.pop("error", None)
                    persist()
                    return
                except Exception as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    if attempt + 1 < attempts:
                        await asyncio.sleep(min(2 ** attempt, 5))
            record["status"] = "failed"
            persist()

    await asyncio.gather(*(generate(item) for item in data))
    failures = [f"{key}: {record.get('error', record['status'])}" for key, record in records.items() if record["status"] != "complete"]
    if failures:
        raise RuntimeError("Narration incomplete. Retry Audio to resume verified chunks. " + "; ".join(failures))
