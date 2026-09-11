import fitz
import os
import io
import time
from google import genai
from google.genai import types

def extract_text_from_pdf(pdf_path: str, max_pages: int = None) -> str:
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    
    client = genai.Client(api_key=api_key)
    
    doc = fitz.open(pdf_path)
    full_text = []
    
    limit = min(max_pages, len(doc)) if max_pages else len(doc)
    
    for i in range(limit):
        page = doc.load_page(i)
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        
        prompt = (
            "You are an expert audiobook transcription engine. Extract the Hindi and Sanskrit Devanagari text from this image.\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. EXCLUDE all page numbers, headers, footers, URLs (e.g., awgp.org, akhandjyoti.org), watermarks, copyright warnings, and footnotes. Extract ONLY the main narrative.\n"
            "2. If text is a Chapter, Title, or Section Heading, wrap it in <heading> ... </heading> tags.\n"
            "3. If text is a Sanskrit Shloka, Mantra, Sutra, or poetic verse, wrap the entire block in <shloka> ... </shloka> tags.\n"
            "4. Preserve natural paragraph breaks. Do not translate. Do not fix grammar. Just return the raw extracted text."
        )
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model='gemini-3.6-flash',
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type='image/png'),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                    )
                )
                if response.text:
                    full_text.append(response.text.strip())
                break
            except Exception as e:
                if '503' in str(e) and attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    raise e
        
    return '\n\n'.join(full_text)