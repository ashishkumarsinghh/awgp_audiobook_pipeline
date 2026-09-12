import re
from typing import List
from src.core.types import SpeechSegment

class SemanticSegmenter:
    def __init__(self, narration_profile):
        self.profile = narration_profile

    def segment_text(self, text: str) -> List[SpeechSegment]:
        segments = []
        
        # 1. Normalize line breaks first
        text = text.replace('\n', ' ')
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 2. Extract quotes vs non-quotes
        tokens = re.split(r'(["\'\“\‘].*?["\'\”\’])', text)
        
        for token in tokens:
            token = token.strip()
            if not token:
                continue
                
            is_quote = bool(re.match(r'^[\"\'\“\‘].*[\"\'\”\’]$', token))
            clean_text = re.sub(r'[\"\'\“\‘\”\’]', '', token).strip()
            
            if is_quote:
                segments.append(SpeechSegment(
                    source_text=token,
                    normalized_text=clean_text,
                    pronunciation_text=clean_text,
                    segment_type="quote"
                ))
                continue
            
            # 3. For non-quotes, split by major sentence boundaries
            blocks = re.split(r'(\|\||\||\।|\.|\?|\!)', token)
            
            sentences = []
            for i in range(0, len(blocks)-1, 2):
                sentences.append((blocks[i] + blocks[i+1]).strip())
            if len(blocks) % 2 != 0 and blocks[-1].strip():
                sentences.append(blocks[-1].strip())
                
            # 4. Clause Chunking for long sentences
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence: continue
                
                words = sentence.split()
                segment_type = "prose"
                if "ॐ" in sentence or "भूर्भुवः" in sentence:
                    segment_type = "mantra"
                elif len(words) < 8 and not sentence.endswith(("।", ".", "|", "||", "?", "!")):
                    segment_type = "heading"
                elif "|" in sentence or "।" in sentence:
                    segment_type = "prose" if "।" in sentence else "shloka"
                    
                # If sentence > 12 words and has a comma, split on comma
                if len(words) > 12 and "," in sentence:
                    clauses = sentence.split(",")
                    for idx, clause in enumerate(clauses):
                        clause = clause.strip()
                        if not clause: continue
                        
                        seg = SpeechSegment(
                            source_text=clause,
                            normalized_text=clause,
                            pronunciation_text=clause,
                            segment_type=segment_type,
                            pause_after_ms=150 if idx < len(clauses)-1 else 0
                        )
                        segments.append(seg)
                else:
                    segments.append(SpeechSegment(
                        source_text=sentence,
                        normalized_text=sentence,
                        pronunciation_text=sentence,
                        segment_type=segment_type
                    ))
                    
        return segments