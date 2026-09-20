"""Text normalization and OCR cleaning utilities.

Strips publishing metadata, book headers, author attributions, and running
headers/footers so only narrated content reaches synthesis.
"""
import re
from typing import Optional, List, Tuple

# OCR tag typos frequently produced by vision LLMs
TAG_TYPOS = [
    (r'<\s*pro5e\s*>', '<prose>'),
    (r'<\s*/\s*pro5e\s*>', '</prose>'),
    (r'<\s*he4ding\s*>', '<heading>'),
    (r'<\s*/\s*he4ding\s*>', '</heading>'),
    (r'<\s*subhe4ding\s*>', '<subheading>'),
    (r'<\s*/\s*subhe4ding\s*>', '</subheading>'),
]

# Metadata header titles to exclude
METADATA_HEADER_PATTERN = re.compile(
    r'^(?:लेखक|रचयिता|संपादक|संकलनकर्ता|प्रकाशक|मुद्रक|संस्करण|पुनर्मुद्रण|मूल्य|सहयोग\s*राशि|'
    r'वितरक|आईएसबीएन|ISBN|सर्वाधिकार\s*सुरक्षित|कॉपीराइट|प्रकाशकीय\s*(?:निवेदन|वक्तव्य)?)\s*[:：\-—]?\s*$',
    re.IGNORECASE
)

# Publishing metadata signatures (author, publisher, address, price, edition)
PUBLISHING_METADATA_PATTERN = re.compile(
    r'(?:युग\s*निर्माण\s*योजना|गायत्री\s*तपोभूमि|अखण्ड\s*ज्योति\s*संस्थान|'
    r'मथुरा\s*[-–—]\s*[२2][८8][१1][०0][०0][३3]|शांतिकुंज\s*,\s*हरिद्वार|'
    r'प्रथम\s*संस्करण|द्वितीय\s*संस्करण|पुनर्मुद्रण|मूल्य\s*:\s*रू|'
    r'सर्वाधिकार\s*प्रकाशकाधीन|मुद्रक\s*:\s*)',
    re.IGNORECASE
)

# Standalone author attribution lines (e.g. —श्रीराम शर्मा आचार्य)
STANDALONE_AUTHOR_PATTERN = re.compile(
    r'^[—\-–]?\s*(?:पं०\s*|पंडित\s*|श्री\s*)?श्रीराम\s*शर्मा\s*आचार्य\s*$',
    re.IGNORECASE
)

# Standalone page number patterns (e.g. ( ५ ), [ ३२ ], ) ( १५, etc.)
PAGE_NUMBER_PATTERN = re.compile(
    r'^(?:[\)\]\(\[\s—\-–|।॥]+[०-९\d]{1,4}[\)\]\(\[\s—\-–|।॥]+|[०-९\d]{1,4})$'
)


def fix_ocr_punctuation(text: str) -> str:
    """Converts English pipe characters to Hindi dandas."""
    text = text.replace('||', '॥')
    text = text.replace('|', '।')
    return text


