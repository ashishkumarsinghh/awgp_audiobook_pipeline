import json
import os

class ManifestManager:
    def __init__(self, manifest_path: str):
        self.manifest_path = manifest_path
        self.manifest = self._load()
        
    def _load(self):
        if os.path.exists(self.manifest_path):
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"chunks": {}}
        
    def save(self):
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, indent=2)
            
    def mark_completed(self, chunk_id: str, output_path: str):
        self.manifest['chunks'][chunk_id] = {
            "status": "completed",
            "output_path": output_path
        }
        self.save()
        
    def is_completed(self, chunk_id: str) -> bool:
        return self.manifest['chunks'].get(chunk_id, {}).get("status") == "completed"
