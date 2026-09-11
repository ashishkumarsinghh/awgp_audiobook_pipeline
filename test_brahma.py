import fitz
import re
import difflib
from src.normalize.text_cleaner import apply_shantikunj_rules, fix_ocr_punctuation

def test_brahma_sandhya():
    pdf_path = '/home/ashish/projects/awgp_audiobook_pipeline/brahma_sandhya.pdf'
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return
        
    raw_text = ""
    # Extract first 10 pages or all if less
    for i in range(min(10, len(doc))):
        raw_text += f"\n--- PAGE {i+1} ---\n"
        raw_text += doc[i].get_text() + "\n"
        
    cleaned = fix_ocr_punctuation(raw_text)
    cleaned = apply_shantikunj_rules(cleaned)
    
    # Save the cleaned text for the user to compare
    with open('/home/ashish/projects/awgp_audiobook_pipeline/brahma_sandhya_cleaned.txt', 'w', encoding='utf-8') as f:
        f.write(cleaned)
        
    # Generate diff report for deviations
    with open('/home/ashish/projects/awgp_audiobook_pipeline/brahma_sandhya_deviations.md', 'w', encoding='utf-8') as f:
        f.write('# Brahma Sandhya Gayatri - Normalization Deviations\n\n')
        
        diff = list(difflib.ndiff(raw_text.splitlines(), cleaned.splitlines()))
        changes = 0
        f.write('`diff\n')
        for line in diff:
            if line.startswith('- ') or line.startswith('+ '):
                f.write(line + '\n')
                changes += 1
        f.write('`\n\n')
        f.write(f'Total lines modified by normalizer: {changes // 2}\n')
        
        if len(raw_text.strip()) < 100:
            f.write('\n\n**WARNING:** The extracted text is very short. This PDF is likely a scanned image and REQUIRES the OCR module to be implemented first to get real text.\n')

if __name__ == '__main__':
    test_brahma_sandhya()
    print('Test complete.')