import pytest
from src.db.models import User, Project
import os
import io
import json

def test_signup_first_user_is_admin(client):
    res = client.post("/api/signup", json={"username": "admin1", "password": "password123"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["role"] == "admin"
    assert "token" in data

def test_signup_second_user_is_editor(client):
    client.post("/api/signup", json={"username": "admin1", "password": "password123"})
    res = client.post("/api/signup", json={"username": "editor1", "password": "password123"})
    assert res.status_code == 200
    data = res.json()
    assert data["role"] == "editor"

def test_signup_duplicate_username(client):
    client.post("/api/signup", json={"username": "testuser", "password": "pw"})
    res = client.post("/api/signup", json={"username": "testuser", "password": "pw2"})
    assert res.status_code == 400
    assert "Username taken" in res.json()["detail"]

def test_login_success(client):
    client.post("/api/signup", json={"username": "testuser", "password": "pw"})
    res = client.post("/api/login", json={"username": "testuser", "password": "pw"})
    assert res.status_code == 200
    assert "token" in res.json()

def test_login_invalid_password(client):
    client.post("/api/signup", json={"username": "testuser", "password": "pw"})
    res = client.post("/api/login", json={"username": "testuser", "password": "wrong"})
    assert res.status_code == 401

def test_request_allocation(client):
    signup_res = client.post("/api/signup", json={"username": "editor", "password": "pw"})
    token = signup_res.json()["token"]
    
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "full_name": "Test Editor",
        "email": "test@test.com",
        "phone": "1234567890"
    }
    res = client.post("/api/users/request-allocation", json=payload, headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "success"

def test_admin_allocate_user(client, db_session):
    admin_res = client.post("/api/signup", json={"username": "admin", "password": "pw"})
    admin_token = admin_res.json()["token"]
    
    editor_res = client.post("/api/signup", json={"username": "editor", "password": "pw"})
    editor_id = editor_res.json()["user_id"]
    
    p = Project(name="test_book", status="00_Starting")
    db_session.add(p)
    db_session.commit()
    project_id = p.id
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post("/api/admin/allocate-user", data={"user_id": editor_id, "project_id": project_id}, headers=headers)
    assert res.status_code == 200
    
    db_session.refresh(p)
    assert p.assigned_to == editor_id

def test_admin_direct_assign_project(client, db_session):
    admin_res = client.post("/api/signup", json={"username": "admin", "password": "pw"})
    admin_token = admin_res.json()["token"]
    
    editor_res = client.post("/api/signup", json={"username": "editor", "password": "pw"})
    editor_id = editor_res.json()["user_id"]
    
    p = Project(name="direct_book", status="00_Starting")
    db_session.add(p)
    db_session.commit()
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.post(f"/api/projects/{p.name}/assign", data={"user_id": editor_id}, headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    
    db_session.refresh(p)
    assert p.assigned_to == editor_id

def test_editor_cannot_allocate_user(client, db_session):
    client.post("/api/signup", json={"username": "admin", "password": "pw"})
    editor_res = client.post("/api/signup", json={"username": "editor", "password": "pw"})
    editor_token = editor_res.json()["token"]
    
    headers = {"Authorization": f"Bearer {editor_token}"}
    res = client.post("/api/admin/allocate-user", data={"user_id": 2, "project_id": 1}, headers=headers)
    assert res.status_code == 403

def test_list_projects(client, db_session):
    admin_res = client.post("/api/signup", json={"username": "admin", "password": "pw"})
    admin_token = admin_res.json()["token"]
    
    editor_res = client.post("/api/signup", json={"username": "editor", "password": "pw"})
    editor_token = editor_res.json()["token"]
    editor_id = editor_res.json()["user_id"]
    
    p1 = Project(name="proj1", status="00_Starting", assigned_to=None)
    p2 = Project(name="proj2", status="05_Mastered", assigned_to=editor_id)
    db_session.add_all([p1, p2])
    db_session.commit()
    
    res = client.get("/api/projects", headers={"Authorization": f"Bearer {admin_token}"})
    assert len(res.json()["projects"]) == 2
    assert res.json()["metrics"]["total"] == 2
    
    res2 = client.get("/api/projects", headers={"Authorization": f"Bearer {editor_token}"})
    assert len(res2.json()["projects"]) == 1
    assert res2.json()["projects"][0]["name"] == "proj2"

def test_create_project_and_get_details(client, tmp_path):
    admin_res = client.post("/api/signup", json={"username": "admin", "password": "pw"})
    admin_token = admin_res.json()["token"]
    
    import api
    original_dir = api.PROJECTS_DIR
    api.PROJECTS_DIR = str(tmp_path)
    
    try:
        headers = {"Authorization": f"Bearer {admin_token}"}
        fake_pdf = io.BytesIO(b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 1\n0000000000 65535 f \ntrailer<</Size 1/Root 1 0 R>>\nstartxref\n34\n%%EOF")
        files = {"file": ("test.pdf", fake_pdf, "application/pdf")}
        data = {"name": "book_alpha"}
        
        res = client.post("/api/projects", data=data, files=files, headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        
        # Verify details
        detail_res = client.get("/api/projects/book_alpha", headers=headers)
        assert detail_res.status_code == 200
        details = detail_res.json()
        assert details["name"] == "book_alpha"
        assert details["status"] == "00_Starting"
        assert details["has_pdf"] is True
    finally:
        api.PROJECTS_DIR = original_dir

def test_clean_and_raw_text_endpoints(client, tmp_path, db_session):
    admin_res = client.post("/api/signup", json={"username": "admin", "password": "pw"})
    admin_token = admin_res.json()["token"]
    
    import api
    original_dir = api.PROJECTS_DIR
    api.PROJECTS_DIR = str(tmp_path)
    
    try:
        headers = {"Authorization": f"Bearer {admin_token}"}
        proj_name = "test_text_proj"
        db_session.add(Project(name=proj_name))
        db_session.commit()
        proj_dir = tmp_path / proj_name
        proj_dir.mkdir(parents=True, exist_ok=True)
        
        # Save raw text
        save_raw = client.put(f"/api/projects/{proj_name}/raw", json={"text": "Raw OCR Line 1।"}, headers=headers)
        assert save_raw.status_code == 200
        
        # Read text
        get_res = client.get(f"/api/projects/{proj_name}/raw", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["raw_text"] == "Raw OCR Line 1।"
        assert get_res.json()["has_clean"] is False
        
        # Save clean text
        save_clean = client.put(f"/api/projects/{proj_name}/clean", json={"text": "Cleaned Line 1।"}, headers=headers)
        assert save_clean.status_code == 200
        
        # Read text again (should prefer clean text)
        get_res2 = client.get(f"/api/projects/{proj_name}/raw", headers=headers)
        assert get_res2.status_code == 200
        assert get_res2.json()["has_clean"] is True
        assert get_res2.json()["clean_text"] == "Cleaned Line 1।"
        assert get_res2.json()["text"] == "Cleaned Line 1।"
    finally:
        api.PROJECTS_DIR = original_dir

def test_segments_and_phonetics_persistence(client, tmp_path, db_session):
    admin_res = client.post("/api/signup", json={"username": "admin", "password": "pw"})
    admin_token = admin_res.json()["token"]
    
    import api
    original_dir = api.PROJECTS_DIR
    api.PROJECTS_DIR = str(tmp_path)
    
    try:
        headers = {"Authorization": f"Bearer {admin_token}"}
        proj_name = "test_seg_proj"
        db_session.add(Project(name=proj_name))
        db_session.commit()
        proj_dir = tmp_path / proj_name
        proj_dir.mkdir(parents=True, exist_ok=True)
        
        # Update segments
        sample_segments = [
            {"id": "chunk_0001", "source_text": "ॐ भूर्भुवः स्वः।", "segment_type": "mantra", "pause_after_ms": 500}
        ]
        save_seg = client.put(f"/api/projects/{proj_name}/segments", json=sample_segments, headers=headers)
        assert save_seg.status_code == 200
        
        # Fetch segments
        get_seg = client.get(f"/api/projects/{proj_name}/segments", headers=headers)
        assert get_seg.status_code == 200
        assert len(get_seg.json()) == 1
        assert get_seg.json()[0]["segment_type"] == "mantra"
        
        # Save phonetics
        sample_phonetics = [
            {"id": "chunk_0001", "source_text": "ॐ भूर्भुवः स्वः।", "pronunciation_text": "ॐ भूर्भुवः स्वः", "rate": "+0%", "pitch": "+0Hz"}
        ]
        save_phon = client.put(f"/api/projects/{proj_name}/phonetics", json=sample_phonetics, headers=headers)
        assert save_phon.status_code == 200
        
        # Fetch phonetics
        get_phon = client.get(f"/api/projects/{proj_name}/phonetics", headers=headers)
        assert get_phon.status_code == 200
        assert len(get_phon.json()) == 1
        assert get_phon.json()[0]["id"] == "chunk_0001"
    finally:
        api.PROJECTS_DIR = original_dir

def test_audit_logs(client, tmp_path, db_session):
    admin_res = client.post("/api/signup", json={"username": "admin", "password": "pw"})
    admin_token = admin_res.json()["token"]
    
    import api
    original_dir = api.PROJECTS_DIR
    api.PROJECTS_DIR = str(tmp_path)
    
    try:
        headers = {"Authorization": f"Bearer {admin_token}"}
        proj_name = "audit_book"
        db_session.add(Project(name=proj_name))
        db_session.commit()
        proj_dir = tmp_path / proj_name
        proj_dir.mkdir(parents=True, exist_ok=True)
        
        # Perform some actions
        client.put(f"/api/projects/{proj_name}/clean", json={"text": "Clean"}, headers=headers)
        client.put(f"/api/projects/{proj_name}/segments", json=[{"id": "c1", "source_text": "A"}], headers=headers)
        
        res = client.get(f"/api/projects/{proj_name}/audit", headers=headers)
        assert res.status_code == 200
        logs = res.json()
        assert len(logs) >= 2
    finally:
        api.PROJECTS_DIR = original_dir
