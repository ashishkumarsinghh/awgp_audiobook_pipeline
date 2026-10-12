from pathlib import Path

from src.db.models import Project
from src.editorial.manuscript import Passage, render


def test_manuscript_api_uses_authoritative_workspace(client, db_session, tmp_path):
    signup = client.post("/api/signup", json={"username": "admin", "password": "pw"})
    headers = {"Authorization": f"Bearer {signup.json()['token']}"}
    project_name = "manuscript_book"
    db_session.add(Project(name=project_name, status="00_Starting"))
    db_session.commit()

    import api
    original_dir = api.PROJECTS_DIR
    api.PROJECTS_DIR = str(tmp_path)
    try:
        project_dir = Path(tmp_path) / project_name
        project_dir.mkdir()
        manuscript = render([Passage("p_one", "पहला पाठ", page="1", pdf_page="1")])
        (project_dir / "manuscript.txt").write_text(manuscript, encoding="utf-8")

        detail = client.get(f"/api/projects/{project_name}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["manuscript_workflow"] is True

        fetched = client.get(f"/api/projects/{project_name}/manuscript", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["passages"][0]["text"] == "पहला पाठ"

        found = client.get(f"/api/projects/{project_name}/manuscript/search",
                           params={"query": "पहला"}, headers=headers)
        assert found.status_code == 200
        assert found.json()["matches"][0]["id"] == "p_one"

        updated = manuscript.replace("पहला पाठ", "बदला हुआ पाठ")
        saved = client.put(f"/api/projects/{project_name}/manuscript",
                           json={"content": updated}, headers=headers)
        assert saved.status_code == 200
        assert "बदला हुआ पाठ" in (project_dir / "manuscript.txt").read_text(encoding="utf-8")

        legacy_write = client.put(f"/api/projects/{project_name}/clean",
                                  json={"text": "must not fork the manuscript"}, headers=headers)
        assert legacy_write.status_code == 409
    finally:
        api.PROJECTS_DIR = original_dir
