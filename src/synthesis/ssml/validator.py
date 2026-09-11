import re

class SSMLValidator:
    @staticmethod
    def validate_preservation(original_text: str, ssml_output: str) -> bool:
        # Strip all XML tags from SSML
        clean_ssml = re.sub(r"<[^>]+>", "", ssml_output)
        clean_ssml = clean_ssml.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        
        # We just need to check if all alphanumeric characters match ignoring spaces/newlines
        def normalize(t):
            return "".join([c for c in t if c.isalnum()])
            
        return normalize(original_text) == normalize(clean_ssml)
