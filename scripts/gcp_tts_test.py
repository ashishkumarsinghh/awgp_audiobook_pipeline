import os
import json
import asyncio
import re
from pathlib import Path
from src.synthesis.providers import GoogleCloudTTSProvider
from src.core.types import SpeechSegment
from src.synthesis.assembler import AudioAssembler

async def generate_gcp_ab_test():
    project_dir = Path("projects/HINR0791_MAN_SADHE_JIVAN_SADHEI_Re2014")
    output_dir = project_dir / "output_improved_gcp"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # GCP allows up to 5000 bytes. We combine our sentences using SSML <break> tags.
    # We can also add <emphasis> for key words.
    
    # Original text edited for natural punctuation
    ssml_text = """<speak>
<prosody rate="slow">बहुत बार देखा जा सकता है कि <emphasis level="moderate">साधन-शक्ति</emphasis> तथा आवश्यकता होने पर भी,</prosody>
<break time="350ms"/>
<prosody rate="slow">जब मन नहीं चाहता, तो अनेक कार्य बिना किए पड़े रहते हैं।</prosody>
<break time="700ms"/>
<prosody rate="slow">शरीर के <emphasis level="moderate">अक्षत</emphasis> रहते हुए भी, मानसिक सहयोग के बिना कोई काम नहीं बनता।</prosody>
<break time="700ms"/>
<prosody rate="slow">और जब मन चाहता है, तो एक बार <emphasis level="strong">रुग्न</emphasis> शरीर भी कार्य में <emphasis level="strong">प्रवृत्त</emphasis> हो जाता है।</prosody>
<break time="700ms"/>
<prosody rate="slow">जो काम मन से किया जाता है, वह अच्छा भी होता है और जल्दी भी।</prosody>
<break time="700ms"/>
</speak>"""
    
    # Provider
    provider = GoogleCloudTTSProvider(voice="hi-IN-Neural2-B")
    
    seg = SpeechSegment(
        source_text="GCP SSML Test",
        normalized_text="GCP SSML Test",
        pronunciation_text=ssml_text,
        segment_type="prose",
        pause_after_ms=0,
        pause_before_ms=0
    )
    
    out_path = output_dir / "chunk_0005_gcp_ssml.wav"
    try:
        await provider.synthesize(seg, str(out_path))
        print(f"Generated GCP SSML audio at {out_path}")
        
        # Assemble it just to mp3 for easy listening
        assembler = AudioAssembler(str(output_dir / "chunk_0005_gcp_ssml.mp3"), speed=1.0)
        assembler.assemble([seg])
        print(f"Mastered GCP SSML audio at {output_dir / 'chunk_0005_gcp_ssml.mp3'}")
    except Exception as e:
        print(f"Failed to generate GCP SSML audio: {e}")

if __name__ == "__main__":
    asyncio.run(generate_gcp_ab_test())
