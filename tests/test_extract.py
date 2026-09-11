import os
import pytest
from dotenv import load_dotenv
from src.extract.ocr_engine import extract_text_from_pdf

def test_extract_scanned_pdf():
    # Load environment variables (API Key)
    load_dotenv()
    
    pdf_path = '/home/ashish/projects/awgp_audiobook_pipeline/brahma_sandhya.pdf'
    
    # Ensure the file exists before testing
    assert os.path.exists(pdf_path)
    
    # Extract just the first page to keep the test fast
    text = extract_text_from_pdf(pdf_path, max_pages=1)
    
    # The text should no longer be blank
    assert len(text.strip()) > 50
    # It should contain some Hindi characters
    assert any('\u0900' <= char <= '\u097F' for char in text)