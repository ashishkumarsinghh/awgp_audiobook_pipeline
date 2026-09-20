"""Page-by-page transcription with explicit failures instead of omitted pages."""
from typing import Optional
import os
import re
import json
import time
from datetime import datetime
import fitz
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()


def get_gemini_client() -> Optional[genai.Client]:
    api_key = os.environ.get("GEMINI_API_KEY")
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60000)) if api_key else None


def extract_text_from_pdf(
    pdf_path: str,
    max_pages: Optional[int] = None,
    checkpoint_dir: Optional[str] = None,
    book_name: Optional[str] = None,
    pages_to_process: Optional[List[int]] = None
) -> str:
    if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
        raise ValueError("max_pages must be a positive integer.")
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {exc}") from exc
    with doc:
        if doc.needs_pass or not doc.is_pdf or len(doc) == 0:
            raise ValueError("Provide an unlocked PDF containing at least one page.")
        client = get_gemini_client()
        pages = []
        clean_book = re.sub(r'[^a-zA-Z0-9_-]', '_', book_name or os.path.splitext(os.path.basename(pdf_path))[0])
        if checkpoint_dir:
            os.makedirs(checkpoint_dir, exist_ok=True)

        if pages_to_process:
            page_indices = [p - 1 for p in pages_to_process if 1 <= p <= len(doc)]
        else:
            limit = min(max_pages or len(doc), len(doc))
            page_indices = list(range(limit))

        for index in page_indices:
            page_num = index + 1
            cached_text = None
            page_file = None

            if checkpoint_dir:
                page_file = os.path.join(checkpoint_dir, f"{clean_book}_page_{page_num:04d}.txt")
                if os.path.isfile(page_file):
                    try:
                        with open(page_file, "r", encoding="utf-8") as f:
                            content = f.read()
                            if content.strip():
                                cached_text = content
                    except Exception:
                        pass

            if cached_text is not None:
                if "<blank_page>" not in cached_text:
                    pages.append(cached_text)
                continue

            page = doc.load_page(index)
            if client is None:
                text = page.get_text().strip()
                if not text:
                    raise RuntimeError(f"Page {page_num} has no embedded text. Set GEMINI_API_KEY for scanned-page OCR, then retry.")
            else:
                print(f"[Stage 0: OCR] Transcribing page {page_num}/{len(page_indices)} with Gemini Flash OCR...")
                image = page.get_pixmap(dpi=200).tobytes("png")
                text = _transcribe_page(client, image, page_num)
                time.sleep(2.0)

            if page_file:
                try:
                    with open(page_file, "w", encoding="utf-8") as f:
                        f.write(text)
                except Exception:
                    pass

            if "<blank_page>" in text:
                print(f"[Stage 0: OCR] Page {page_num}: Excluded non-narrative metadata/blank page.")
            else:
                pages.append(text)

        if checkpoint_dir:
            manifest_path = os.path.join(checkpoint_dir, "ocr_manifest.json")
            try:
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "book_name": clean_book,
                        "total_pages": len(page_indices),
                        "completed_pages": len(pages),
                        "timestamp": datetime.now().isoformat()
                    }, f, indent=2)
            except Exception:
                pass

        return "\n\n".join(pages)


def _transcribe_page(client, img_bytes, page_number):
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
        "Exclude page numbers, running headers/footers, book title headers repeated on pages, "
        "author/writer information (e.g., 'लेखक', 'पं० श्रीराम शर्मा आचार्य', '—श्रीराम शर्मा आचार्य'), "
        "publisher/press metadata (e.g., 'प्रकाशक', 'युग निर्माण योजना', 'गायत्री तपोभूमि, मथुरा', "
        "'मुद्रक', 'मूल्य', 'संस्करण'), publication names/dates, website URLs or watermarks, "
        "decorative borders, ornamental typography, printer marks, copyright notices, "
        "advertisements, and other non-narrative publishing artifacts.\n"
        "Examples to EXCLUDE completely: '(३१)', '32', ') ( ५', 'मन साधे जीवन सधे ) ( १५', "
        "'लेखक', 'प्रकाशक', 'अखण्ड ज्योति', 'अखंडज्योति', 'Akhand Jyoti - May, 1948', 'awgp.org', 'akhandjyoti.org'.\n"
        "If a cover page, front matter, or title page contains only author name, publisher, address, "
        "or publishing credits, treat the page as non-narrative metadata and output <blank_page></blank_page>.\n"
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
        "If the page contains no narrative, spiritual, philosophical, or literary content (for example, "
        "if it contains ONLY excluded publishing metadata, addresses, URLs, printer credits, or is completely blank), "
        "output exactly: <blank_page></blank_page>\n"
    )


    model_name = os.environ.get("OCR_MODEL") or "gemini-3.6-flash"
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[types.Part.from_bytes(data=img_bytes, mime_type="image/png"), prompt],
                config=types.GenerateContentConfig(temperature=0.0))
            text = (response.text or "").strip()
            if not text:
                raise ValueError("empty OCR response; inspect this page before proceeding")
            return text
        except Exception as exc:
            err_str = str(exc)
            if ("404" in err_str or "503" in err_str or "RESOURCE_EXHAUSTED" in err_str or "GenerateRequestsPerDay" in err_str) and model_name != "gemini-3.5-flash-lite":
                print(f"  [ModelFallback] {model_name} quota exceeded or unavailable. Switching to gemini-3.5-flash-lite...")
                model_name = "gemini-3.5-flash-lite"
                continue
            if attempt < max_attempts - 1 and any(code in err_str for code in ("429", "500", "502", "503", "504", "quota", "RESOURCE_EXHAUSTED", "empty OCR response")):
                delay = 5 * (attempt + 1) if "empty OCR response" in err_str else 30
                if "retry in " in err_str:
                    try:
                        match = re.search(r'retry in (\d+(?:\.\d+)?)s', err_str)
                        if match:
                            delay = float(match.group(1)) + 2.0
                    except Exception:
                        pass
                elif "retryDelay" in err_str:
                    try:
                        match = re.search(r"retryDelay': '(\d+)s", err_str)
                        if match:
                            delay = int(match.group(1)) + 2.0
                    except Exception:
                        pass
                elif "empty OCR response" not in err_str:
                    delay = min(60, 15 * (attempt + 1))
                print(f"  [Retry] Page {page_number}, attempt {attempt + 1}: {exc.__class__.__name__}. Waiting {int(delay)}s before retry...")
                time.sleep(delay)
                continue
            raise RuntimeError(f"OCR failed on page {page_number}: {exc}") from exc
