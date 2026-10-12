import os
import json
import asyncio
import re
from pathlib import Path
from src.synthesis.providers import EdgeTTSProvider
from src.core.types import SpeechSegment
from src.synthesis.audio.enhancer import AudioEnhancer

def fix_hindi_punctuation(text: str) -> str:
    # Remove comma before 'कि'
    text = re.sub(r',\s*कि\b', ' कि', text)
    # Remove comma before 'और'
    text = re.sub(r',\s*और\b', ' और', text)
    # Ensure proper spacing around dandas and commas
    text = re.sub(r'\s+।', '।', text)
    text = re.sub(r'\s+,', ',', text)
    return text

def apply_pronunciation(text: str) -> str:
    # Hardcoded test rules based on config
    rules = {
        "साधन-शक्ति": "साधन शक्ति",
        "रुग्ण": "रुग्न",
        # अक्षत, प्रवृत्त, मानसिक सहयोग kept as is for testing, Edge TTS usually handles them if we don't force bad halants
    }
    for k, v in rules.items():
        text = text.replace(k, v)
    return text

def split_into_breath_groups(text: str):
    """Semantic prosody planner: splits into breath groups"""
    # Simple semantic splitting on Hindi clause boundaries
    # split on ।, ?, ! and internal commas.
    # We will just segment by comma or danda, taking care not to split inside words.
    parts = re.split(r'(।|\?|!|,)', text)
    groups = []
    current_group = ""
    for part in parts:
        if part in ['।', '?', '!', ',']:
            current_group += part
            if current_group.strip():
                groups.append(current_group.strip())
            current_group = ""
        else:
            current_group += part
    if current_group.strip():
        groups.append(current_group.strip())
    return groups

async def generate_ab_test():
    project_dir = Path("projects/HINR0791_MAN_SADHE_JIVAN_SADHEI_Re2014")
    output_dir = project_dir / "output_improved"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Original text
    chunk_0005 = "बहुत बार देखा जा सकता है कि साधन-शक्ति तथा आवश्यकता होने पर भी जब मन नहीं चाहता तो अनेक कार्य बिना किए पड़े रहते हैं। शरीर के अक्षत रहते हुए भी मानसिक सहयोग के बिना कोई काम नहीं बनता और जब मन चाहता है तो एक बार रुग्ण शरीर भी कार्य में प्रवृत्त हो जाता है। जो काम मन से किया जाता है वह अच्छा भी होता है, और जल्दी भी।"
    
    # OLD Pipeline Output
    provider = EdgeTTSProvider(voice="hi-IN-MadhurNeural")
    old_segment = SpeechSegment(
        source_text=chunk_0005,
        normalized_text=chunk_0005,
        pronunciation_text=chunk_0005,
        segment_type="prose",
        pause_after_ms=350
    )
    
    old_output_path = output_dir / "chunk_0005_old.wav"
    await provider.synthesize(old_segment, str(old_output_path))
    
    # Improve text
    # 1. Editorial corrections (as defined by the user for reference)
    editorial_text = """बहुत बार देखा जा सकता है कि साधन-शक्ति तथा आवश्यकता होने पर भी,
जब मन नहीं चाहता, तो अनेक कार्य बिना किए पड़े रहते हैं।
शरीर के अक्षत रहते हुए भी, मानसिक सहयोग के बिना कोई काम नहीं बनता।
और जब मन चाहता है, तो एक बार रुग्ण शरीर भी कार्य में प्रवृत्त हो जाता है।
जो काम मन से किया जाता है, वह अच्छा भी होता है और जल्दी भी।"""
    
    # Replace newlines with spaces for clean processing
    editorial_text = editorial_text.replace('\n', ' ')
    editorial_text = fix_hindi_punctuation(editorial_text)
    
    # Create breath groups
    groups = split_into_breath_groups(editorial_text)
    
    # Synthesize each breath group
    new_chunks = []
    for i, group in enumerate(groups):
        if not group.strip(): continue
        
        # Determine pause duration
        pause_ms = 150 # default short grammatical clause
        if group.endswith('।') or group.endswith('?') or group.endswith('!'):
            pause_ms = 650 # ordinary sentence ending
        elif group.endswith(','):
            pause_ms = 300 # meaningful clause boundary
            
        tts_text = apply_pronunciation(group)
        
        seg = SpeechSegment(
            source_text=group,
            normalized_text=group,
            pronunciation_text=tts_text,
            segment_type="prose",
            pause_after_ms=pause_ms,
            pause_before_ms=0
        )
        out_path = output_dir / f"chunk_0005_new_part_{i}.wav"
        await provider.synthesize(seg, str(out_path))
        new_chunks.append(seg)
        
    from src.synthesis.assembler import AudioAssembler
    assembler = AudioAssembler(str(output_dir / "chunk_0005_improved.mp3"), speed=1.0)
    assembler.assemble(new_chunks)
    
    # Also assemble the old one just to have mp3 version
    assembler_old = AudioAssembler(str(output_dir / "chunk_0005_old.mp3"), speed=1.0)
    assembler_old.assemble([old_segment])
    
    print("A/B test generated in output_improved/")

if __name__ == "__main__":
    asyncio.run(generate_ab_test())
