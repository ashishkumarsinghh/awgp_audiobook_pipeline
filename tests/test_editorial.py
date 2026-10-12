"""Real-file, real-FFmpeg editorial round trips; no network/TTS credentials."""
from dataclasses import replace
import json
import math
from pathlib import Path
import struct
from types import SimpleNamespace
import wave

import pytest

from src.core.artifacts import write_json
from src.core.corrections import remove_segments
from src.editorial.manuscript import Passage, parse, render, compile_passages
from src.editorial.workspace import Workspace, read_json
from src.normalize.pronunciation import PronunciationDictionary


class FakeTTS:
    voice = "test-voice"
    def __init__(self):
        self.calls = []
        self.fail = False

    async def synthesize(self, segment, output):
        self.calls.append(segment.pronunciation_text)
        if self.fail:
            raise RuntimeError("simulated provider failure")
        # Different input yields different valid audio for comparison/caching tests.
        hz = 200 + sum(map(ord, segment.pronunciation_text)) % 300
        with wave.open(str(output), "wb") as stream:
            stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            stream.writeframes(b"".join(struct.pack("<h", int(4000 * math.sin(2*math.pi*hz*i/24000))) for i in range(12000)))
        return str(output)


@pytest.fixture
def book(tmp_path):
    ws = Workspace(tmp_path / "book")
    manager = SimpleNamespace(tts=FakeTTS(), tts_provider="google", pronunciation=PronunciationDictionary(),
                              audio_dir=str(ws.root / "05_audio_chunks"), profile=SimpleNamespace(mastering_speed=1.0))
    ws.settings(provider="google", voice="test-voice", speed=1, eq="flat", required_approvals=2)
    ws.save(render([Passage("a", "मुगल सल्तनत का विस्तार।", "35", "37", pause=200),
                    Passage("b", "दूसरा वाक्य यहाँ है।", "36", "38", pause=300)]))
    return ws, manager


def edit(ws, pid, **changes):
    passages = parse(ws.manuscript.read_text(encoding="utf-8"))
    ws.save(render([replace(p, **changes) if p.id == pid else p for p in passages]))


def test_manuscript_round_trip_and_errors():
    original = Passage("a", "मूल पाठ\nदूसरी पंक्ति", "iv", "4", speech="उच्चारण")
    assert parse(render([original])) == [original]
    with pytest.raises(ValueError, match="duplicate passage ID"):
        parse(render([original, original]))
    with pytest.raises(ValueError, match="unknown or duplicate"):
        parse(render([original]).replace("RATE:", "TYPO:"))
    with pytest.raises(ValueError, match="exactly one"):
        parse(render([original]) + "\nSSML:\n<speak>text</speak>")


def test_ocr_uncertainty_can_be_edited_but_not_spoken():
    p = parse(render([Passage("a", "[अस्पष्ट]")]))
    with pytest.raises(ValueError, match="unresolved OCR"):
        compile_passages(p, PronunciationDictionary(), "google")


def test_ssml_is_explicit_validated_and_wrapped():
    p = Passage("a", "उलझनें", speech='<sub alias="उल्झनें">उलझनें</sub>', mode="SSML")
    assert compile_passages([p], PronunciationDictionary(), "google")[0]["pronunciation_text"].startswith("<speak>")
    with pytest.raises(ValueError, match="does not accept"):
        compile_passages([p], PronunciationDictionary(), "edge")
    with pytest.raises(ValueError, match="Malformed"):
        compile_passages([replace(p, speech="<break>")], PronunciationDictionary(), "azure")
    with pytest.raises(ValueError, match="Unsupported SSML element"):
        compile_passages([replace(p, speech='<audio src="http://example.com">x</audio>')], PronunciationDictionary(), "google")


def test_overlapping_override_requires_acknowledgement_and_undo(book):
    ws, _ = book
    edit(ws, "a", speech="spoken override")
    old = ws.manuscript.read_text(encoding="utf-8")
    ws.manuscript.write_text(old.replace("मुगल सल्तनत", "नया पाठ"), encoding="utf-8")
    with pytest.raises(ValueError, match="override did not"):
        ws.save()
    ws.undo()
    assert ws.manuscript.read_text(encoding="utf-8") == old
    ws.save(old.replace("मुगल सल्तनत", "नया पाठ"), accept_speech=True)


