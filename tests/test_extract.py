from unittest.mock import patch, MagicMock
import fitz
import pytest
from src.extract.ocr_engine import extract_text_from_pdf


def pdf_file(tmp_path, texts):
    path = tmp_path / "book.pdf"
    with fitz.open() as doc:
        for text in texts:
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), text)
        doc.save(path)
    return path


def test_ocr_engine_mocked(tmp_path):
    path = pdf_file(tmp_path, ["A page"])
    client = MagicMock()
    client.models.generate_content.return_value.text = "<prose>Transcription.</prose>"
    with patch("src.extract.ocr_engine.get_gemini_client", return_value=client):
        assert extract_text_from_pdf(str(path)) == "<prose>Transcription.</prose>"
    assert client.models.generate_content.call_count == 1


def test_invalid_pdf_is_not_sent_to_model(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"invalid")
    with patch("src.extract.ocr_engine.get_gemini_client") as client:
        with pytest.raises(ValueError, match="Cannot open PDF"):
            extract_text_from_pdf(str(path))
        client.assert_not_called()


def test_local_page_limit_and_scanned_page_error(tmp_path):
    path = pdf_file(tmp_path, ["Page one.", ""])
    with patch("src.extract.ocr_engine.get_gemini_client", return_value=None):
        assert extract_text_from_pdf(str(path), max_pages=1) == "Page one."
        with pytest.raises(RuntimeError, match="Page 2.*GEMINI_API_KEY"):
            extract_text_from_pdf(str(path))


def test_empty_cloud_response_identifies_page(tmp_path):
    path = pdf_file(tmp_path, ["A"])
    client = MagicMock()
    client.models.generate_content.return_value.text = ""
    with patch("src.extract.ocr_engine.get_gemini_client", return_value=client):
        with pytest.raises(RuntimeError, match="page 1.*empty OCR"):
            extract_text_from_pdf(str(path))


def test_invalid_page_limit(tmp_path):
    with pytest.raises(ValueError, match="positive integer"):
        extract_text_from_pdf(str(tmp_path / "book.pdf"), 0)
