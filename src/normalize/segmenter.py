import re
from typing import List
from src.core.types import SpeechSegment
from src.synthesis.parser.xml_parser import XMLParser
from src.synthesis.models.document import SemanticTag

class SemanticSegmenter:
    def __init__(self, narration_profile=None, sentences_per_chunk=5, max_chars_per_chunk=1000):
        self.profile = narration_profile
        self.sentences_per_chunk = sentences_per_chunk
        self.max_chars_per_chunk = max_chars_per_chunk

    def _split_into_sentences(self, text: str) -> List[str]:
        """Splits Hindi/Devanagari prose into individual sentences preserving punctuation and quotes."""
        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            return []
        
        pattern = r'([^।॥!?.\n]+(?:[।॥!?.]|$)[\"\'\”\’]*)'
        matches = [m.strip() for m in re.findall(pattern, text) if m.strip()]
        return matches if matches else [text]

    def _clean_tags(self, text: str) -> str:
        """Removes all XML/HTML tags like <prose>, </prose>, <heading>, etc."""
        cleaned = re.sub(r'<[^>]+>', '', text)
        return re.sub(r'\s+', ' ', cleaned).strip()

    def segment_text(self, text: str) -> List[SpeechSegment]:
        if not text or not text.strip():
            return []

        segments = []
        
        # 1. Parse into semantic document blocks using XMLParser
        doc = XMLParser.parse(text)
        
        for block in doc.blocks:
            clean_content = self._clean_tags(block.text)
            if not clean_content:
                continue

            tag = block.tag

            if tag == SemanticTag.HEADING:
                segments.append(SpeechSegment(
                    source_text=clean_content,
                    normalized_text=clean_content,
                    pronunciation_text=clean_content,
                    segment_type="heading",
                    pause_after_ms=1000
                ))
            elif tag == SemanticTag.SUBHEADING:
                segments.append(SpeechSegment(
                    source_text=clean_content,
                    normalized_text=clean_content,
                    pronunciation_text=clean_content,
                    segment_type="subheading",
                    pause_after_ms=600
                ))
            elif tag == SemanticTag.SHLOKA:
                segments.append(SpeechSegment(
                    source_text=clean_content,
                    normalized_text=clean_content,
                    pronunciation_text=clean_content,
                    segment_type="shloka",
                    pause_after_ms=800
                ))
            elif tag == SemanticTag.GLOSS:
                segments.append(SpeechSegment(
                    source_text=clean_content,
                    normalized_text=clean_content,
                    pronunciation_text=clean_content,
                    segment_type="gloss",
                    pause_after_ms=500
                ))
            else:
                # Prose block: group into 5-6 sentences per chunk for optimal audiobook listening
                sentences = self._split_into_sentences(clean_content)
                if not sentences:
                    sentences = [clean_content]

                current_sentences = []
                current_chars = 0

                for sent in sentences:
                    current_sentences.append(sent)
                    current_chars += len(sent)

                    if len(current_sentences) >= self.sentences_per_chunk or current_chars >= self.max_chars_per_chunk:
                        chunk_str = " ".join(current_sentences)
                        segments.append(SpeechSegment(
                            source_text=chunk_str,
                            normalized_text=chunk_str,
                            pronunciation_text=chunk_str,
                            segment_type="prose",
                            pause_after_ms=450
                        ))
                        current_sentences = []
                        current_chars = 0

                if current_sentences:
                    chunk_str = " ".join(current_sentences)
                    segments.append(SpeechSegment(
                        source_text=chunk_str,
                        normalized_text=chunk_str,
                        pronunciation_text=chunk_str,
                        segment_type="prose",
                        pause_after_ms=500
                    ))

        return segments