def apply_shantikunj_rules(text: str) -> str:
    """Standardizes classical half-consonants to anusvara and fixes spacing artifacts."""
    replacements = {
        'ङ्क': 'ंक', 'ञ्च': 'ंच', 'ण्ड': 'ंड', 'न्त': 'ंत', 'म्प': 'ंप',
        'शान्त': 'शांत', 'सम्पत्ति': 'संपत्ति'
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Fix OCR artifacts where spaces are inserted before matras
    text = re.sub(r'\s+([ािीुूेैोौंँः])', r'\1', text)
    return text


def is_metadata_block(tag: str, content: str) -> bool:
    """Returns True if a block represents non-narrative publishing metadata."""
    stripped = content.strip()
    if not stripped:
        return True
    if METADATA_HEADER_PATTERN.match(stripped):
        return True
    if STANDALONE_AUTHOR_PATTERN.match(stripped):
        return True
    if PUBLISHING_METADATA_PATTERN.search(stripped) and len(stripped) < 200:
        return True
    if PAGE_NUMBER_PATTERN.match(stripped):
        return True
    return False


def is_terminal_sentence_end(text: str) -> bool:
    """Returns True if the text ends with sentence-terminating punctuation."""
    stripped = text.strip()
    if not stripped:
        return False
    # Check Hindi dandas, question marks, exclamations, and trailing quotes
    if re.search(r'[।॥!?][\'\"”’]?$', stripped):
        return True
    # If ends with a period, verify it is not an abbreviation
    if re.search(r'\.[\'\"”’]?$', stripped):
        last_token = re.split(r'\s+', stripped)[-1]
        last_token = re.sub(r'[\'\"”’]$', '', last_token)
        abbrs = {
            'पं.', 'डॉ.', 'प्रो.', 'श्री.', 'श्रीमती.', 'कु.', 'ले.', 'इ.', 'उदा.', 'सं.', 'वि.', 'स्व.', 'चि.',
            'dr.', 'mr.', 'mrs.', 'ms.', 'prof.', 'st.', 'e.g.', 'i.e.', 'vs.', 'etc.'
        }
        if last_token.lower() in abbrs:
            return False
        # Single letter initials (e.g. 'A.', 'B.', 'ए.', 'बी.')
        if len(last_token) <= 2:
            return False
        return True
    return False


def clean_book_headers_and_metadata(text: str, book_title: Optional[str] = None) -> str:
    """
    Cleans OCR text by stripping book headers, writer/author attributions,
    publisher/printer metadata, leaked running headers/footers with page numbers,
    and duplicate chapter titles.
    """
    if not text or not text.strip():
        return ""

    # 1. Fix known OCR tag typos
    for pat, repl in TAG_TYPOS:
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)

    # 2. Fix OCR punctuation (pipe to danda)
    text = fix_ocr_punctuation(text)

    # Parse XML blocks
    block_regex = re.compile(r'<([a-zA-Z0-9_]+)>(.*?)</\1>', re.DOTALL)
    raw_blocks: List[Tuple[str, str]] = []

    matches = list(block_regex.finditer(text))
    if matches:
        for m in matches:
            tag = m.group(1).lower()
            content = m.group(2).strip()
            raw_blocks.append((tag, content))
    else:
        for part in text.split('\n\n'):
            if part.strip():
                raw_blocks.append(('prose', part.strip()))

    # Build regexes for detecting running headers
    running_header_regexes = []
    first_headings = [c for t, c in raw_blocks if t == 'heading']
    detected_title = book_title or (first_headings[0] if first_headings else "")
    if detected_title:
        norm_title = re.sub(r'[\sंँेै]+', r'[\\sंँेै]*', re.escape(detected_title))
        running_header_regexes.append(re.compile(norm_title, re.IGNORECASE))
    # Known variations for AWGP literature
    running_header_regexes.append(re.compile(r'मन\s*स[ांँ]*ध[ेै्]*\s*जीवन\s*स[ांँ]*ध[ेै्]*ँ?', re.IGNORECASE))

    def is_running_header_content(c: str) -> bool:
        c_stripped = c.strip()
        if PAGE_NUMBER_PATTERN.match(c_stripped):
            return True
        for rhr in running_header_regexes:
            if rhr.search(c_stripped):
                remainder = rhr.sub('', c_stripped)
                remainder = re.sub(r'[\s\)\]\(\[—\-–|।॥०-९\d]+', '', remainder)
                if not remainder:
                    return True
        return False

    cleaned_blocks: List[Tuple[str, str]] = []
    skip_next_metadata_prose = False

    for i, (tag, content) in enumerate(raw_blocks):
        clean_content = content.strip()
        if not clean_content:
            continue

        # If a substantive heading appears, reset metadata skipping
        if tag in ('heading', 'subheading') and not METADATA_HEADER_PATTERN.match(clean_content):
            skip_next_metadata_prose = False

        # Check if this block is a metadata header (e.g. <subheading>लेखक</subheading>)
        if METADATA_HEADER_PATTERN.match(clean_content):
            skip_next_metadata_prose = True
            continue

        # If previous block was a metadata header, check if this prose is the metadata value
        if skip_next_metadata_prose and tag == 'prose':
            if (PUBLISHING_METADATA_PATTERN.search(clean_content) or
                STANDALONE_AUTHOR_PATTERN.match(clean_content) or
                "श्रीराम शर्मा" in clean_content or
                "गायत्री" in clean_content or
                "मथुरा" in clean_content or
                len(clean_content) < 60):
                continue
            else:
                skip_next_metadata_prose = False

        # Standalone author attribution line: e.g. <prose>—श्रीराम शर्मा आचार्य</prose>
        if STANDALONE_AUTHOR_PATTERN.match(clean_content):
            continue

        # Publishing metadata block
        if PUBLISHING_METADATA_PATTERN.search(clean_content) and len(clean_content) < 200:
            continue

        # Standalone running header / page number block
        if is_running_header_content(clean_content):
            continue

        # Clean leaked running headers/footers embedded at the end of a prose block
        for rhr in running_header_regexes:
            pat_end = re.compile(
                r'[\s,।॥—\-–]*' + rhr.pattern + r'[\s\)\]\(\[—\-–|।॥०-९\d]*$',
                re.IGNORECASE
            )
            if pat_end.search(clean_content):
                sub_res = pat_end.sub('', clean_content).strip()
                if sub_res:
                    clean_content = sub_res

            # Trailing page numbers alone: e.g. ") ( ५" or "( ३५ )"
            pat_page_end = re.compile(r'[\s]+[\)\]]+\s*[\(\[]+\s*[०-९\d]+\s*$', re.IGNORECASE)
            clean_content = pat_page_end.sub('', clean_content).strip()

        # If after stripping running header, content became empty or just a header remnant, skip
        if not clean_content or is_running_header_content(clean_content):
            continue

        # Collapse duplicate identical consecutive headings
        if tag == 'heading' and cleaned_blocks:
            last_tag, last_content = cleaned_blocks[-1]
            if last_tag == 'heading':
                def simplify(h):
                    return re.sub(r'[\sंँेै।॥]+', '', h)
                if simplify(clean_content) == simplify(last_content):
                    continue

        cleaned_blocks.append((tag, clean_content))

    has_xml_tags = bool(matches)

    # Stitch consecutive prose/paragraph/quote blocks that were severed across page breaks in XML-tagged OCR text
    if has_xml_tags:
        stitched_blocks: List[Tuple[str, str]] = []

        for tag, content in cleaned_blocks:
            clean_content = content.strip()
            if not clean_content:
                continue

            if stitched_blocks:
                prev_tag, prev_content = stitched_blocks[-1]
                if prev_tag in ('prose', 'paragraph', 'quote') and tag in ('prose', 'paragraph', 'quote'):
                    # If previous block did not end with sentence-ending punctuation, merge them
                    if not is_terminal_sentence_end(prev_content):
                        # Check for hyphen at end of line/page (word-break)
                        if re.search(r'(\w+)[-]\s*$', prev_content):
                            prev_content = re.sub(r'[-]\s*$', '', prev_content)
                            merged = f"{prev_content}{clean_content}"
                        else:
                            # Deduplicate repeated catchwords / OCR overlap
                            prev_words = prev_content.split()
                            next_words = clean_content.split()
                            if prev_words and next_words and prev_words[-1] == next_words[0]:
                                clean_content = clean_content[len(next_words[0]):].lstrip()
                            merged = f"{prev_content} {clean_content}"
                        stitched_blocks[-1] = (prev_tag, merged)
                        continue

            stitched_blocks.append((tag, clean_content))
    else:
        stitched_blocks = cleaned_blocks

    result_parts = []
    for tag, content in stitched_blocks:
        result_parts.append(f"<{tag}>{content}</{tag}>")

    return "\n\n".join(result_parts)