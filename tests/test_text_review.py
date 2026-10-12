import json

from src.qa.text_review import detect_text_anomalies, build_llm_prompt, run_text_review


def test_deterministic_detector_flags_confirmed_ocr_without_mutating_text():
    items = [{"id": "chunk_0036", "page": 14, "paragraph": 1,
              "source_text": "मन को साधिपए मन एक देवता है।"}]
    findings = detect_text_anomalies(items)
    assert findings[0]["candidate"] == "साधिये"
    assert items[0]["source_text"].endswith("साधिपए मन एक देवता है।")


def test_llm_prompt_is_conservative():
    prompt = build_llm_prompt("मन को साधिपए", "heading", "Hindi")
    assert "Return JSON candidates only" in prompt
    assert "Do not rewrite style" in prompt


def test_text_review_report_never_mutates_segments(tmp_path):
    project = tmp_path / "book" / "01_segments"
    project.mkdir(parents=True)
    (project / "segments.json").write_text(json.dumps([{
        "id": "x", "page": 1, "paragraph": 1, "source_text": "मन को साधिपए"
    }], ensure_ascii=False), encoding="utf-8")
    report = run_text_review(str(project.parent))
    assert report["status"] == "review_required"
    saved = json.loads((project / "segments.json").read_text(encoding="utf-8"))
    assert saved[0]["source_text"] == "मन को साधिपए"
