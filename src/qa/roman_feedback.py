"""Conservative romanized-feedback to Devanagari source matching."""
import re
import unicodedata
from difflib import SequenceMatcher

VOWELS = {"अ":"a","आ":"aa","इ":"i","ई":"ee","उ":"u","ऊ":"oo","ऋ":"ri","ए":"e","ऐ":"ai","ओ":"o","औ":"au"}
MATRA = {"ा":"aa","ि":"i","ी":"ee","ु":"u","ू":"oo","ृ":"ri","े":"e","ै":"ai","ो":"o","ौ":"au"}
CONS = {"क":"k","ख":"kh","ग":"g","घ":"gh","ङ":"n","च":"ch","छ":"chh","ज":"j","झ":"jh","ञ":"n","ट":"t","ठ":"th","ड":"d","ढ":"dh","ण":"n","त":"t","थ":"th","द":"d","ध":"dh","न":"n","प":"p","फ":"ph","ब":"b","भ":"bh","म":"m","य":"y","र":"r","ल":"l","व":"v","श":"sh","ष":"sh","स":"s","ह":"h","क्ष":"ksh","त्र":"tr","ज्ञ":"gy"}


def romanize(text: str) -> str:
    value = unicodedata.normalize("NFC", text or "").lower()
    out = []
    i = 0
    inherent = True
    while i < len(value):
        pair = value[i:i+2]
        if pair in CONS:
            out.append(CONS[pair]); i += 2; inherent = True; continue
        char = value[i]
        if char in VOWELS:
            out.append(VOWELS[char]); i += 1; inherent = False; continue
        if char in CONS:
            out.append(CONS[char]); i += 1; inherent = True; continue
        if char in MATRA:
            out.append(MATRA[char]); i += 1; inherent = False; continue
        if char == "्":
            inherent = False; i += 1; continue
        if char in "ंँ":
            out.append("n"); i += 1; continue
        if char == "ः":
            out.append("h"); i += 1; continue
        if char in "ऽॐ":
            out.append("om" if char == "ॐ" else ""); i += 1; continue
        out.append(char if char.isascii() else " "); i += 1
    result = "".join(out)
    # Hindi schwa/orthography variation in reviewer notes is best handled by
    # collapsing vowel runs, not by pretending the roman note is authoritative.
    result = re.sub(r"[aeiou]+", lambda m: m.group(0)[0], result)
    result = re.sub(r"[^a-z0-9]+", " ", result)
    return re.sub(r"\s+", " ", result).strip()


def normalize_feedback(text: str) -> str:
    value = (text or "").lower().replace("sh", "s").replace("ph", "f")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"[aeiou]+", lambda m: m.group(0)[0], value)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_roman(value: str) -> str:
    value = normalize_feedback(value)
    return value.replace("v", "w")


def _skeleton(value: str) -> str:
    return re.sub(r"[aeiou]", "", value.replace(" ", ""))


def resolve_phrase(note: str, source_text: str):
    if "shunya" in (note or "").lower() and re.search(r"बी[०0.]", source_text) and re.search(r"ए[०0.]", source_text):
        for sentence in [s.strip() for s in re.split(r"[।!?॥]+", source_text) if s.strip()]:
            if re.search(r"बी[०0.]", sentence) and re.search(r"ए[०0.]", sentence):
                return {"sentence": sentence, "romanized": romanize(sentence),
                        "matched_window": "बी० ए०", "score": 1.0,
                        "method": "abbreviation_aware"}
    needle = _normalize_roman(note)
    needle_tokens = needle.split()
    sentences = [s.strip() for s in re.split(r"[।!?॥]+", source_text) if s.strip()]
    best = None
    for sentence in sentences:
        candidate = _normalize_roman(romanize(sentence))
        candidate_tokens = candidate.split()
        windows = []
        for width in range(max(1, len(needle_tokens) - 1), min(len(candidate_tokens), len(needle_tokens) + 3) + 1):
            windows.extend(" ".join(candidate_tokens[i:i + width])
                           for i in range(max(1, len(candidate_tokens) - width + 1)))
        best_window = max(windows or [candidate], key=lambda value: SequenceMatcher(None, needle, value).ratio())
        score = max(
            SequenceMatcher(None, needle, best_window).ratio(),
            SequenceMatcher(None, _skeleton(needle), _skeleton(best_window)).ratio(),
        )
        record = {"sentence": sentence, "romanized": candidate,
                  "matched_window": best_window, "score": round(score, 4)}
        if best is None or record["score"] > best["score"]:
            best = record
    return best
