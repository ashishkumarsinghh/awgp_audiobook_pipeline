import sys
from dotenv import load_dotenv
from src.extract.ocr_engine import extract_text_from_pdf

def run_extraction():
    load_dotenv()
    pdf_path = '/home/ashish/projects/awgp_audiobook_pipeline/brahma_sandhya.pdf'
    print("Extracting first 3 pages using Smart Prompt (TTS Markers)...")
    text = extract_text_from_pdf(pdf_path, max_pages=3)
    
    with open('/home/ashish/projects/awgp_audiobook_pipeline/brahma_sandhya_gemini_smart.txt', 'w', encoding='utf-8') as f:
        f.write(text)
        
    print("Done! Extracted text saved.")
    
if __name__ == '__main__':
    run_extraction()