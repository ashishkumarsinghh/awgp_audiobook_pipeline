import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.pipeline_v3 import ProjectManager, parse_stage, main
from src.extract.ocr_engine import extract_text_from_pdf
from tests.test_pipeline import create_fake_wav


def test_parse_stage_mappings():
    assert parse_stage("0") == 0
    assert parse_stage("ocr") == 0
    assert parse_stage("1") == 1
    assert parse_stage("segmentation") == 1
    assert parse_stage("segment") == 1
    assert parse_stage("2") == 2
    assert parse_stage("phonetics") == 2
    assert parse_stage("3") == 3
    assert parse_stage("audio") == 3
    assert parse_stage("4") == 4
    assert parse_stage("mastering") == 4
    assert parse_stage("5") == 5
    assert parse_stage("speed") == 5
    assert parse_stage("tempo") == 5
    assert parse_stage("flow") == 5
    assert parse_stage("6") == 6
    assert parse_stage("metadata") == 6
    assert parse_stage("tag") == 6
    assert parse_stage("tags") == 6
    assert parse_stage("export") == 6
    assert parse_stage("package") == 6

    with pytest.raises(ValueError, match="Unknown stage"):
        parse_stage("unknown_stage")


def test_ocr_checkpoint_and_resuming(tmp_path):
    project_dir = tmp_path / "test_book"
    pm = ProjectManager(str(project_dir), book_name="gita_mahatmya")
    assert pm.book_name == "gita_mahatmya"

    # Create dummy PDF
    import fitz
    doc = fitz.open()
    for text in ["Page one content.", "Page two content.", "Page three content."]:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(pm.pdf_file)
    doc.close()

    # Run OCR with local extraction
    with patch("src.extract.ocr_engine.get_gemini_client", return_value=None):
        out = pm.run_stage_1_ocr(max_pages=2)

    assert os.path.exists(out)
    assert "Page one content." in Path(out).read_text()
    assert "Page two content." in Path(out).read_text()

    # Verify page checkpoints exist
    page1_cp = Path(pm.ocr_checkpoints_dir) / "gita_mahatmya_page_0001.txt"
    page2_cp = Path(pm.ocr_checkpoints_dir) / "gita_mahatmya_page_0002.txt"
    assert page1_cp.exists()
    assert page2_cp.exists()

    # Check that timestamped artifact was saved in artifacts/
    artifacts = list(Path(pm.artifacts_dir).glob("gita_mahatmya_00_ocr_raw_cli_*.txt"))
    assert len(artifacts) >= 1

    # Modify page 1 checkpoint to simulate editing a checkpoint, and run again to verify resume
    page1_cp.write_text("Edited Page One from Checkpoint.")
    with patch("src.extract.ocr_engine.get_gemini_client", return_value=None):
        out2 = pm.run_stage_1_ocr(max_pages=2)

    assert "Edited Page One from Checkpoint." in Path(out2).read_text()


def test_segmentation_with_edited_input_file(tmp_path):
    project_dir = tmp_path / "test_book"
    pm = ProjectManager(str(project_dir), book_name="upanishad")

    # Write a custom edited text file outside or inside project dir
    custom_edited_txt = tmp_path / "my_custom_edited.txt"
    custom_edited_txt.write_text("<heading>पहला अध्याय</heading>\n<prose>यह एक परीक्षण वाक्य है। यह दूसरा वाक्य है।</prose>", encoding="utf-8")

    # Run stage 1 pointing directly to the edited text
    out_segments = pm.run_stage_1_segmentation(input_text_file=str(custom_edited_txt))
    assert os.path.exists(out_segments)

    data = json.loads(Path(out_segments).read_text(encoding="utf-8"))
    assert len(data) >= 1
    assert any("पहला अध्याय" in d["source_text"] for d in data)

    # Check timestamped artifact in artifacts/
    artifacts = list(Path(pm.artifacts_dir).glob("upanishad_02_segments_cli_*.json"))
    assert len(artifacts) >= 1


