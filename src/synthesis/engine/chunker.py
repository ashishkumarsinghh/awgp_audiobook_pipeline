import hashlib
import json

class SemanticChunker:
    @staticmethod
    def chunk_plan(plan: list[dict], max_chars: int = 4000) -> list[dict]:
        chunks = []
        current_chunk = []
        current_len = 0
        
        for p in plan:
            if current_len + len(p['text']) > max_chars and current_chunk:
                chunks.append(SemanticChunker._create_chunk(current_chunk))
                current_chunk = []
                current_len = 0
            
            current_chunk.append(p)
            current_len += len(p['text'])
            
        if current_chunk:
            chunks.append(SemanticChunker._create_chunk(current_chunk))
            
        return chunks
        
    @staticmethod
    def _create_chunk(plan_items: list[dict]) -> dict:
        content_str = json.dumps(plan_items, sort_keys=True)
        chunk_id = hashlib.sha256(content_str.encode()).hexdigest()[:12]
        return {
            "chunk_id": chunk_id,
            "items": plan_items
        }
