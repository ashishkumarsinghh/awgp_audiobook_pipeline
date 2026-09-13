from src.db.models import Project, Candidate


def test_review_candidate_issue_and_approval_gate(client, db_session, tmp_path, monkeypatch):
    import api
    monkeypatch.setattr(api, "PROJECTS_DIR", str(tmp_path))
    auth = client.post("/api/signup", json={"username": "reviewer", "password": "pw"}).json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    db_session.add(Project(name="book", status="05_Mastered"))
    db_session.commit()
    db_session.add(Candidate(project_name="book", artifact_filename="06_mastered.mp3", sha256="abc",
                             status="pending_review", source_status="05_Mastered", created_by=1))
    db_session.commit()

    review = client.get("/api/projects/book/review", headers=headers)
    assert review.status_code == 200
    assert review.json()["open_blockers"] == 0

    created = client.post("/api/projects/book/review/issues", headers=headers,
                          json={"body": "Check the verse ending", "severity": "blocker", "page_number": 4})
    assert created.status_code == 200
    blocked = client.post("/api/projects/book/review/decision", headers=headers,
                          json={"decision": "approved"})
    assert blocked.status_code == 409

    issue_id = created.json()["issue_id"]
    resolved = client.patch(f"/api/projects/book/review/issues/{issue_id}", headers=headers,
                            data={"status": "resolved"})
    assert resolved.status_code == 200
    approved = client.post("/api/projects/book/review/decision", headers=headers,
                           json={"decision": "approved", "summary": "Reviewed PDF and audio"})
    assert approved.status_code == 200
    assert approved.json()["approval_count"] == 1
    assert db_session.query(Project).filter_by(name="book").one().status == "06_Pending_Second_Approval"
    second = client.post("/api/signup", json={"username": "second-reviewer", "password": "pw"}).json()
    db_session.query(Project).filter_by(name="book").one().assigned_to = second["user_id"]
    db_session.commit()
    approved_twice = client.post("/api/projects/book/review/decision",
                                 headers={"Authorization": f"Bearer {second['token']}"},
                                 json={"decision": "approved", "summary": "Independent second review"})
    assert approved_twice.status_code == 200
    assert db_session.query(Project).filter_by(name="book").one().status == "06_Approved"


def test_changes_requested_is_a_distinct_project_state(client, db_session, tmp_path, monkeypatch):
    import api
    monkeypatch.setattr(api, "PROJECTS_DIR", str(tmp_path))
    auth = client.post("/api/signup", json={"username": "reviewer", "password": "pw"}).json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    db_session.add(Project(name="book", status="05_Mastered"))
    db_session.commit()
    db_session.add(Candidate(project_name="book", artifact_filename="06_mastered.mp3", sha256="def",
                             status="pending_review", source_status="05_Mastered", created_by=1))
    db_session.commit()
    response = client.post("/api/projects/book/review/decision", headers=headers,
                           json={"decision": "changes_requested", "summary": "Fix pronunciation"})
    assert response.status_code == 200
    assert db_session.query(Project).filter_by(name="book").one().status == "06_Changes_Requested"
