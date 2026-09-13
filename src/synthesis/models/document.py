from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

class SemanticTag(str, Enum):
    BOOK_TITLE = "book_title"
    HEADING = "heading"
    SUBHEADING = "subheading"
    PROSE = "prose"
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    GLOSS = "gloss"
    SHLOKA = "shloka"
    VERSE_LINE = "verse_line"
    STANZA = "stanza"
    MANTRA = "mantra"
    CHANT_REFRAIN = "chant_refrain"
    QUOTE = "quote"
    DIALOGUE = "dialogue"
    FOOTNOTE = "footnote"
    LIST_ITEM = "list_item"
    TABLE = "table"
    CAPTION = "caption"
    TRANSLITERATION = "transliteration"
    FOREIGN_TEXT = "foreign_text"
    NUMBER_OR_DATE = "number_or_date"

@dataclass
class TextBlock:
    tag: SemanticTag
    text: str
    block_id: int

@dataclass
class Document:
    blocks: List[TextBlock]
