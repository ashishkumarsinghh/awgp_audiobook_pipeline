import re
from src.synthesis.models.document import Document, TextBlock, SemanticTag

class XMLParser:
    @staticmethod
    def parse(xml_text: str) -> Document:
        blocks = []
        pattern = r"<(heading|subheading|prose|gloss|shloka)>(.*?)</\1>"
        matches = re.finditer(pattern, xml_text, re.DOTALL)
        for i, match in enumerate(matches):
            tag = SemanticTag(match.group(1))
            text = match.group(2).strip()
            blocks.append(TextBlock(tag=tag, text=text, block_id=i))
        return Document(blocks=blocks)