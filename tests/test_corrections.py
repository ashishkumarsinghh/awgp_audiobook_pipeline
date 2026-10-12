import json
from pathlib import Path

from src.db.models import Project, Candidate, Correction
from src.core.corrections import matching, remove_segments, apply_source_corrections


def test_declarative_corrections_are_stage_scoped_and_source_preserving():
    items = [
        {"id": "a", "page": 43, "source_text": "लेखक का संक्षिप्त परिचय", "segment_type": "heading"},
        {"id": "b", "page": 6, "source_text": "बड़ी-बड़ी बातें", "segment_type": "prose"},
    ]
    config = {"corrections": [
        {"stage": "segment", "find": "संक्षिप्त परिचय"},
        {"stage": "phonetics", "page": 6, "find": "बड़ी-बड़ी", "replace": "बड़ी बड़ी"},
    ]}
    kept = remove_segments(items, config)
    assert [item["id"] for item in kept] == ["a", "b"]
    config["corrections"][0]["approved"] = True
    kept = remove_segments(items, config)
    assert [item["id"] for item in kept] == ["b"]
    assert matching(config["corrections"][1], kept[0])
    assert kept[0]["source_text"] == "बड़ी-बड़ी बातें"


def test_approved_source_correction_is_audited_and_unapproved_exclusion_stays_safe():
    items = [{"id": "a", "page": 21, "source_text": "यह हो सकती संभव है।"}]
    config = {"corrections": [{
        "stage": "segment", "kind": "ocr_correction", "page": 21,
        "find": "हो सकती संभव है", "replace": "हो सकनी संभव है",
        "approved": True, "reason": "PDF verified"
    }]}

    corrected = apply_source_corrections(items, config)
    assert corrected[0]["source_text"] == "यह हो सकनी संभव है।"
    assert corrected[0]["content_correction_audit"][0]["kind"] == "ocr_correction"


def test_correction_preview_apply_is_versioned_and_exact(client, db_session, tmp_path, monkeypatch):
    import api
    monkeypatch.setattr(api, "PROJECTS_DIR", str(tmp_path))
    auth = client.post("/api/signup", json={"username": "editor", "password": "pw"}).json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    db_session.add(Project(name="book", assigned_to=auth["user_id"], version=1))
    db_session.commit()
    project_dir = tmp_path / "book" / "02_phonetics"
    project_dir.mkdir(parents=True)
    payload = [{"id": "stable-segment", "source_text": "यह शब्द है।", "pronunciation_text": "यह शब्द है।",
                "segment_type": "prose", "pause_before_ms": 0, "pause_after_ms": 200,
                "rate": "+0%", "pitch": "+0Hz", "volume": "+0%"}]
    (project_dir / "phonetics.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    request = {"base_version": 1, "kind": "pronunciation_replace",
               "target": {"segment_id": "stable-segment", "expected_text": "शब्द"},
               "operation": {"replacement": "शब्‍द"}, "reason": "paper note 4"}
    preview = client.post("/api/projects/book/corrections/preview", headers=headers, json=request)
    assert preview.status_code == 200, preview.json()
    assert "शब्‍द" in preview.json()["after"]
    applied = client.post("/api/projects/book/corrections", headers=headers, json=request)
    assert applied.status_code == 200
    assert applied.json()["new_version"] == 2
    saved = json.loads((project_dir / "phonetics.json").read_text(encoding="utf-8"))
    assert saved[0]["pronunciation_text"] == "यह शब्‍द है।"
    assert db_session.query(Correction).count() == 1
    stale = client.post("/api/projects/book/corrections", headers=headers, json=request)
    assert stale.status_code == 409


def test_correction_rejects_ambiguous_or_changed_target(client, db_session, tmp_path, monkeypatch):
    import api
    monkeypatch.setattr(api, "PROJECTS_DIR", str(tmp_path))
    auth = client.post("/api/signup", json={"username": "editor2", "password": "pw"}).json()
    headers = {"Authorization": f"Bearer {auth['token']}"}
    db_session.add(Project(name="book", assigned_to=auth["user_id"], version=1))
    db_session.commit()
    path = tmp_path / "book" / "02_phonetics"
    path.mkdir(parents=True)
    (path / "phonetics.json").write_text(json.dumps([{"id": "x", "source_text": "नया", "pronunciation_text": "नया"}], ensure_ascii=False), encoding="utf-8")
    response = client.post("/api/projects/book/corrections/preview", headers=headers, json={
        "base_version": 1, "kind": "pronunciation_replace",
        "target": {"segment_id": "x", "expected_text": "पुराना"},
        "operation": {"replacement": "नवीन"}})
    assert response.status_code == 409
