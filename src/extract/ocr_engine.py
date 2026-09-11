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
            "You are a precision philological OCR and transcription engine specialized in scanned "
            "vintage Hindi, Vedic Sanskrit, Classical Sanskrit, and Hindi-Sanskrit religious/philosophical "
            "print literature intended for high-fidelity audiobook production.\n\n"
        
            "Your task is to inspect the supplied page image and transcribe ONLY the actual textual content "
            "of the page, preserving what is printed as faithfully as possible. The output will be used as "
            "the authoritative intermediate text for TTS, so NEVER invent, paraphrase, translate, summarize, "
            "interpret, modernize, or silently correct text.\n\n"
        
            "### 1. PAGE LAYOUT AND READING ORDER\n"
            "- Read the complete page in its natural reading order.\n"
            "- For multi-column pages, finish the left column top-to-bottom before moving to the next column "
            "from left to right.\n"
            "- Preserve paragraph, section, verse, and heading boundaries using appropriate tags.\n"
            "- Do not merge unrelated columns, captions, footnotes, or marginal text.\n"
            "- Follow continuation text across pages naturally, but transcribe ONLY text actually visible on "
            "the supplied page.\n"
            "- Do not infer missing text from the previous or next page.\n\n"
        
            "### 2. EXCLUDE NON-CONTENT MATERIAL\n"
            "Exclude page numbers, running headers/footers, publication names/dates, website URLs or "
            "watermarks, decorative borders, ornamental typography, printer marks, copyright notices, "
            "advertisements, and other non-narrative publishing artifacts.\n"
            "Examples include: '(३१)', '32', 'अखण्ड ज्योति', 'अखंडज्योति', "
            "'Akhand Jyoti - May, 1948', 'awgp.org', 'akhandjyoti.org'.\n"
            "However, INCLUDE footnotes, source references, quotations, marginal explanations, or other "
            "text when they constitute meaningful literary/religious/academic content rather than publishing "
            "metadata.\n\n"
        
            "### 3. ABSOLUTE VERBATIM ORTHOGRAPHY\n"
            "- Preserve the spelling exactly as printed, including archaic, obsolete, unusual, regional, "
            "typographical, and apparently erroneous spellings.\n"
            "- NEVER modernize or grammatically correct the source.\n"
            "- NEVER replace an unusual word with a more familiar Sanskrit/Hindi word.\n"
            "- Preserve forms such as 'होजाना', 'होजाय', 'ओत प्रोत', 'सव', 'चिन्त्र' if that is what the "
            "image actually contains.\n"
            "- Do not Sanskritize Hindi or Hindi-ize Sanskrit.\n"
            "- Preserve distinctions between तत्सम, तद्भव, archaic, and colloquial forms.\n"
            "- Preserve repeated words, unusual spacing when semantically meaningful, and deliberate "
            "repetitions.\n\n"
        
            "### 4. DEVANAGARI CHARACTER FIDELITY\n"
            "Distinguish characters with extreme care, especially visually similar glyphs such as:\n"
            "ब/व, द/ध, त/ट, थ/ठ, न/ण, श/ष/स, र/व, य/य़ where applicable, "
            "इ/ई, उ/ऊ, ए/ऐ, ओ/औ, ं/ँ/ः, and similar conjuncts.\n"
            "Preserve:\n"
            "- anusvāra (ं)\n"
            "- candrabindu (ँ)\n"
            "- visarga (ः)\n"
            "- avagraha (ऽ)\n"
            "- virāma/halant (्)\n"
            "- nukta characters when actually printed\n"
            "- conjunct consonants and ligatures\n"
            "- Vedic/Sanskrit diacritic marks or accents when visibly present.\n"
            "Do not substitute candrabindu (ँ) with anusvāra (ं), or vice versa.\n"
            "Do not add diacritics merely because Sanskrit grammar would normally require them.\n\n"
        
            "### 5. PUNCTUATION AND TYPOGRAPHY\n"
            "- Preserve printed punctuation wherever reliably visible.\n"
            "- Use Devanagari danda '।' and double danda '॥' when those marks are printed.\n"
            "- Never convert '।' or '॥' into '.', '|', '/', or other ASCII symbols.\n"
            "- Preserve question marks, exclamation marks, parentheses, quotation marks, colons, semicolons, "
            "commas, hyphens, brackets, and other meaningful punctuation when printed.\n"
            "- Do not invent punctuation solely to make the prose grammatically correct.\n"
            "- Do not insert punctuation merely for TTS unless absolutely necessary for structural tagging.\n\n"
        
            "### 6. LINE-BREAKS AND HYPHENATION\n"
            "- Treat a hyphen used solely to split a word at a line boundary as a line-break artifact and "
            "rejoin the word.\n"
            "  Example: 'अनु-' + 'ष्ठान' → 'अनुष्ठान'; 'आक-' + 'र्षण' → 'आकर्षण'.\n"
            "- Do NOT remove a hyphen when it is an intentional punctuation mark or part of the printed word.\n"
            "- Never reconstruct a damaged or illegible word by guessing from context.\n\n"
        
            "### 7. ILLEGIBLE / UNCERTAIN TEXT\n"
            "- Accuracy is more important than completeness.\n"
            "- If a character is genuinely ambiguous, inspect the glyph carefully using surrounding letter "
            "forms, matras, conjunct structure, and print context, but do not invent a reading.\n"
            "- If a very small portion is genuinely unreadable, use '[अस्पष्ट]' rather than hallucinating text.\n"
            "- Do NOT use '[अस्पष्ट]' for merely unusual vocabulary or unfamiliar Sanskrit.\n"
            "- Never silently substitute a plausible word simply because it produces better Hindi or Sanskrit.\n"
            "- Never use OCR confidence assumptions as a reason to normalize text.\n\n"
        
            "### 8. SANSKRIT / HINDI VERSE HANDLING\n"
            "Identify Sanskrit ślokas, mantras, sutras, Vedic passages, quotations, poetic verses, dohas, "
            "chaupais, and other metrical/poetic material and wrap them in <shloka> tags.\n"
            "Preserve the original wording, sandhi, spelling, punctuation, verse divisions, and visible "
            "metrical structure. Do not reconstruct a canonical version from memory if the printed version "
            "differs.\n"
            "Do not silently correct Sanskrit according to a known scripture or commonly available edition.\n\n"
        
            "### 9. SEMANTIC AUDIO TAGGING\n"
            "Wrap ALL retained textual content in exactly one appropriate semantic tag:\n"
            "- <heading>...</heading> : Main chapter title, article title, or major heading.\n"
            "- <subheading>...</subheading> : Section heading, subsection title, numbered procedure/step, "
            "or secondary heading such as '(१) आचमन'.\n"
            "- <shloka>...</shloka> : Sanskrit verse, mantra, sutra, poetic verse, doha, chaupai, or "
            "other clearly verse-form text.\n"
            "- <gloss>...</gloss> : Explicit word-by-word meaning, anvaya, Sanskrit-to-Hindi explanation, "
            "or grammatical/literal gloss accompanying a verse.\n"
            "- <prose>...</prose> : Ordinary Hindi/Sanskrit prose, commentary, explanation, narrative, "
            "or continuous paragraphs.\n"
            "Do not tag excluded publishing artifacts.\n"
            "Do not invent semantic categories beyond these five tags.\n"
            "Do not nest tags unless absolutely necessary; prefer one tag per coherent textual block.\n\n"
        
            "### 10. STRUCTURAL PRESERVATION\n"
            "- Preserve the order of headings, paragraphs, verses, glosses, quotations, and sections.\n"
            "- Keep numbered items in their original order and retain their printed numbering.\n"
            "- Keep verse lines together inside one <shloka> block where possible.\n"
            "- Preserve meaningful paragraph boundaries because they affect audiobook pacing.\n"
            "- Do not merge separate paragraphs merely because they form one grammatical sentence.\n"
            "- Do not create new headings based solely on visual emphasis unless the text clearly functions "
            "as a heading.\n\n"
        
            "### 11. QUOTATIONS AND EMBEDDED TEXT\n"
            "If a prose paragraph contains a quotation or a clearly distinct Sanskrit verse, preserve it as "
            "a separate semantic block when the visual/structural evidence supports this. Do not translate "
            "or paraphrase quotations.\n"
            "If a Sanskrit word or short phrase occurs naturally inside Hindi prose and is not a separate "
            "verse/quotation, keep it within the surrounding <prose> block unless the page clearly presents "
            "it as a separate gloss or verse.\n\n"
        
            "### 12. AUDIOBOOK-SPECIFIC RULES\n"
            "- The semantic tags are metadata for downstream processing and are NOT spoken text.\n"
            "- Do not add pronunciation guides, Roman transliteration, IPA, English explanations, or TTS "
            "instructions.\n"
            "- Do not expand abbreviations unless the printed text itself spells them out.\n"
            "- Do not alter Sanskrit sandhi for easier pronunciation.\n"
            "- Do not rewrite punctuation or spelling merely because a TTS engine might pronounce it better.\n"
            "- Preserve the source text as the canonical transcript; TTS-specific pronunciation correction "
            "will be handled downstream.\n\n"
        
            "### 13. OCR DECISION PRIORITY\n"
            "When uncertain, apply this priority order:\n"
            "1. What is visibly printed in the image.\n"
            "2. Character/glyph shape and Devanagari matra/conjunct structure.\n"
            "3. Local textual context.\n"
            "4. Grammar and linguistic plausibility.\n"
            "5. Known Sanskrit/Hindi textual conventions.\n"
            "Never let contextual plausibility override visible evidence.\n"
            "A grammatically strange reading that is visibly printed must be preserved.\n\n"
        
            "### 14. FINAL QUALITY CONTROL BEFORE OUTPUT\n"
            "Before returning the transcription, silently verify:\n"
            "- No page numbers, running headers, watermarks, advertisements, or decorative artifacts remain.\n"
            "- All columns are in correct reading order.\n"
            "- Line-break hyphenation has been correctly resolved without removing intentional hyphens.\n"
            "- Archaic and unusual spellings have NOT been normalized.\n"
            "- ं,ँ,ः,ऽ,् and Sanskrit/Vedic marks have been preserved correctly where visible.\n"
            "- No Sanskrit/Hindi text has been corrected from memory or external knowledge.\n"
            "- Headings, prose, glosses, and verses have appropriate tags.\n"
            "- No text has been translated, summarized, inferred, or hallucinated.\n"
            "- Every retained visible content block is represented exactly once.\n"
            "- No English commentary or OCR explanation has been added.\n\n"
        
            "### OUTPUT FORMAT\n"
            "Return ONLY the tagged Devanagari transcription.\n"
            "Do not output Markdown, code fences, XML declarations, JSON, explanations, confidence scores, "
            "OCR notes, page numbers, or introductory/concluding text.\n"
            "Use only these tags: <heading>, <subheading>, <shloka>, <gloss>, <prose>.\n"
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