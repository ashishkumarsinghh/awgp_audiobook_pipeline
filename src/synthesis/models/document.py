from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

class SemanticTag(str, Enum):
    HEADING = "heading"
    SUBHEADING = "subheading"
    PROSE = "prose"
    GLOSS = "gloss"
    SHLOKA = "shloka"

@dataclass
class TextBlock:
    tag: SemanticTag
    text: str
    block_id: int

@dataclass
class Document:
    blocks: List[TextBlock]
