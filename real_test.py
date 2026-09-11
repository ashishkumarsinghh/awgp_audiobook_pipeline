import fitz
import re
import difflib
from src.normalize.text_cleaner import apply_shantikunj_rules, fix_ocr_punctuation

def extract_pages(pdf_path, start, end):
    doc = fitz.open(pdf_path)
    text = ''
    for i in range(start, min(end, len(doc))):
        text += doc[i].get_text() + '\n'
    return text

def test_on_real_book():
    pdf_path = '/home/ashish/projects/awgp_audiobook_pipeline/sample.pdf'
    # The book has a lot of text, let's grab pages 15 to 20
    raw_text = extract_pages(pdf_path, 15, 20)
    
    # Process
    cleaned = fix_ocr_punctuation(raw_text)
    cleaned = apply_shantikunj_rules(cleaned)
    
    # Create a diff report
    with open('/home/ashish/projects/awgp_audiobook_pipeline/normalization_report.md', 'w', encoding='utf-8') as f:
        f.write('# Normalization Real-World Test Report\n\n')
        
        diff = list(difflib.ndiff(raw_text.splitlines(), cleaned.splitlines()))
        changes_found = False
        
        f.write('## Changes Detected:\n\n`diff\n')
        for line in diff:
            if line.startswith('- ') or line.startswith('+ '):
                f.write(line + '\n')
                changes_found = True
        f.write('`\n\n')
        
        if not changes_found:
            f.write('*No OCR artifacts or Shantikunj rule violations were detected on these pages.*\n')
            
        f.write('## Raw Text Snippet (First 500 chars):\n\n`\n' + raw_text[:500] + '\n`\n\n')
        f.write('## Cleaned Text Snippet:\n\n`\n' + cleaned[:500] + '\n`\n')
        
if __name__ == '__main__':
    test_on_real_book()
    print('Report generated.')