import re

def fix_ocr_punctuation(text: str) -> str:
    # Converts English pipe characters to Hindi dandas
    text = text.replace('||', '॥')
    text = text.replace('|', '।')
    return text

def apply_shantikunj_rules(text: str) -> str:
    # Standardize classical half-consonants to anusvara
    replacements = {
        'ङ्क': 'ंक', 'ञ्च': 'ंच', 'ण्ड': 'ंड', 'न्त': 'ंत', 'म्प': 'ंप',
        'शान्त': 'शांत', 'सम्पत्ति': 'संपत्ति'
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
        
    # Fix OCR artifacts where spaces are inserted before matras
    text = re.sub(r'\s+([ािीुूेैोौंँः])', r'\1', text)
    return text