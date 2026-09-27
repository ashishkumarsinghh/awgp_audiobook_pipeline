"""Dynamic prosody planning and intonation marking for natural speech synthesis.

Applies clause-level breath pauses, punctuation modulation, and segment-level
pitch/rate shaping so neural TTS models (e.g. Edge TTS Swara/Madhur) sound
natural, expressive, and human-like.
"""
import re
from typing import List, Optional
from src.core.types import SpeechSegment, NarrationProfile

# Conjunctions where human narrators naturally take a micro breath-pause
CONJUNCTION_BREATH_PATTERN = re.compile(
    r'(?<=[^\s,।॥!?:;—\-])\s+(किंतु|परंतु|लेकिन|मगर|इसलिए|ताकि|जिससे|क्योंकि|चूँकि|अर्थात्|वस्तुतः|फलतः|अतः|तथापि|यद्यपि|वरन|बल्कि)(?=\s+[^\s])'
)

# Subordinate clause complementizer 'कि' preceded by verbal/predicate triggers
SUBORDINATE_KI_PATTERN = re.compile(
    r'(\b(?:है|था|थी|थे|हूँ|हो|कहा|माना|देखा|लगा|पहुँचा|पहुंची|पहुंचे|सका|सकी|सके|सकता|सकती|सकते|चाहिए|गया|गई|गए|हुआ|हुई|हुए|सोचा|समझा|बोला|सुना|पाया|दिखा|आया|आई|आए|स्पष्ट|उद्देश्य|आशा|विश्वास|प्रतीत))\s+कि(?=\s+[^\s])'
)

# Relative clauses and adverbial clause markers requiring a respiration breath pause
RELATIVE_BREATH_PATTERN = re.compile(
    r'(?<=[^\s,।॥!?:;—\-])\s+(जिसने|जिसके कारण|जिसके फलस्वरूप|जिस समय|जिस प्रकार|जहाँ कहीं)(?=\s+[^\s])'
)


def apply_prosodic_marking(text: str, segment_type: str = "prose") -> str:
    """
    Applies punctuation and phrasing enhancements that steer neural TTS models
    (like Edge TTS) to produce natural prosody, breathing pauses, and intonational contours.
    """
    if not text:
        return ""

    t = text.strip()

    # 1. Normalize OCR pipe characters to standard Hindi dandas
    t = t.replace("||", "॥").replace("|", "।")

    # 2. Insert natural clause breath-pause commas before coordinating/subordinating conjunctions
    t = CONJUNCTION_BREATH_PATTERN.sub(r', \1', t)
    t = SUBORDINATE_KI_PATTERN.sub(r'\1, कि', t)
    t = RELATIVE_BREATH_PATTERN.sub(r', \1', t)

    # 3. Clean and convert ASCII parenthetical hyphens to Devanagari/Hindi em-dashes
    t = re.sub(r'\s+[-–—]\s+', '—', t)
    t = re.sub(r'(?<=[^\s—])—(?=[^\s—])', '—', t)

    # 4. Standardize quotes for distinct quotation cadence
    t = t.replace('"', '“').replace('"', '”')
    t = re.sub(r'([—:])\s*“', r'\1 “', t)

    # 5. Clean redundant punctuation and resolve isolated conjunction pause islands
    t = re.sub(r',\s*,+', ',', t)
    t = re.sub(r',\s*(कि|और|तथा|एवं|या|अथवा|तो)\s*,', r', \1 ', t)
    t = re.sub(r'([।॥!?])\s*([।॥!?])+', r'\1', t)
    t = re.sub(r',\s*([।॥!?])', r'\1', t)
    t = re.sub(r'([।॥!?])\s*,', r'\1', t)

    # 6. Ensure sentences end with proper cadence marks
    if segment_type in ("heading", "subheading", "book_title"):
        # Headings should not end with a trailing comma
        t = t.rstrip(', ')
    elif segment_type == "question":
        if not t.endswith("?"):
            t = t.rstrip('।॥. ') + "?"
    elif segment_type in ("shloka", "mantra", "stanza", "verse_line", "chant_refrain"):
        # Ensure proper spacing around dandas for Sanskrit Yati pauses
        t = re.sub(r'(?<=[^\s])([।॥])', r' \1', t)
        if not (t.endswith("॥") or t.endswith("।")):
            t = t.rstrip('. ') + "॥"

    t = re.sub(r'[ \t]+', ' ', t).strip()
    return t