def test_build_cache_pause_preview_and_fresh_take(book):
    ws, manager = book
    first = ws.build(manager)
    assert len(manager.tts.calls) == 2
    # Boundary pause changes only assembly.
    edit(ws, "a", pause=1000)
    second = ws.build(manager)
    assert len(manager.tts.calls) == 2
    assert second["offsets"][1]["start_seconds"] > first["offsets"][1]["start_seconds"]
    edit(ws, "b", speech="नई आवाज़")
    preview = ws.preview(manager, "b", context=False)
    assert preview.exists()
    assert len(manager.tts.calls) == 3
    ws.build(manager)
    assert len(manager.tts.calls) == 3  # preview audio reused
    edit(ws, "b", take=1)
    ws.build(manager)
    assert len(manager.tts.calls) == 4


def test_two_feedback_rounds_old_timestamps_and_approval_withdrawal(book, tmp_path):
    ws, manager = book
    first = ws.build(manager)
    assert ws.submit(manager)["id"] == "v1"
    old_time = first["offsets"][1]["start_seconds"]
    issue = ws.issue("v1", "a", "Wrong pronunciation", "checker1")
    edit(ws, "a", speech="मुगल सल्तनत", pause=1500)
    assert ws.issues("v1")[0]["status"] == "open"  # save is not a submitted fix
    with pytest.raises(ValueError, match="changed since"):
        ws.submit(manager)
    second = ws.build(manager)
    ws.submit(manager)
    assert ws.issues("v2")[0]["status"] == "ready_to_recheck"
    assert ws.locate(f"0:{old_time:05.2f}", "v1")[0]["id"] == "b"
    assert ws.locate(f"0:{old_time:05.2f}", "v2")[0]["id"] == "a"
    ws.resolve(issue["id"], "v2", "verified", "checker1")
    ws.decide("v2", "checker1", "approved")
    with pytest.raises(ValueError, match="2 current approvals"):
        ws.export(tmp_path / "book.mp3", "v2")
    ws.decide("v2", "checker2", "approved")
    ws.decide("v2", "checker1", "changes_requested")
    with pytest.raises(ValueError, match="current approvals"):
        ws.export(tmp_path / "book.mp3", "v2")
    ws.decide("v2", "checker1", "approved")
    assert ws.export(tmp_path / "book.mp3", "v2").exists()
    # A second correction invalidates verification; original audio stays unchanged.
    edit(ws, "a", speech="मुगल सल्तनत का विस्तार")
    ws.build(manager)
    ws.submit(manager)
    assert ws.issues("v3")[0]["status"] == "ready_to_recheck"
    ws.check_build(first)
    ws.check_build(second)
    late = ws.issue("v1", "b", "Late feedback on older version", "checker2")
    assert any(i["id"] == late["id"] for i in ws.issues("v3"))


def test_split_join_feedback_lineage_and_ambiguous_search(book):
    ws, manager = book
    ws.build(manager)
    ws.submit(manager)
    ws.issue("v1", "a", "Check boundary", "checker")
    ws.split("a", "का विस्तार")
    children = parse(ws.manuscript.read_text(encoding="utf-8"))[:2]
    assert all("a" in p.parents.split() for p in children)
    assert ws.choose(children[0].id)["id"] == children[0].id
    ws.build(manager)
    ws.submit(manager)
    state = ws.issues("v2")[0]
    assert state["current_passages"] == [p.id for p in children]
    ws.join(children[0].id, children[1].id)
    joined = parse(ws.manuscript.read_text(encoding="utf-8"))[0]
    assert "a" in joined.parents.split()
    with pytest.raises(ValueError, match="Choose an exact"):
        ws.choose("")


def test_identical_passages_generate_once(book):
    ws, manager = book
    edit(ws, "b", text="मुगल सल्तनत का विस्तार।")
    ws.build(manager)
    assert len(manager.tts.calls) == 1


def test_failed_generation_preserves_last_build(book):
    ws, manager = book
    first = ws.build(manager)
    edit(ws, "a", speech="बदला हुआ पाठ")
    manager.tts.fail = True
    with pytest.raises(RuntimeError, match="incomplete"):
        ws.build(manager)
    assert ws.build_record()["id"] == first["id"]
    ws.check_build(first)


def test_source_rules_are_not_removal_rules():
    data = [{"id": "x", "source_text": "same phrase"}]
    assert remove_segments(data, {"corrections": [{"stage": "segment", "kind": "ocr_correction", "find": "same", "replace": "other", "approved": True}]}) == data


def test_import_preserves_existing_edits_and_page_offset(book):
    ws, manager = book
    other = Workspace(ws.root.parent / "legacy")
    data = [{"id": "chunk_0001", "source_text": "मूल", "page": 37, "pronunciation_text": "उच्चारण",
             "rate": "-5%", "pause_after_ms": 950}]
    write_json(other.root / "01_segments" / "segments.json", data)
    write_json(other.root / "02_phonetics" / "phonetics.json", data)
    other.initialize(manager, page_offset=2)
    p = parse(other.manuscript.read_text(encoding="utf-8"))[0]
    assert (p.page, p.pdf_page, p.speech, p.rate, p.pause) == ("35", "37", "उच्चारण", "-5%", 950)
    before = other.manuscript.read_bytes()
    other.initialize(manager, page_offset=10)
    assert other.manuscript.read_bytes() == before


