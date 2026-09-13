import re
from src.synthesis.models.document import Document, TextBlock, SemanticTag

class XMLParser:
    TAGS = "book_title|heading|subheading|prose|paragraph|sentence|gloss|shloka|verse_line|stanza|mantra|chant_refrain|quote|dialogue|footnote|list_item|table|caption|transliteration|foreign_text|number_or_date"

    @staticmethod
    def parse(xml_text: str) -> Document:
        blocks = []
        # Find all tags
        pattern = rf"<({XMLParser.TAGS})>(.*?)</\1>"
        
        # We also need to capture the untagged text between tags as prose.
        # Let's split by the pattern
        parts = re.split(rf"(<(?:{XMLParser.TAGS})>.*?</(?:{XMLParser.TAGS})>)", xml_text, flags=re.DOTALL)
        
        block_id = 0
        for part in parts:
            if not part.strip():
                continue
            
            match = re.match(pattern, part, re.DOTALL)
            if match:
                tag = SemanticTag(match.group(1))
                text = match.group(2).strip()
            else:
                # Untagged text is prose
                tag = SemanticTag.PROSE
                text = part.strip()
                
            if text:
                blocks.append(TextBlock(tag=tag, text=text, block_id=block_id))
                block_id += 1
                
        return Document(blocks=blocks)
