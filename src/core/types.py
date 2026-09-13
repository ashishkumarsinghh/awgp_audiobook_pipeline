from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class PronunciationEntry:
    source: str
    tts_alias: str
    language: str = "hi-IN"
    context: str = "general"
    confidence: str = "EXACT"
    category: str = "Sanskrit"
    notes: str = ""

@dataclass
class VoiceProfile:
    voice: str
    language: str
    base_rate: str = "+0%"
    base_pitch: str = "+0Hz"
    preferred_chunk_size: int = 2
    pronunciation_profile: str = "classical_sanskrit"
    pause_profile: str = "default"
    mastering_profile: str = "intimate_audiobook"

@dataclass
class NarrationProfile:
    mode: str = "audiobook"
    language: str = "hi-IN"
    voice: str = "hi-IN-MadhurNeural"
    base_rate: str = "-5%"
    base_pitch: str = "+0Hz"
    sentence_pause_ms: int = 300
    paragraph_pause_ms: int = 600
    verse_pause_ms: int = 600
    heading_pause_ms: int = 800
    prosody_variation: str = "low"
    target_wpm: int = 145
    wpm_tolerance_percent: int = 18

@dataclass
class SpeechSegment:
    source_text: str
    normalized_text: str
    pronunciation_text: str
    segment_type: str = "prose"
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    pause_before_ms: int = 0
    pause_after_ms: int = 0
    audio_file: Optional[str] = None
    
    def __repr__(self):
        return f"<Segment [{self.segment_type}] rate={self.rate} pitch={self.pitch} text='{self.source_text[:20]}...'>"
