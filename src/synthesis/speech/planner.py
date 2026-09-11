from src.synthesis.models.document import Document, SemanticTag
from src.synthesis.models.config import SynthesisConfig
import unicodedata

class SpeechPlanner:
    def __init__(self, config: SynthesisConfig):
        self.config = config
    
    def plan(self, doc: Document) -> list[dict]:
        plan = []
        for block in doc.blocks:
            # Enforce unicode NFC norm (rule 1)
            norm_text = unicodedata.normalize("NFC", block.text)
            rate = self._get_rate(block.tag)
            pause_before, pause_after = self._get_pauses(block.tag)
            plan.append({
                "block_id": block.block_id,
                "tag": block.tag.value,
                "text": norm_text,
                "rate": rate,
                "pause_before": pause_before,
                "pause_after": pause_after
            })
        return plan

    def _get_rate(self, tag: SemanticTag) -> float:
        return getattr(self.config.rates, tag.value)

    def _get_pauses(self, tag: SemanticTag) -> tuple[int, int]:
        c = self.config.pauses
        if tag == SemanticTag.HEADING:
            return c.heading_before, c.heading_after
        elif tag == SemanticTag.SUBHEADING:
            return c.subheading_before, c.subheading_after
        elif tag == SemanticTag.SHLOKA:
            return c.paragraph, c.shloka_end
        elif tag == SemanticTag.GLOSS:
            return c.gloss_before, c.paragraph
        return c.paragraph, c.paragraph
