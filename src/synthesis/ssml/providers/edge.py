import xml.sax.saxutils
from src.synthesis.ssml.providers.base import SSMLRenderer

class EdgeTTSRenderer(SSMLRenderer):
    def render(self, plan: list[dict]) -> str:
        ssml = ["<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='hi-IN'>"]
        for p in plan:
            if p['pause_before'] > 0:
                ssml.append(f"<break time='{p['pause_before']}ms'/>")
            
            rate_pct = int((p['rate'] - 1.0) * 100)
            rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"
            escaped_text = xml.sax.saxutils.escape(p['text'])
            
            # Simple handling for shloka line breaks
            if p['tag'] == 'shloka':
                lines = escaped_text.split('\n')
                escaped_text = f"<break time='450ms'/>".join(lines)
            
            ssml.append(f"<prosody rate='{rate_str}'>{escaped_text}</prosody>")
            
            if p['pause_after'] > 0:
                ssml.append(f"<break time='{p['pause_after']}ms'/>")
                
        ssml.append("</speak>")
        return "\n".join(ssml)
