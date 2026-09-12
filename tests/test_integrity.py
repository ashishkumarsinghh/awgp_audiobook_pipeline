import asyncio
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from src.core.artifacts import validate_segments, write_json
from src.synthesis.runner import synthesize_segments, load_manifest
from src.synthesis.audio.io import validate_wav
from src.pipeline_v3 import ProjectManager
from src.normalize.segmenter import SemanticSegmenter
from tests.test_pipeline import create_fake_wav


class LocalProvider:
    voice = "test-voice"

    def __init__(self):
        self.calls = []
        self.fail = set()

    async def synthesize(self, segment, path):
        self.calls.append(segment.source_text)
        if segment.source_text in self.fail:
            Path(path).write_bytes(b"partial")
            raise RuntimeError("provider unavailable")
        create_fake_wav(str(path), 100)


def items():
    return [{"id": "one", "source_text": "first"}, {"id": "two", "source_text": "second"}]


def run(data, folder, provider):
    return asyncio.run(synthesize_segments(data, folder, provider, "test", attempts=1))


def test_retry_preserves_good_chunks_and_never_inserts_silence(tmp_path):
    provider = LocalProvider()
    provider.fail.add("second")
    with pytest.raises(RuntimeError, match="two.*provider unavailable"):
        run(items(), tmp_path, provider)
    assert not (tmp_path / "two.wav").exists()
    assert load_manifest(tmp_path)["chunks"]["two"]["status"] == "failed"
    provider.fail.clear()
    run(items(), tmp_path, provider)
    assert provider.calls == ["first", "second", "second"]
    assert validate_wav(tmp_path / "two.wav") == 0.1


@pytest.mark.parametrize("change", ["text", "voice", "corruption", "rate", "pause"])
def test_cache_invalidation(tmp_path, change):
    provider = LocalProvider()
    data = items()
    run(data, tmp_path, provider)
    provider.calls.clear()
    if change == "text":
        data[0]["source_text"] = "changed"
    elif change == "voice":
        provider.voice = "other-voice"
    elif change == "corruption":
        (tmp_path / "one.wav").write_bytes(b"broken" * 100)
    elif change == "rate":
        data[0]["rate"] = "-10%"
    else:
        data[0]["pause_after_ms"] = 300
    run(data, tmp_path, provider)
    assert len(provider.calls) == (2 if change == "voice" else 1)


def test_master_refuses_missing_and_unverified_audio(tmp_path):
    pm = ProjectManager(str(tmp_path))
    write_json(pm.phonetics_file, items())
    create_fake_wav(str(Path(pm.audio_dir) / "one.wav"))
    with pytest.raises(RuntimeError, match="unverified audio"):
        pm.run_stage_4_mastering()
    assert not Path(pm.master_file).exists()


def test_master_refuses_text_changed_since_synthesis(tmp_path):
    pm = ProjectManager(str(tmp_path))
    pm.tts = LocalProvider()
    pm.tts_provider = "test"
    data = items()
    write_json(pm.phonetics_file, data)
    pm.run_stage_3_audio()
    data[0]["source_text"] = "changed"
    write_json(pm.phonetics_file, data)
    with pytest.raises(RuntimeError, match="one"):
        pm.run_stage_4_mastering()


@pytest.mark.parametrize("data", [
    [], [{"id": "../escape", "source_text": "text"}],
    [{"id": "a", "source_text": ""}],
    [{"id": "a", "source_text": "text", "pause_after_ms": -1}],
    [{"id": "a", "source_text": "text", "rate": "bad"}],
    [{"id": "a", "source_text": "one"}, {"id": "a", "source_text": "two"}],
])
def test_invalid_segments_fail_early(data):
    with pytest.raises(ValueError):
        validate_segments(data)


def test_chunking_preserves_all_punctuation_and_bounds():
    text = 'पहला वाक्य... “दूसरा?!” मूल्य 3.14 है। ॐ शान्तिः॥'
    segments = SemanticSegmenter(max_chars_per_chunk=22).segment_text(text)
    assert all(len(s.source_text) <= 22 for s in segments)
    assert " ".join(s.source_text for s in segments) == text


def test_long_verse_is_bounded_and_paragraphs_stay_separate():
    verse = "ॐ शान्तिः " * 20 + "॥"
    segments = SemanticSegmenter(max_chars_per_chunk=40).segment_text(f"<shloka>{verse}</shloka>")
    assert all(s.segment_type == "shloka" and len(s.source_text) <= 40 for s in segments)
    assert " ".join(s.source_text for s in segments) == verse
    assert len(SemanticSegmenter().segment_text("one paragraph\n\nsecond paragraph")) == 2


