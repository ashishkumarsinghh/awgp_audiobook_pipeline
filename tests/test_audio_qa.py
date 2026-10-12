import json
import wave
from pathlib import Path

from src.qa.audio_qa import run_audio_qa
from src.qa.checker_simulator import compare_transcript


def test_checker_transcript_comparison_detects_omission_and_addition():
    result = compare_transcript("मन साधे जीवन सधै", "मन जीवन अतिरिक्त")
    assert result["omissions"] == ["साधे", "सधै"]
    assert result["additions"] == ["अतिरिक्त"]
    assert result["coverage"] < 1.0


def test_checker_transcript_does_not_false_fail_on_romanized_hindi():
    result = compare_transcript("मन साधे जीवन सधै", "man sadhe jeevan sadhai")
    assert result["comparison_mode"] == "romanized_asr"
    assert result["coverage"] is None


def write_wav(path: Path, value: int = 1000, frames: int = 24000):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 24000, frames, "NONE", "not compressed"))
        audio.writeframes((value.to_bytes(2, "little", signed=True)) * frames)


def test_audio_qa_passes_contract_and_wav(tmp_path, monkeypatch):
    project = tmp_path / "book"
    for name in ("01_segments", "02_phonetics", "05_audio_chunks", "04_master"):
        (project / name).mkdir(parents=True)
    item = {"id": "chunk_0001", "source_text": "निर्बल मन", "segment_type": "prose",
            "page": 6, "paragraph": 1, "pause_after_ms": 200}
    phon = {**item, "pronunciation_text": "निरबल मन", "rate": "+0%", "pitch": "+0Hz", "volume": "+0%"}
    (project / "01_segments" / "segments.json").write_text(json.dumps([item], ensure_ascii=False))
    (project / "02_phonetics" / "phonetics.json").write_text(json.dumps([phon], ensure_ascii=False))
    write_wav(project / "05_audio_chunks" / "chunk_0001.wav")
    (project / "05_audio_chunks" / "manifest.json").write_text(json.dumps({"chunks": {"chunk_0001": {"status": "complete"}}}))
    master = project / "04_master" / "book.mp3"
    master.write_bytes(b"placeholder")
    monkeypatch.setattr("src.qa.audio_qa.validate_mp3", lambda path: True)
    (project / "project_corrections.json").write_text(json.dumps({"corrections": [
        {"stage": "phonetics", "find": "निर्बल", "replace": "निरबल"}
    ]}, ensure_ascii=False))
    report = run_audio_qa(str(project))
    assert report["status"] == "pass"
    assert report["summary"]["blockers"] == 0


def test_audio_qa_flags_source_drift_and_clipping(tmp_path, monkeypatch):
    project = tmp_path / "book"
    for name in ("01_segments", "02_phonetics", "05_audio_chunks", "04_master"):
        (project / name).mkdir(parents=True)
    item = {"id": "chunk_0001", "source_text": "सही पाठ", "page": 1, "paragraph": 1}
    phon = {**item, "source_text": "बदला हुआ पाठ", "pronunciation_text": "बदला हुआ पाठ"}
    (project / "01_segments" / "segments.json").write_text(json.dumps([item], ensure_ascii=False))
    (project / "02_phonetics" / "phonetics.json").write_text(json.dumps([phon], ensure_ascii=False))
    write_wav(project / "05_audio_chunks" / "chunk_0001.wav", value=32767)
    (project / "05_audio_chunks" / "manifest.json").write_text(json.dumps({"chunks": {"chunk_0001": {"status": "complete"}}}))
    (project / "04_master" / "book.mp3").write_bytes(b"placeholder")
    monkeypatch.setattr("src.qa.audio_qa.validate_mp3", lambda path: True)
    report = run_audio_qa(str(project))
    codes = {finding["code"] for finding in report["findings"]}
    assert report["status"] == "fail"
    assert {"source_drift", "clipping"}.issubset(codes)
