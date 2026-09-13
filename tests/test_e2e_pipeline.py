import pytest
import os
import io
import json
from unittest.mock import patch
from src.db.models import Project

@pytest.fixture
def auth_headers(client):
    res = client.post("/api/signup", json={"username": "testadmin", "password": "pw"})
    token = res.json()["token"]
    return {"Authorization": f"Bearer {token}"}

@patch("api.PROJECTS_DIR", "/tmp/pytest_projects")
def test_full_pipeline_e2e(client, auth_headers, db_session, tmp_path):
    import api
    api.PROJECTS_DIR = str(tmp_path)
    
    # 1. Create a Project
    fake_pdf = io.BytesIO(b"fake pdf content")
    res = client.post("/api/projects", data={"name": "e2e_book"}, files={"file": ("test.pdf", fake_pdf, "application/pdf")}, headers=auth_headers)
    assert res.status_code == 200
    
    # Fake that OCR completed by creating 01_ocr_raw.txt
    proj_dir = tmp_path / "e2e_book"
    os.makedirs(proj_dir, exist_ok=True)
    with open(proj_dir / "01_ocr_raw.txt", "w") as f:
        f.write("Chapter 1\nThis is a test sentence. This is another sentence.")
    
    # Update DB status
    project = db_session.query(Project).filter_by(name="e2e_book").first()
    project.status = "01_OCR_Done"
    db_session.commit()

    # 2. Test Get Segments on fresh project (should be 404)
    res = client.get("/api/projects/e2e_book/segments", headers=auth_headers)
    assert res.status_code == 404

    # 3. Run Stage 2 (Segmentation)
    res = client.post("/api/projects/e2e_book/stage/2", headers=auth_headers)
    assert res.status_code == 200
    
    # 4. Test Get Segments now (should have data)
    res = client.get("/api/projects/e2e_book/segments", headers=auth_headers)
    assert res.status_code == 200
    segments = res.json()
    assert len(segments) > 0
    assert len(segments) > 0

    # 5. Test Put Segments (Save changes)
    segments[0]["source_text"] = "Chapter One Modified"
    res = client.put("/api/projects/e2e_book/segments", json=segments, headers=auth_headers)
    assert res.status_code == 200

    res = client.get("/api/projects/e2e_book/segments", headers=auth_headers)
    assert res.json()[0]["source_text"] == "Chapter One Modified"

    # 6. Run Stage 3 (Phonetics)
    res = client.post("/api/projects/e2e_book/stage/3", headers=auth_headers)
    assert res.status_code == 200
    
    res = client.get("/api/projects/e2e_book/phonetics", headers=auth_headers)
    assert "pronunciation_text" in res.json()[0]

    # A checker edit must be the exact input consumed by Audio, even when a
    # previous chunk exists in the resumable audio directory.
    phonetics = res.json()
    phonetics[0]["pronunciation_text"] = "EDITOR OVERRIDE pronunciation"
    res = client.put("/api/projects/e2e_book/phonetics", json=phonetics, headers=auth_headers)
    assert res.status_code == 200

    # Generate actual PCM artifacts with a local provider double.
    from tests.test_pipeline import create_fake_wav
    synthesized_text = []
    async def synthesize(segment, output):
        synthesized_text.append(segment.pronunciation_text)
        create_fake_wav(output, 1000)
    def master(source, output, **kwargs):
        with open(output, "wb") as stream:
            stream.write(b"verified master")
    with patch("src.synthesis.providers.EdgeTTSProvider.synthesize", side_effect=synthesize):
        res = client.post("/api/projects/e2e_book/stage/4", headers=auth_headers)
        assert res.status_code == 200
    assert "EDITOR OVERRIDE pronunciation" in synthesized_text
    details = client.get("/api/projects/e2e_book", headers=auth_headers).json()
    assert details["status"] == "04_Audio_Review"
    assert details["audio_progress"]["percent"] == 100
    with patch("src.synthesis.assembler.AudioEnhancer.apply_studio_mastering", side_effect=master):
        res = client.post("/api/projects/e2e_book/stage/5", headers=auth_headers)
        assert res.status_code == 200
    assert (proj_dir / "06_mastered.mp3").read_bytes() == b"verified master"

    # Test invalid stage
    res = client.post("/api/projects/e2e_book/stage/99", headers=auth_headers)
    assert res.status_code == 400
