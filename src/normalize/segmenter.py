"""Conservative, bounded segmentation preserving punctuation and semantic blocks."""
import re
from src.core.types import SpeechSegment
from src.synthesis.parser.xml_parser import XMLParser


class SemanticSegmenter:
    def __init__(self, narration_profile=None, sentences_per_chunk=5, max_chars_per_chunk=1000):
        if sentences_per_chunk < 1 or max_chars_per_chunk < 1:
            raise ValueError("Chunk limits must be positive.")
        self.profile = narration_profile
        self.sentences_per_chunk = sentences_per_chunk
        self.max_chars_per_chunk = max_chars_per_chunk

    def _split_into_sentences(self, text):
        return [part.strip() for part in re.split(
            r"(?<=[।॥!?])\s+|(?<=\.)\s+(?=\D)", text.strip()) if part.strip()]

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

    def segment_text(self, text):
        segments = []
        for block in XMLParser.parse(text or "").blocks:
            for paragraph in re.split(r"\n\s*\n", block.text):
                clean = self._clean_tags(paragraph)
                if not clean:
                    continue
                tag = block.tag.value
                # Ordinary prose relies on provider punctuation pauses. Explicit
                # silence is reserved for semantic boundaries where it improves
                # comprehension; editors can override it in Stage 2.
                pause = {
                    "heading": 1000, "subheading": 600, "book_title": 1400,
                    "shloka": 800, "stanza": 800, "mantra": 800,
                    "chant_refrain": 700, "gloss": 350,
                }.get(tag, 0)
                current = []
                for sentence in self._split_into_sentences(clean):
                    for piece in self._pieces(sentence):
                        if current and (len(" ".join(current)) + 1 + len(piece) > self.max_chars_per_chunk
                                        or len(current) >= self.sentences_per_chunk):
                            chunk = " ".join(current)
                            segments.append(SpeechSegment(chunk, chunk, chunk, segment_type=tag, pause_after_ms=pause))
                            current = []
                        current.append(piece)
                if current:
                    chunk = " ".join(current)
                    segments.append(SpeechSegment(chunk, chunk, chunk, segment_type=tag, pause_after_ms=pause))
        return segments