def test_project_page_map_handles_front_matter_and_unnumbered_pages(book):
    ws, _ = book
    (ws.root / "page_map.json").write_text(json.dumps({"rules": [
        {"pdf_start": 1, "pdf_end": 4, "printed_start": None},
        {"pdf_start": 5, "pdf_end": 42, "printed_start": 3},
        {"pdf_start": 43, "pdf_end": 43, "printed_start": None},
    ]}), encoding="utf-8")
    from src.editorial.workspace import load_printed_page_map
    page_map = load_printed_page_map(ws.root)
    assert page_map.printed_page(1) is None
    assert page_map.printed_page(5) == "3"
    assert page_map.printed_page(41) == "39"
    assert page_map.printed_page(42) == "40"
    assert page_map.printed_page(43) is None


def test_page_map_override_is_persisted_and_reconcile_clears_unmapped_labels(book):
    ws, _ = book
    content = render([
        Passage("a", "पहला", page="99", pdf_page="1"),
        Passage("b", "दूसरा", page="98", pdf_page="2"),
    ])
    ws.manuscript.write_text(content, encoding="utf-8")
    ws.save(content)
    from src.editorial.workspace import save_printed_page_override, load_printed_page_map
    save_printed_page_override(ws.root, 1, "iv")
    save_printed_page_override(ws.root, 2, None)
    assert load_printed_page_map(ws.root).printed_page(1) == "iv"
    assert load_printed_page_map(ws.root).printed_page(2) is None
    assert ws.reconcile_pages() == 2
    pages = {p.pdf_page: p.page for p in parse(ws.manuscript.read_text(encoding="utf-8"))}
    assert pages == {"1": "iv", "2": "?"}


def test_cli_remembers_book_and_does_not_launch_editor(book, monkeypatch, capsys):
    from src.editorial.cli import main
    ws, _ = book
    monkeypatch.chdir(ws.root.parent)
    assert main([str(ws.root), "edit", "p35", "--no-open"]) == 0
    assert main(["find", "मुगल"]) == 0
    output = capsys.readouterr().out
    assert "manuscript.txt:" in output and "PDF 37" in output
    assert main(["validate"]) == 0
    edit(ws, "a", text="peace and prosperity")
    assert ws.choose("peace")["id"] == "a"


def test_offline_feedback_import_is_atomic_idempotent_and_escaped(book, tmp_path):
    ws, manager = book
    edit(ws, "a", text='सुरक्षित </script><script>alert(1)</script> पाठ', speech="सुरक्षित पाठ")
    ws.build(manager)
    ws.submit(manager)
    page = (ws.home / "reviews" / "v1" / "index.html").read_text(encoding="utf-8")
    assert "</script><script>alert(1)" not in page
    assert "\\u003c/script>" in page
    assert (ws.home / "reviews" / "v1" / "audiobook.mp3").is_file()
    payload = {"version": "v1", "build": ws.version("v1")["build"], "reporter": "checker", "notes": [
        {"passage": "a", "body": "Wrong word"}, {"passage": "nonexistent", "body": "bad anchor"}]}
    file = tmp_path / "feedback.json"
    write_json(file, payload)
    with pytest.raises(ValueError, match="known passage"):
        ws.import_feedback(file)
    assert ws.issues() == []
    payload["notes"].pop()
    write_json(file, payload)
    assert ws.import_feedback(file) == 1
    assert ws.import_feedback(file) == 0
    assert ws.locate("i1")[0]["id"] == "a"
    edit(ws, "a", speech="सुधारा हुआ पाठ")
    ws.build(manager)
    ws.submit(manager)
    payload.update(version="v2", build=ws.version("v2")["build"], notes=[{"issue": "i1", "status": "verified"}])
    write_json(file, payload)
    assert ws.import_feedback(file) == 1
    assert ws.issues()[0]["status"] == "verified"


def test_embedded_pdf_import_and_reocr_do_not_overwrite_manuscript(tmp_path, monkeypatch):
    import fitz
    from src.pipeline_v3 import ProjectManager
    import src.extract.ocr_engine as ocr
    monkeypatch.setattr(ocr, "get_gemini_client", lambda: None)
    pdf = tmp_path / "book.pdf"
    with fitz.open() as doc:
        p = doc.new_page()
        p.insert_text((72, 120), "This is the original text of a sufficiently long paragraph in a test book.")
        doc.save(pdf)
    manager = ProjectManager(str(tmp_path / "project"))
    ws = Workspace(manager.project_dir)
    ws.intake(pdf, manager)
    content = ws.manuscript.read_text(encoding="utf-8")
    assert "original text" in content
    ws.save(content.replace("original text", "corrected text"))
    corrected = ws.manuscript.read_bytes()
    comparison = ws.intake(pdf, manager, reocr=True, pages=[1])
    assert comparison.is_file()
    assert ws.manuscript.read_bytes() == corrected


