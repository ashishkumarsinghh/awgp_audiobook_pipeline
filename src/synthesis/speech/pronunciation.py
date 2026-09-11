import re

class PronunciationDictionary:
    def __init__(self):
        # Maps canonical Devanagari to phonetic spellings optimized for Edge-TTS / Azure TTS
        # These replacements ONLY happen on the text sent to the TTS engine.
        self.exact_words = {
            # Ha conjuncts
            "ब्रह्म": "ब्रम्ह",
            "ब्राह्मण": "ब्राम्हण",
            "चिह्न": "चिन्ह",
            "आह्वान": "आव्हान",
            "अपराह्न": "अपरान्ह",
            
            # Gya conjuncts (often mispronounced depending on voice)
            "ज्ञान": "ग्यान",
            "अज्ञान": "अग्यान",
            "प्रज्ञा": "प्रग्या",
            "यज्ञ": "यग्य",
            "विद्वान": "विद्वान",
            
            # Vocalic Ri
            "ऋषि": "रिषि",
            "ऋतु": "रितु",
            "प्रकृति": "प्रक्रिति",
            "कृपा": "क्रिपा",
            "हृदय": "ह्रिदय",
            "सृष्टि": "स्रिष्टि",
            
            # Om
            "ॐ": "ओम्",
            
            # Common Sanskrit endings often swallowed by Hindi TTS
            "नमः": "नमह",
            "स्वः": "स्वाह", # specifically in Gayatri Mantra context
            "तपः": "तपह",
            "तेजः": "तेजह",
        }
        
        # Regex replacements for general rules
        self.regex_rules = [
            # Handle Visarga at the end of words (e.g., भूर्भुवः -> भूर्भुवह)
            (re.compile(r"(\S+)ः(?=\s|$)"), r"\1ह"),
            # Handle Avagraha (ऽ) - replace with 'अ' for proper phonetic reading
            (re.compile(r"ऽ"), r"अ"),
            # Double Danda (॥) - TTS often ignores it, replace with single Danda (।) for pause
            (re.compile(r"॥"), r"।"),
        ]

    def apply(self, text: str) -> str:
        words = text.split()
        processed_words = []
        for w in words:
            # Strip punctuation for exact match check
            clean_w = re.sub(r"[।॥,.;\-?!'\"]", "", w)
            if clean_w in self.exact_words:
                # Replace the core word but keep punctuation
                w = w.replace(clean_w, self.exact_words[clean_w])
            processed_words.append(w)
            
        processed_text = " ".join(processed_words)
        
        for pattern, replacement in self.regex_rules:
            processed_text = pattern.sub(replacement, processed_text)
            
        return processed_text