def test_phonetics_with_edited_segments_input(tmp_path):
    project_dir = tmp_path / "test_book"
    pm = ProjectManager(str(project_dir), book_name="vedas")

    custom_segments = tmp_path / "custom_segments.json"
    segments_data = [
        {"id": "chunk_0001", "source_text": "ॐ भूर्भुवः स्वः", "segment_type": "shloka", "pause_after_ms": 800},
        {"id": "chunk_0002", "source_text": "तत्सवितुर्वरेण्यं", "segment_type": "shloka", "pause_after_ms": 800}
    ]
    custom_segments.write_text(json.dumps(segments_data, ensure_ascii=False), encoding="utf-8")

    out_phonetics = pm.run_stage_2_phonetics(input_segments_file=str(custom_segments))
    assert os.path.exists(out_phonetics)

    data = json.loads(Path(out_phonetics).read_text(encoding="utf-8"))
    assert len(data) == 2
    # Verify pronunciation rules applied
    assert "ओम्" in data[0]["pronunciation_text"]
    assert "तत् सवितुर" in data[1]["pronunciation_text"]

    artifacts = list(Path(pm.artifacts_dir).glob("vedas_03_phonetics_cli_*.json"))
    assert len(artifacts) >= 1


def test_audio_and_mastering_with_edited_input(tmp_path):
    project_dir = tmp_path / "test_book"
    pm = ProjectManager(str(project_dir), book_name="mahabharat")

    custom_phonetics = tmp_path / "custom_phonetics.json"
    phonetics_data = [
        {
            "id": "chunk_0001",
            "source_text": "पहला श्लोक",
            "pronunciation_text": "पहला श्लोक",
            "segment_type": "shloka",
            "rate": "-10%",
            "pitch": "-2Hz",
            "volume": "+0%",
            "pause_before_ms": 0,
            "pause_after_ms": 800
        },
        {
            "id": "chunk_0002",
            "source_text": "दूसरा श्लोक",
            "pronunciation_text": "दूसरा श्लोक",
            "segment_type": "shloka",
            "rate": "-10%",
            "pitch": "-2Hz",
            "volume": "+0%",
            "pause_before_ms": 0,
            "pause_after_ms": 800
        }
    ]
    custom_phonetics.write_text(json.dumps(phonetics_data, ensure_ascii=False), encoding="utf-8")

    # Mock TTS synthesize
    async def mock_synth(segment, output_path):
        create_fake_wav(output_path, 200)
        return output_path

    with patch.object(pm.tts, "synthesize", side_effect=mock_synth):
        audio_dir = pm.run_stage_3_audio(input_phonetics_file=str(custom_phonetics))

    assert os.path.exists(Path(audio_dir) / "chunk_0001.wav")
    assert os.path.exists(Path(audio_dir) / "chunk_0002.wav")
    assert os.path.exists(Path(audio_dir) / "manifest.json")

    # Verify manifest artifact was archived
    manifest_artifacts = list(Path(pm.artifacts_dir).glob("mahabharat_04_audio_manifest_cli_*.json"))
    assert len(manifest_artifacts) >= 1

    # Now test mastering
    def mock_master(src, dest, **kwargs):
        Path(dest).write_bytes(b"MASTERED_AUDIO_TEST")

    with patch("src.synthesis.assembler.AudioEnhancer.apply_studio_mastering", side_effect=mock_master):
        master_out = pm.run_stage_4_mastering(input_phonetics_file=str(custom_phonetics))

    assert os.path.exists(master_out)
    assert Path(master_out).read_bytes() == b"MASTERED_AUDIO_TEST"

    # Verify master artifact in artifacts/
    master_artifacts = list(Path(pm.artifacts_dir).glob("mahabharat_05_mastered_cli_*.mp3"))
    assert len(master_artifacts) >= 1


def test_cli_main_argument_dispatching(tmp_path, monkeypatch):
    project_dir = tmp_path / "cli_book"
    pm = ProjectManager(str(project_dir), book_name="ramayana")

    # Create dummy segments
    seg_file = tmp_path / "my_segs.json"
    seg_file.write_text(json.dumps([
        {"id": "chunk_0001", "source_text": "नमस्ते", "segment_type": "prose", "pause_after_ms": 300}
    ]), encoding="utf-8")

    # Test running CLI stage 2 with --input
    test_args = [
        "pipeline_v3",
        "--project", str(project_dir),
        "--book-name", "ramayana",
        "--stage", "phonetics",
        "--input", str(seg_file)
    ]
    monkeypatch.setattr("sys.argv", test_args)
    main()

    # Verify 04_phonetics.json was generated in project_dir
    assert (project_dir / "04_phonetics.json").exists()
    phonetics_content = json.loads((project_dir / "04_phonetics.json").read_text(encoding="utf-8"))
    assert phonetics_content[0]["id"] == "chunk_0001"


