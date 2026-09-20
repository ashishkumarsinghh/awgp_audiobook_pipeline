"""Conservative, bounded segmentation preserving punctuation and semantic blocks.

Integrates metadata header filtering and prosodic semantic classification.
"""
import re
from src.core.types import SpeechSegment
from src.synthesis.parser.xml_parser import XMLParser
from src.normalize.text_cleaner import clean_book_headers_and_metadata, is_metadata_block


class SemanticSegmenter:
    def __init__(self, narration_profile=None, sentences_per_chunk=3, max_chars_per_chunk=700):
        if sentences_per_chunk < 1 or max_chars_per_chunk < 1:
            raise ValueError("Chunk limits must be positive.")
        self.profile = narration_profile
        self.sentences_per_chunk = sentences_per_chunk
        self.max_chars_per_chunk = max_chars_per_chunk

    def _split_into_sentences(self, text):
        text = text.strip()
        if not text:
            return []

        # Protect common Hindi and English abbreviations and numbered points
        abbr_pattern = re.compile(
            r'\b(?:पं|डॉ|प्रो|श्री|श्रीमती|कु|ले|इ|उदा|सं|वि|स्व|चि|'
            r'Dr|Mr|Mrs|Ms|Prof|St|e\.g|i\.e|vs|etc|'
            r'[A-Za-z]|[\u0900-\u097F])\.',
            re.IGNORECASE
        )
        list_num_pattern = re.compile(r'(?:^|\s)[०-९\d]+\.')
        placeholder = "\uE000"

        def replace_dot(m):
            return m.group(0)[:-1] + placeholder

        subbed = abbr_pattern.sub(replace_dot, text)
        subbed = list_num_pattern.sub(replace_dot, subbed)

        raw_sentences = re.split(r'(?<=[।॥!?])\s+|(?<=\.)\s+(?=[A-Z\u0900-\u097F])', subbed)
        results = [s.replace(placeholder, ".").strip() for s in raw_sentences if s.strip()]
        return results

    def _clean_tags(self, text):
        text = re.sub(rf"</?(?:{XMLParser.TAGS})>", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def _pieces(self, sentence):
        limit = self.max_chars_per_chunk
        if any(len(word) > limit for word in sentence.split()):
            raise ValueError(f"A word exceeds the {limit}-character chunk limit. Review OCR spacing before synthesis.")
        current = ""
        for word in sentence.split():
            if current and len(current) + 1 + len(word) > limit:
                yield current
                current = ""
            current = f"{current} {word}".strip()
        if current:
            yield current

    def _detect_sentence_tag(self, text: str, base_tag: str) -> str:
        """Refines prose tag into richer prosodic categories for natural intonation."""
        if base_tag not in ("prose", "paragraph", "sentence"):
            return base_tag
        t = text.strip()
        if t.endswith("?"):
            return "question"
        if t.endswith("!"):
            return "emphasis"
        if (t.startswith("“") and t.endswith("”")) or (t.startswith('"') and t.endswith('"')):
            return "quote"
        if re.search(r'^(?:किंतु|परंतु|लेकिन|इसके विपरीत|दूसरी घटना|दूसरी ओर)\b', t):
            return "reflective"
        if re.search(r'^(?:इस प्रकार|अतः|इसलिए मनुष्य|निष्कर्षतः)\b', t):
            return "conclusion"
        return base_tag

    def segment_text(self, text):
        # 1. Clean book headers, publishing metadata, author lines, and running headers
        cleaned_text = clean_book_headers_and_metadata(text or "")

        segments = []
        parsed_doc = XMLParser.parse(cleaned_text)

        for block in parsed_doc.blocks:
            tag = block.tag.value
            # Defensive check against non-narrative metadata blocks
            if is_metadata_block(tag, block.text):
                continue

            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", block.text) if p.strip()]
            for p_idx, paragraph in enumerate(paragraphs):
                clean = self._clean_tags(paragraph)
                if not clean:
                    continue

                is_last_paragraph_in_block = (p_idx == len(paragraphs) - 1)

                # Default pauses by tag type
                pause_map = {
                    "heading": 1000, "subheading": 600, "book_title": 1400,
                    "shloka": 800, "stanza": 800, "mantra": 800,
                    "chant_refrain": 700, "gloss": 350,
                    "question": 500, "quote": 400, "reflective": 400, "conclusion": 600,
                }

                current = []
                current_ends_at_sentence = True
                sentences = self._split_into_sentences(clean)
                for s_idx, sentence in enumerate(sentences):
                    pieces = list(self._pieces(sentence))
                    for p_sub_idx, piece in enumerate(pieces):
                        is_sentence_end = (p_sub_idx == len(pieces) - 1)

                        if current:
                            would_exceed_len = (len(" ".join(current)) + 1 + len(piece) > self.max_chars_per_chunk)
                            would_exceed_sentences = (len(current) >= self.sentences_per_chunk and current_ends_at_sentence)
                            if would_exceed_len or would_exceed_sentences:
                                chunk = " ".join(current)
                                chunk_tag = self._detect_sentence_tag(chunk, tag)
                                if current_ends_at_sentence:
                                    pause = pause_map.get(chunk_tag, 350)
                                    if tag in ("heading", "subheading", "book_title", "shloka", "stanza", "mantra"):
                                        pause = pause_map.get(tag, 800)
                                else:
                                    # Never insert a pause mid-sentence if forced to split by max_chars
                                    pause = 0
                                segments.append(SpeechSegment(chunk, chunk, chunk, segment_type=chunk_tag, pause_after_ms=pause))
                                current = []

                        current.append(piece)
                        current_ends_at_sentence = is_sentence_end

                if current:
                    chunk = " ".join(current)
                    final_tag = self._detect_sentence_tag(chunk, tag)
                    if current_ends_at_sentence:
                        pause = pause_map.get(final_tag, 600 if is_last_paragraph_in_block else 350)
                        if tag in ("heading", "subheading", "book_title", "shloka", "stanza", "mantra"):
                            pause = pause_map.get(tag, 800)
                    else:
                        pause = 0
                    segments.append(SpeechSegment(chunk, chunk, chunk, segment_type=final_tag, pause_after_ms=pause))

        return segments

