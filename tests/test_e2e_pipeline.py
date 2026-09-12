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
    
    # Fake that background Stage 0 completed by creating 01_ocr_raw.txt
    proj_dir = tmp_path / "e2e_book"
    os.makedirs(proj_dir, exist_ok=True)
    with open(proj_dir / "01_ocr_raw.txt", "w") as f:
        f.write("Chapter 1\nThis is a test sentence. This is another sentence.")
    
    # Update DB status
    project = db_session.query(Project).filter_by(name="e2e_book").first()
    project.status = "01_Raw_Text"
    db_session.commit()

    # 2. Test Get Segments on fresh project (should be 404)
    res = client.get("/api/projects/e2e_book/segments", headers=auth_headers)
    assert res.status_code == 404

    # 3. Run Stage 1 (Segmentation)
    res = client.post("/api/projects/e2e_book/stage/1", headers=auth_headers)
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

    # 6. Run Stage 2 (Phonetics)
    res = client.post("/api/projects/e2e_book/stage/2", headers=auth_headers)
    assert res.status_code == 200
    
    res = client.get("/api/projects/e2e_book/segments", headers=auth_headers)
    assert "pronunciation_text" in res.json()[0]

    # 7. Run Stage 3 (Audio) - mock Edge TTS so it doesn't actually hit the network
    with patch("src.synthesis.providers.EdgeTTSProvider.synthesize") as mock_synth:
        mock_synth.return_value = None # Doesn't matter, we just don't want to hit network
        # Actually wait, EdgeTTSProvider writes a file, if it doesn't write a file, assembler might fail, or it's just chunk generation.
        # Stage 3 is audio_chunks. It calls pipeline_v3.py
        # Let's mock os.system for ffmpeg too
        with patch("os.system") as mock_sys:
            mock_sys.return_value = 0
            # Run Stage 3
            res = client.post("/api/projects/e2e_book/stage/3", headers=auth_headers)
            assert res.status_code == 200
            
            # Run Stage 4 (Mastering)
            res = client.post("/api/projects/e2e_book/stage/4", headers=auth_headers)
            assert res.status_code == 200

    # Test invalid stage
    res = client.post("/api/projects/e2e_book/stage/99", headers=auth_headers)
    assert res.status_code == 400
