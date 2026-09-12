import json
import re
import unicodedata
from typing import List, Dict

class PronunciationDictionary:
    def __init__(self, dict_path: str = None):
        self.exact_words: Dict[str, str] = {}
        self.exact_phrases: Dict[str, str] = {}
        
        self._init_default_rules()
        
        if dict_path:
            self._load_legacy(dict_path)

    def _init_default_rules(self):
        # 3. Expanded H-Conjunct Metathesis
        h_conjuncts = {
            'ब्रह्म': 'ब्रम्ह', 'ब्रह्मा': 'ब्रम्हा', 'ब्राह्मण': 'ब्राम्हण', 
            'ब्राह्मी': 'ब्राम्ही', 'ब्राह्म': 'ब्राम्ह', 'चिह्न': 'चिन्ह', 
            'चिह्नित': 'चिन्हित', 'आह्वान': 'आव्हान', 'आह्वानम्': 'आव्हानम्', 
            'अपराह्न': 'अपरान्ह', 'मध्याह्न': 'मध्यान्ह', 'पूर्वाह्न': 'पूर्वान्ह', 
            'प्रह्लाद': 'प्रल्हाद', 'जिह्वा': 'जिव्हा', 'विह्वल': 'विव्हल'
        }
        # 4. Vocalic R and R-matra
        vocalic_r = {
            'ऋषि': 'रिषि', 'ऋतु': 'रितु', 'ऋग्वेद': 'रिग्वेद', 'ऋचा': 'रिचा', 'ऋण': 'रिण',
            'कृपा': 'क्रिपा', 'प्रकृति': 'प्रक्रिति', 'विकृति': 'विक्रिति', 'संस्कृति': 'संस्क्रिति',
            'हृदय': 'ह्रिदय', 'सृष्टि': 'स्रिष्टि', 'दृष्टि': 'द्रिष्टि', 'वृष्टि': 'व्रिष्टि',
            'अमृत': 'अम्रित', 'स्मृति': 'स्म्रिति', 'गृह': 'ग्रिह', 'पितृ': 'पित्रि', 'मातृ': 'मात्रि',
            'दृढ़': 'द्रिढ़', 'सुदृढ़': 'सुद्रिढ़', 'तृतीय': 'त्रितीय'
        }
        # 5. Sacred Bija Mantras
        bija = {
            'ॐ': 'ओम्', 'ॐकार': 'ओंकार', 'ह्रीं': 'ह्रीम', 'श्रीं': 'श्रीम',
            'क्लीं': 'क्लीम', 'ऐं': 'ऐम', 'हूँ': 'हूम', 'ग्लौं': 'ग्लौम', 
            'फट्': 'फट', 'स्वाहा': 'स्वाहा'
        }
        # 6. Varga Nasals
        varga = {
            'वाङ्मय': 'वांग्मय', 'पञ्च': 'पंच', 'सङ्घ': 'संघ', 
            'शङ्कर': 'शंकर', 'कुण्डलिनी': 'कुंडलिनी'
        }
        # Terminal halant nominals/verbs
        terminal_halants = {
            'भगवान्': 'भगवान', 'विद्वान्': 'विद्वान', 'महान्': 'महान', 'जगत्': 'जगत', 
            'सत्': 'सत', 'चित्': 'चित', 'विद्युत्': 'विद्युत', 'सम्पत्': 'सम्पत',
            'पश्चात्': 'पश्चात', 'साक्षात्': 'साक्षात', 'सम्यक्': 'सम्यक', 'अर्थात्': 'अर्थात', 
            'तस्मात्': 'तस्मात', 'यस्मात्': 'यस्मात',
            'प्रचोदयात्': 'प्रचोदयात', 'कुर्यात्': 'कुर्यात', 'स्यात्': 'स्यात', 'भवेत्': 'भवेत'
        }
        
        for d in [h_conjuncts, vocalic_r, bija, varga, terminal_halants]:
            for k, v in d.items():
                self.add_word(k, v)
        
        # 7. Sandhi Splitting phrases
        phrases = {
            "ॐ भूर्भुवः स्वः": "ओम् भूर्भुवह स्वाह",
            "तत्सवितुर्वरेण्यं": "तत् सवितुर वरेण्यम",
            "धियो यो नः प्रचोदयात्": "धियो यो नह प्रचोदयात",
            "आचमनम्": "आचमनम",
            "शिखाबन्धनम्": "शिखाबन्धनम",
            "प्राणायामः": "प्राणायामह",
            "अघमर्षणम्": "अघमर्षणम",
            "न्यासः": "न्यासह",
            "गायत्र्या": "गायत्रिया",
            "त्र्यम्बकं यजामहे": "त्र्यम्बकम यजामहे",
            "सुगन्धिं पुष्टिवर्धनम्": "सुगन्धिम पुष्टिवर्धनम",
            "मृत्योर्मुक्षीय मामृतात्": "म्रित्योर्मुक्षीय माम्रितात्",
            "सोऽहम्": "सोहम",
            "शिवोऽहम्": "शिवोहम",
            "दासोऽहम्": "दासोहम"
        }
        for k, v in phrases.items():
            self.add_phrase(k, v)

    def _load_legacy(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for item in data:
                    self.add_word(item["source"], item["tts_alias"])
        except FileNotFoundError:
            pass

    def add_word(self, word: str, replacement: str):
        self.exact_words[word] = replacement
        
    def remove_word(self, word: str):
        if word in self.exact_words:
            del self.exact_words[word]

    def add_phrase(self, phrase: str, replacement: str):
        self.exact_phrases[phrase] = replacement
        
    def remove_phrase(self, phrase: str):
        if phrase in self.exact_phrases:
            del self.exact_phrases[phrase]
            
    def explain(self, text: str) -> dict:
        original = text
        applied = self.apply(text)
        return {
            "original": original,
            "transformed": applied,
            "modified": original != applied
        }

    def apply(self, text: str, context: str = "general") -> str:
        # Normalize Unicode and clean TTS-breaking artifacts
        text = unicodedata.normalize('NFC', text)
        text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
        text = re.sub(r'[*#_~^]', '', text)
        
        # Apply Exact Phrases (Sorted by longest first to prevent substring collision)
        for phrase in sorted(self.exact_phrases.keys(), key=len, reverse=True):
            text = text.replace(phrase, self.exact_phrases[phrase])
            
        # Apply Exact Words (Sorted by longest first)
        for word in sorted(self.exact_words.keys(), key=len, reverse=True):
            # Safe Devanagari word boundary: Not preceded/followed by Devanagari chars
            pattern = r'(?<![\u0900-\u097F])' + re.escape(word) + r'(?![\u0900-\u097F])'
            text = re.sub(pattern, self.exact_words[word], text)
            
        # 1. Systematic Visarga Dynamic Echo Rules (Regex)
        # Preceded by i/ii (ि/ी)
        text = re.sub(r'([िी])ः(?=[\s।॥,?!*\'"”’]|$)', r'\1हि', text)
        # Preceded by u/uu (ु/ू)
        text = re.sub(r'([ुू])ः(?=[\s।॥,?!*\'"”’]|$)', r'\1हु', text)
        # Preceded by any other char (inherent 'a', 'ā', 'e', 'ai') -> echo as 'h'
        text = re.sub(r'([^\sिीुू])ः(?=[\s।॥,?!*\'"”’]|$)', r'\1ह', text)
        
        # 2. Terminal Virama / Halant Rule
        # Converts terminal virāmas on specific Sanskrit nominals and verbs (handled via exact_words lexical overrides above).
        
        # Generalized Schwa Deletion for Hindi Prose
        # If context is not a Sanskrit chant, drop the trailing 'a' by adding a halant
        if context not in ["shloka", "mantra"]:
            C = r'[\u0915-\u0939]'
            H = '\u094D'
            M = r'[\u093E-\u094C\u094E-\u094F\u0900-\u0903]'
            pattern = f'({C}{H}{C})(?!{M}|{C}|{H})'
            text = re.sub(pattern, r'\g<1>' + H, text)
            
        return text

    def apply_aliases(self, text: str, context: str = "general") -> str:
        # Legacy mapping for backwards compatibility with pipeline_v2.py
        return self.apply(text, context)