def test_unbroken_ocr_word_requires_review():
    with pytest.raises(ValueError, match="OCR spacing"):
        SemanticSegmenter(max_chars_per_chunk=10).segment_text("x" * 50)


def test_upstream_change_invalidates_derived_artifacts(tmp_path):
    pm = ProjectManager(str(tmp_path))
    for file in [pm.clean_file, pm.segments_file, pm.phonetics_file, pm.master_file]:
        Path(file).write_text("old")
    Path(pm.audio_dir, "old.wav").write_bytes(b"cached")
    pm.invalidate_after("raw")
    assert not Path(pm.clean_file).exists()
    assert not Path(pm.master_file).exists()
    assert Path(pm.audio_dir, "old.wav").exists()


def test_background_failure_visible_and_retryable(client, db_session, tmp_path, monkeypatch):
    import api
    from src.db.models import Project
    monkeypatch.setattr(api, "PROJECTS_DIR", str(tmp_path))
    auth = client.post("/api/signup", json={"username": "owner", "password": "pw"}).json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    db_session.add(Project(name="book"))
    db_session.commit()
    pm = ProjectManager(str(tmp_path / "book"))
    write_json(pm.phonetics_file, items())

    async def fail(segment, path):
        raise RuntimeError("provider quota exhausted")
    with patch("src.synthesis.providers.EdgeTTSProvider.synthesize", side_effect=fail):
        assert client.post("/api/projects/book/stage/4", headers=headers).status_code == 200
    detail = client.get("/api/projects/book", headers=headers).json()
    assert detail["status"] == "03_Phonetics"
    assert detail["audio_progress"]["completed"] == 0
    assert len(detail["audio_progress"]["failed"]) == 2
    assert not api.project_lock("book").locked()
    assert client.post("/api/projects/book/stage/5", headers=headers).status_code == 500


def test_project_access_and_settings(client, db_session, tmp_path, monkeypatch):
    import api
    from src.db.models import Project
    monkeypatch.setattr(api, "PROJECTS_DIR", str(tmp_path))
    admin = client.post("/api/signup", json={"username": "owner", "password": "pw"}).json()
    editor = client.post("/api/signup", json={"username": "admin", "password": "pw"}).json()
    assert editor["role"] == "editor"
    db_session.add(Project(name="private"))
    db_session.commit()
    admin_headers = {"Authorization": f"Bearer {admin['token']}"}
    headers = {"Authorization": f"Bearer {editor['token']}"}
    for suffix in ["", "/audio/chunk_0001", "/raw", "/settings/tts-provider"]:
        assert client.get(f"/api/projects/private{suffix}", headers=headers).status_code == 403
    assert client.get("/api/projects/private/audio/chunk_0001").status_code == 401
    assert client.get("/api/projects/private/settings/tts-provider", headers=admin_headers).status_code == 200
    assert client.put("/api/projects/private/segments", headers=admin_headers,
                      json=[{"id": "../escape", "source_text": "bad"}]).status_code == 422


def test_uncertain_ocr_requires_review():
    with pytest.raises(ValueError, match="unresolved OCR"):
        validate_segments([{"id": "a", "source_text": "यह [अस्पष्ट] है।"}])


def test_api_noop_save_preserves_artifacts_and_edit_invalidates(client, db_session, tmp_path, monkeypatch):
    import api
    from src.db.models import Project
    monkeypatch.setattr(api, "PROJECTS_DIR", str(tmp_path))
    auth = client.post("/api/signup", json={"username": "owner", "password": "pw"}).json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    db_session.add(Project(name="book"))
    db_session.commit()
    pm = ProjectManager(str(tmp_path / "book"))
    Path(pm.clean_file).write_text("source")
    write_json(pm.segments_file, items())
    write_json(pm.phonetics_file, items())
    assert client.put("/api/projects/book/clean", json={"text": "source"}, headers=headers).status_code == 200
    assert Path(pm.phonetics_file).exists()
    changed = items()
    changed[0]["source_text"] = "edited"
    assert client.put("/api/projects/book/segments", json=changed, headers=headers).status_code == 200
    assert not Path(pm.phonetics_file).exists()
    assert json.loads(Path(pm.segments_file).read_text())[0]["source_text"] == "edited"
    assert client.put("/api/projects/book/clean", json={"text": "new source"}, headers=headers).status_code == 200
    assert not Path(pm.segments_file).exists()
