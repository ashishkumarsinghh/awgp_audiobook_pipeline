import pytest
from unittest.mock import patch, MagicMock
from src.extract.ocr_engine import extract_text_from_pdf

def test_ocr_engine_mocked(tmp_path):
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"dummy pdf content")
    
    with patch("src.extract.ocr_engine.genai.Client") as MockClient:
        # Set up the mock chain
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        
        # Mock file upload
        mock_file = MagicMock()
        mock_file.name = "mock_file_name"
        mock_client.files.upload.return_value = mock_file
        
        # Mock file state to ACTIVE
        mock_file_state = MagicMock()
        mock_file_state.state.name = "ACTIVE"
        mock_client.files.get.return_value = mock_file_state
        
        # Mock generate_content
        mock_response = MagicMock()
        mock_response.text = "Mocked OCR Text"
        mock_client.models.generate_content.return_value = mock_response
        
        # Provide dummy API key so it doesn't fail early
        with patch.dict("os.environ", {"GEMINI_API_KEY": "fake_key"}):
            # Test extract_text_from_pdf
            # Need to mock the split_pdf function so it doesn't try to use pymupdf on dummy bytes
            with patch("src.extract.ocr_engine.split_pdf") as mock_split:
                # Return a list of fake pdf paths
                fake_chunk = tmp_path / "chunk_1.pdf"
                fake_chunk.write_bytes(b"chunk content")
                mock_split.return_value = [str(fake_chunk)]
                
                text = extract_text_from_pdf(str(pdf_path))
                assert "Mocked OCR Text" in text

def test_gemini_processor_init():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake_key"}):
        from src.extract.ocr_engine import get_gemini_client
        client = get_gemini_client()
        assert client is not None