def test_mixed_pdf_prefers_embedded_and_ocr_only_for_scan(tmp_path, monkeypatch):
    import fitz
    import src.extract.ocr_engine as ocr
    pdf = tmp_path / "mixed.pdf"
    with fitz.open() as doc:
        p = doc.new_page()
        p.insert_text((72, 120), "A long embedded paragraph that should be extracted without making any OCR request.")
        doc.new_page()
        doc.save(pdf)
    monkeypatch.setattr(ocr, "get_gemini_client", lambda: object())
    called = []
    def fake_ocr(client, images, pages):
        called.extend(pages)
        return ["<prose>Scanned second page.</prose>"]
    monkeypatch.setattr(ocr, "_transcribe_page_batch", fake_ocr)
    monkeypatch.setattr(ocr.time, "sleep", lambda _: None)
    result = ocr.extract_text_from_pdf(str(pdf), prefer_embedded=True)
    assert called == [2]
    assert "long embedded" in result and "Scanned second" in result


def test_new_workflow_rejects_stale_legacy_cli(book, monkeypatch):
    from src.pipeline_v3 import main
    ws, _ = book
    monkeypatch.setattr("sys.argv", ["run.py", str(ws.root), "2"])
    with pytest.raises(SystemExit, match="legacy stage commands are disabled"):
        main()


def test_migrated_web_mutations_are_blocked(client, db_session, tmp_path, monkeypatch):
    import api
    from src.db.models import Project
    monkeypatch.setattr(api, "PROJECTS_DIR", str(tmp_path))
    auth = client.post("/api/signup", json={"username": "migration-editor", "password": "pw"}).json()
    db_session.add(Project(name="book", assigned_to=auth["user_id"]))
    db_session.commit()
    (tmp_path / "book").mkdir()
    (tmp_path / "book" / "manuscript.txt").write_text(render([Passage("a", "पाठ")]), encoding="utf-8")
    response = client.post("/api/projects/book/stage/all", headers={"Authorization": f"Bearer {auth['token']}"})
    assert response.status_code == 409
    assert "manuscript" in response.json()["detail"]


def test_preview_allows_unresolved_ocr_elsewhere(book):
    ws, manager = book
    edit(ws, "b", text="[अस्पष्ट]")
    assert ws.preview(manager, "a", context=False).exists()
    with pytest.raises(ValueError, match="unresolved OCR"):
        ws.build(manager)


def test_review_pack_dom_smoke(book):
    import shutil
    import subprocess
    root = Path(__file__).resolve().parents[1]
    if not shutil.which("node") or not (root / "frontend/node_modules/jsdom").exists():
        pytest.skip("Node and frontend jsdom are optional for the checker DOM smoke test")
    ws, manager = book
    ws.build(manager)
    ws.submit(manager)
    result = subprocess.run(["node", str(root / "tests/check_review_pack.cjs"), str(ws.home / "reviews/v1/index.html")],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_azure_transports_authored_ssml_instead_of_stripping_it(tmp_path, monkeypatch):
    import asyncio
    from src.synthesis.providers import AzureSpeechProvider
    from src.core.types import SpeechSegment
    captured = []
    output = tmp_path / "speech.wav"
    class Synthesizer:
        def __init__(self, **kwargs):
            pass
        def speak_ssml_async(self, text):
            captured.append(text)
            output.write_bytes(b"test")
            return SimpleNamespace(get=lambda: SimpleNamespace(reason="completed"))
    sdk = SimpleNamespace(audio=SimpleNamespace(AudioOutputConfig=lambda **kwargs: object()),
                          SpeechSynthesizer=Synthesizer,
                          ResultReason=SimpleNamespace(SynthesizingAudioCompleted="completed"))
    provider = AzureSpeechProvider()
    monkeypatch.setattr(provider, "_speech_config", lambda: (sdk, object()))
    segment = SpeechSegment("पाठ", "पाठ", '<speak><sub alias="पाठ">पाठ</sub><break time="250ms"/></speak>')
    asyncio.run(provider.synthesize(segment, str(output)))
    assert '<break time="250ms"' in captured[0] and '<sub alias="पाठ"' in captured[0]
    assert captured[0].count('<speak') == 1