def test_stage_subfolder_edits_auto_picked(tmp_path):
    """Test that editing files directly inside stage subfolders is picked up by subsequent stages without any --input flag."""
    project_dir = tmp_path / "subfolder_book"
    pm = ProjectManager(str(project_dir), book_name="subfolder_book")

    # 1. Simulate human editing text in 00_ocr/text_cleaned.txt
    ocr_cleaned = Path(pm.stage0_dir) / "text_cleaned.txt"
    ocr_cleaned.write_text("<heading>अध्याय एक</heading>\n<prose>मानव जीवन दुर्लभ है।</prose>", encoding="utf-8")

    # 2. Run Stage 1 with NO arguments: should pick up from 00_ocr/text_cleaned.txt
    out_seg = pm.run_stage_1_segmentation()
    assert os.path.exists(out_seg)
    stage1_json = Path(pm.stage1_dir) / "segments.json"
    assert stage1_json.exists()
    segments = json.loads(stage1_json.read_text(encoding="utf-8"))
    assert any("मानव जीवन दुर्लभ है" in s["source_text"] for s in segments)

    # 3. Simulate human editing segments in 01_segments/segments.json
    segments[0]["source_text"] = "मानव जीवन अत्यंत दुर्लभ है।"
    stage1_json.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")

    # 4. Run Stage 2 with NO arguments: should pick up from 01_segments/segments.json
    out_ph = pm.run_stage_2_phonetics()
    assert os.path.exists(out_ph)
    stage2_json = Path(pm.stage2_dir) / "phonetics.json"
    assert stage2_json.exists()
    phonetics = json.loads(stage2_json.read_text(encoding="utf-8"))
    assert phonetics[0]["source_text"] == "मानव जीवन अत्यंत दुर्लभ है।"


def test_run_py_positional_syntax(tmp_path, monkeypatch):
    """Test minimal verbosity execution: python run.py <book> <stage>"""
    import run
    project_dir = tmp_path / "projects" / "minimal_book"
    os.makedirs(project_dir, exist_ok=True)
    pm = ProjectManager(str(project_dir), book_name="minimal_book")

    # Provide text in 00_ocr/ocr_raw.txt
    (Path(pm.stage0_dir) / "ocr_raw.txt").write_text("<prose>सरल वाक्य।</prose>", encoding="utf-8")

    # Run: python run.py minimal_book 1
    monkeypatch.setattr("sys.argv", ["run.py", str(project_dir), "1"])
    run.main()

    # Check that 01_segments/segments.json was generated
    assert (Path(pm.stage1_dir) / "segments.json").exists()

    # Run: python run.py minimal_book 2
    monkeypatch.setattr("sys.argv", ["run.py", str(project_dir), "2"])
    run.main()

    # Check that 02_phonetics/phonetics.json was generated
    assert (Path(pm.stage2_dir) / "phonetics.json").exists()


def test_stage_5_speed_execution(tmp_path):
    """Test Stage 5 speed & tempo optimization logic."""
    project_dir = tmp_path / "speed_book"
    pm = ProjectManager(str(project_dir), book_name="speed_book")

    master_path = Path(pm.stage4_dir) / "mastered.mp3"
    master_path.write_bytes(b"ORIGINAL_MASTERED_AUDIO")

    recorded_calls = []

    def mock_apply_speed(in_file, out_file, speed=1.15, **kwargs):
        recorded_calls.append((in_file, out_file, speed))
        Path(out_file).write_bytes(b"TEMPO_OPTIMIZED_AUDIO")

    with patch("src.synthesis.audio.enhancer.AudioEnhancer.apply_speed", side_effect=mock_apply_speed):
        # 1. Default speed (1.15x)
        out1 = pm.run_stage_5_speed()
        assert os.path.exists(out1)
        assert len(recorded_calls) == 1
        assert recorded_calls[0][2] == 1.15
        assert Path(out1).read_bytes() == b"TEMPO_OPTIMIZED_AUDIO"

        # Verify artifact created
        speed_artifacts = list(Path(pm.artifacts_dir).glob("speed_book_06_speed_115x_cli_*.mp3"))
        assert len(speed_artifacts) >= 1

        # 2. Custom speed (1.25x)
        out2 = pm.run_stage_5_speed(speed=1.25)
        assert recorded_calls[-1][2] == 1.25
        speed_artifacts_125 = list(Path(pm.artifacts_dir).glob("speed_book_06_speed_125x_cli_*.mp3"))
        assert len(speed_artifacts_125) >= 1


