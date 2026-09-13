from pathlib import Path
from src.db.models import Project


def test_only_admin_can_delete_project(client, db_session, tmp_path, monkeypatch):
    import api
    monkeypatch.setattr(api, "PROJECTS_DIR", str(tmp_path))
    admin = client.post("/api/signup", json={"username": "owner", "password": "pw"}).json()
    editor = client.post("/api/signup", json={"username": "editor", "password": "pw"}).json()
    db_session.add(Project(name="book"))
    db_session.commit()
    (tmp_path / "book").mkdir()
    (tmp_path / "book" / "00_scanned.pdf").write_bytes(b"pdf")
    assert client.delete("/api/projects/book", headers={"Authorization": f"Bearer {editor['token']}"}).status_code == 403
    response = client.delete("/api/projects/book", headers={"Authorization": f"Bearer {admin['token']}"})
    assert response.status_code == 200
    assert not (tmp_path / "book").exists()
    assert db_session.query(Project).filter_by(name="book").first() is None
