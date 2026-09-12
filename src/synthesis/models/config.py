from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SpeechRates:
    prose: float = 1.0
    heading: float = 0.85
    subheading: float = 0.90
    gloss: float = 0.95
    shloka: float = 0.82

@dataclass
class PausesMs:
    heading_before: int = 900
    heading_after: int = 700
    paragraph: int = 500
    shloka_line: int = 450
    shloka_end: int = 1000
    subheading_before: int = 600
    subheading_after: int = 400
    gloss_before: int = 300

@dataclass
class TTSProviderConfig:
    provider: str = "edge"
    edge_voice: str = "hi-IN-SwaraNeural"
    gemini_voice: str = "hi-IN-AaryaNeural"

@dataclass
class SynthesisConfig:
    rates: SpeechRates = field(default_factory=SpeechRates)
    pauses: PausesMs = field(default_factory=PausesMs)
    tts_provider: TTSProviderConfig = field(default_factory=TTSProviderConfig)