class ProsodyPlanner:
    def __init__(self, profile: NarrationProfile):
        self.profile = profile

    def apply_prosody(self, segments: List[SpeechSegment]) -> List[SpeechSegment]:
        base_rate_val = int(self.profile.base_rate.strip('%').strip('+'))
        base_pitch_val = int(self.profile.base_pitch.strip('Hz').strip('+'))

        # Track discourse position within paragraphs
        in_para_idx = 0
        total_segs = len(segments)

        for i, seg in enumerate(segments):
            seg_type = seg.segment_type or "prose"

            # Determine paragraph boundaries based on pause after and neighboring segment types
            is_prev_boundary = (
                (i == 0)
                or (segments[i - 1].pause_after_ms >= 550)
                or (segments[i - 1].segment_type in ("heading", "subheading", "book_title", "shloka", "mantra", "stanza"))
            )
            is_next_boundary = (
                (i == total_segs - 1)
                or (seg.pause_after_ms >= 550)
                or ((i + 1 < total_segs) and segments[i + 1].segment_type in ("heading", "subheading", "book_title", "shloka", "mantra", "stanza"))
            )

            if is_prev_boundary:
                in_para_idx = 0
            else:
                in_para_idx += 1

            rate_var = 0
            pitch_var = 0
            vol_var = 0

            # 1. Structural / Metrical / Expressive segment types take priority
            if seg_type in ("heading", "book_title"):
                rate_var = -6
                pitch_var = -2
                seg.pause_before_ms = max(seg.pause_before_ms, 700)
                seg.pause_after_ms = max(seg.pause_after_ms, 1000)

            elif seg_type == "subheading":
                rate_var = -4
                pitch_var = -1
                seg.pause_before_ms = max(seg.pause_before_ms, 450)
                seg.pause_after_ms = max(seg.pause_after_ms, 700)

            elif seg_type in ("shloka", "stanza", "verse_line", "mantra", "chant_refrain"):
                rate_var = -10
                pitch_var = -2
                seg.pause_before_ms = max(seg.pause_before_ms, 500)
                seg.pause_after_ms = max(seg.pause_after_ms, 900)

            elif seg_type in ("quote", "dialogue"):
                rate_var = -3
                pitch_var = +2
                seg.pause_before_ms = max(seg.pause_before_ms, 250)
                seg.pause_after_ms = max(seg.pause_after_ms, 400)

            elif seg_type == "question":
                rate_var = 0
                pitch_var = +3
                seg.pause_before_ms = max(seg.pause_before_ms, 250)
                seg.pause_after_ms = max(seg.pause_after_ms, 500)

            elif seg_type in ("emphasis", "exclamation"):
                rate_var = -2
                pitch_var = +1
                vol_var = +3
                seg.pause_before_ms = max(seg.pause_before_ms, 200)
                seg.pause_after_ms = max(seg.pause_after_ms, 450)

            elif seg_type == "reflective":
                rate_var = -3
                pitch_var = +1
                seg.pause_before_ms = max(seg.pause_before_ms, 300)
                seg.pause_after_ms = max(seg.pause_after_ms, 400)

            elif seg_type == "conclusion":
                rate_var = -4
                pitch_var = -1
                seg.pause_before_ms = max(seg.pause_before_ms, 350)
                seg.pause_after_ms = max(seg.pause_after_ms, 650)

            else:  # Ordinary prose: Hierarchical discourse-level prosody
                is_opener = (in_para_idx == 0)
                is_closer = is_next_boundary

                if is_opener and is_closer:
                    # Single-sentence standalone paragraph: topic opener & resolution in one
                    rate_var = -2
                    pitch_var = +1
                    if seg.pause_after_ms == 0:
                        seg.pause_after_ms = max(self.profile.paragraph_pause_ms, 450)
                elif is_opener:
                    # Paragraph topic opener: F0 pitch reset (+2Hz) and deliberate pacing (-3%)
                    rate_var = -3
                    pitch_var = +2
                    if seg.pause_after_ms == 0:
                        seg.pause_after_ms = self.profile.sentence_pause_ms
                elif is_closer:
                    # Paragraph cadential closer: terminal pitch drop (-1Hz) and deceleration (-4%)
                    rate_var = -4
                    pitch_var = -1
                    if seg.pause_after_ms == 0:
                        seg.pause_after_ms = max(self.profile.paragraph_pause_ms, 450)
                else:
                    # Paragraph body development: linear F0 declination tilt
                    if in_para_idx == 1:
                        rate_var = 0
                        pitch_var = +1
                    elif in_para_idx == 2:
                        rate_var = +1
                        pitch_var = 0
                    else:
                        rate_var = 0
                        pitch_var = max(-1, 0 - (in_para_idx - 2))

                    if seg.pause_after_ms == 0:
                        seg.pause_after_ms = self.profile.sentence_pause_ms

            final_rate = base_rate_val + rate_var
            final_pitch = base_pitch_val + pitch_var
            final_vol = vol_var

            seg.rate = f"{final_rate:+}%".replace("++", "+")
            seg.pitch = f"{final_pitch:+}Hz".replace("++", "+")
            seg.volume = f"{final_vol:+}%".replace("++", "+")

            # Apply clause-level prosodic intonation marking to the speech text
            target_text = seg.pronunciation_text or seg.source_text
            seg.pronunciation_text = apply_prosodic_marking(target_text, seg_type)

        return segments
