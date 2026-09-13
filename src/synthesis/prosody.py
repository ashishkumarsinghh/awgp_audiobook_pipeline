import hashlib
from typing import List
from src.core.types import SpeechSegment, NarrationProfile

class ProsodyPlanner:
    def __init__(self, profile: NarrationProfile):
        self.profile = profile

    def apply_prosody(self, segments: List[SpeechSegment]):
        base_rate_val = int(self.profile.base_rate.strip('%').strip('+'))
        base_pitch_val = int(self.profile.base_pitch.strip('Hz').strip('+'))
        
        for i, seg in enumerate(segments):
            # 1. Base Pause Profile (only set if not already set by clause chunking)
            if seg.pause_after_ms == 0:
                if seg.segment_type == "heading":
                    seg.pause_before_ms = self.profile.heading_pause_ms
                    seg.pause_after_ms = self.profile.heading_pause_ms
                elif seg.segment_type == "shloka":
                    seg.pause_after_ms = self.profile.verse_pause_ms
                else:
                    seg.pause_after_ms = self.profile.sentence_pause_ms
                
            # 2. Dynamic Rate & Pitch
            rate_var = 0
            pitch_var = 0
            
            if seg.segment_type in ["quote", "dialogue"]:
                rate_var = -2
                pitch_var = 2
            elif seg.segment_type in ["shloka", "stanza", "verse_line", "mantra", "chant_refrain"]:
                rate_var = -5
                pitch_var = -1
            elif seg.segment_type in ["heading", "subheading", "book_title"]:
                pitch_var = -2
                rate_var = 0
                
            final_rate = base_rate_val + rate_var
            final_pitch = base_pitch_val + pitch_var
            
            seg.rate = f"{final_rate:+}%".replace("++", "+")
            seg.pitch = f"{final_pitch:+}Hz".replace("++", "+")
            
        return segments