def test_cli_stage_5_speed_dispatch(tmp_path, monkeypatch):
    """Test CLI invocation of Stage 5 with positional argument and --speed flag."""
    project_dir = tmp_path / "cli_speed_book"
    pm = ProjectManager(str(project_dir), book_name="cli_speed_book")

    master_path = Path(pm.stage4_dir) / "mastered.mp3"
    master_path.write_bytes(b"DUMMY_AUDIO")

    called_speed = []

    def mock_apply_speed(in_file, out_file, speed=1.15, **kwargs):
        called_speed.append(speed)
        Path(out_file).write_bytes(b"ADJUSTED_AUDIO")

    with patch("src.synthesis.audio.enhancer.AudioEnhancer.apply_speed", side_effect=mock_apply_speed):
        # Test: python run.py cli_speed_book 5 --speed 1.20
        test_args = ["run.py", str(project_dir), "5", "--speed", "1.20"]
        monkeypatch.setattr("sys.argv", test_args)
        main()

        assert len(called_speed) == 1
        assert called_speed[0] == 1.20


def test_stage_6_metadata_execution(tmp_path):
    """Test Stage 6 ID3 metadata tagging and export naming."""
    project_dir = tmp_path / "meta_book"
    pm = ProjectManager(str(project_dir), book_name="meta_book")

    master_path = Path(pm.stage4_dir) / "mastered.mp3"
    master_path.write_bytes(b"DUMMY_AUDIO_DATA")

    # Add dummy segments.json to test title resolution
    seg_file = Path(pm.stage1_dir) / "segments.json"
    seg_file.write_text(json.dumps([
        {"id": "chunk_0001", "source_text": "अध्याय एक: सत्य का मार्ग", "segment_type": "heading"}
    ], ensure_ascii=False), encoding="utf-8")

    meta_applied = {}

    def mock_apply_metadata(in_file, out_file, metadata=None, **kwargs):
        meta_applied.update(metadata or {})
        Path(out_file).write_bytes(b"TAGGED_AUDIO_DATA")
        return out_file

    with patch("src.synthesis.audio.enhancer.AudioEnhancer.apply_metadata", side_effect=mock_apply_metadata):
        # 1. Resolve and apply default metadata
        out1 = pm.run_stage_6_metadata()
        assert os.path.exists(out1)
        assert os.path.basename(out1) == "meta_book.mp3"
        assert meta_applied["title"] == "अध्याय एक: सत्य का मार्ग"
        assert "पं. श्रीराम शर्मा आचार्य" in meta_applied["artist"]
        assert meta_applied["genre"] == "Audiobook"

        # 2. Custom metadata overrides
        custom = {"title": "Custom Title", "artist": "Custom Author", "album": "Custom Album"}
        out2 = pm.run_stage_6_metadata(metadata=custom)
        assert meta_applied["title"] == "Custom Title"
        assert meta_applied["artist"] == "Custom Author"
        assert meta_applied["album"] == "Custom Album"


def test_cli_stage_6_metadata_dispatch(tmp_path, monkeypatch):
    """Test CLI invocation of Stage 6 with --title, --artist, --album, --year."""
    project_dir = tmp_path / "cli_meta_book"
    pm = ProjectManager(str(project_dir), book_name="cli_meta_book")

    master_path = Path(pm.stage4_dir) / "mastered.mp3"
    master_path.write_bytes(b"DUMMY_AUDIO")

    applied = {}

    def mock_apply_metadata(in_file, out_file, metadata=None, **kwargs):
        applied.update(metadata or {})
        Path(out_file).write_bytes(b"TAGGED_AUDIO")
        return out_file

    with patch("src.synthesis.audio.enhancer.AudioEnhancer.apply_metadata", side_effect=mock_apply_metadata):
        test_args = [
            "run.py", str(project_dir), "6",
            "--title", "My Custom Title",
            "--artist", "My Author",
            "--year", "2024"
        ]
        monkeypatch.setattr("sys.argv", test_args)
        main()

        assert applied["title"] == "My Custom Title"
        assert applied["artist"] == "My Author"
        assert applied["date"] == "2024"



