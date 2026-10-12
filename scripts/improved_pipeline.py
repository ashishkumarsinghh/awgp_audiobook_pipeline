import os
import json
import asyncio
import re
from pathlib import Path
import unicodedata
from src.synthesis.providers import EdgeTTSProvider
from src.core.types import SpeechSegment
from src.synthesis.assembler import AudioAssembler
from src.synthesis.audio.enhancer import AudioEnhancer

def fix_hindi_punctuation(text: str) -> str:
    text = re.sub(r',\s*कि\b', ' कि', text)
    text = re.sub(r',\s*और\b', ' और', text)
    text = re.sub(r'\s+।', '।', text)
    text = re.sub(r'\s+,', ',', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    # Basic cleanup
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def apply_pronunciation(text: str, config: dict) -> str:
    for rule in config.get("rules", []):
        text = text.replace(rule["source"], rule["tts_alias"])
    return text

def split_into_breath_groups(text: str):
    parts = re.split(r'(।|॥|\?|!|,)', text)
    groups = []
    current_group = ""
    for part in parts:
        if part in ['।', '॥', '?', '!', ',']:
            current_group += part
            if current_group.strip():
                groups.append(current_group.strip())
            current_group = ""
        else:
            current_group += part
    if current_group.strip():
        groups.append(current_group.strip())
    return groups

async def process_project(project_dir: Path):
    print(f"Starting improved pipeline for {project_dir.name}")
    
    # 1. Read config
    config_path = Path("configs/improved_pronunciation.json")
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            pronunciation_config = json.load(f)
    else:
        pronunciation_config = {"rules": []}

    # 2. Read OCR raw text
    ocr_file = project_dir / "01_ocr_raw.txt"
    with open(ocr_file, "r", encoding="utf-8") as f:
        ocr_text = f.read()

    # 3. Create output directory
    out_dir = project_dir / "output_improved"
    audio_dir = out_dir / "audio_units"
    audio_dir.mkdir(parents=True, exist_ok=True)
    
    # 4. Parse paragraphs (naively based on XML tags for this demo, or double newlines)
    # We'll rely on the existing 03_segments.json to preserve chunk mapping and just re-process the prose.
    segments_file = project_dir / "03_segments.json"
    with open(segments_file, "r", encoding="utf-8") as f:
        base_segments = json.load(f)

    provider = EdgeTTSProvider(voice="hi-IN-MadhurNeural")
    
    final_master_chunks = []
    qa_report = []

    print(f"Processing {len(base_segments)} chunks...")
    for idx, item in enumerate(base_segments):
        chunk_id = item["id"]
        source_text = item["source_text"]
        segment_type = item["segment_type"]
        
        # We only apply complex chunking to prose
        if segment_type not in ["prose", "paragraph", "quote"]:
            # Just render as is
            tts_text = apply_pronunciation(source_text, pronunciation_config)
            seg = SpeechSegment(
                source_text=source_text,
                normalized_text=source_text,
                pronunciation_text=tts_text,
                segment_type=segment_type,
                pause_after_ms=item.get("pause_after_ms", 500)
            )
            out_path = audio_dir / f"{chunk_id}_full.wav"
            if not out_path.exists():
                try:
                    await provider.synthesize(seg, str(out_path))
                except Exception as e:
                    print(f"Failed to synthesize {chunk_id}: {e}")
                    qa_report.append({"chunk_id": chunk_id, "error": str(e)})
                    continue
            seg.audio_file = str(out_path)
            final_master_chunks.append(seg)
            continue
            
        # For prose: Normalize, Fix Punctuation, split into breath groups
        norm_text = normalize_text(source_text)
        ed_text = fix_hindi_punctuation(norm_text)
        groups = split_into_breath_groups(ed_text)
        
        for i, group in enumerate(groups):
            if not group.strip(): continue
            
            pause_ms = 150
            if group.endswith('।') or group.endswith('॥') or group.endswith('?') or group.endswith('!'):
                pause_ms = 700
            elif group.endswith(','):
                pause_ms = 350
                
            tts_text = apply_pronunciation(group, pronunciation_config)
            seg = SpeechSegment(
                source_text=group,
                normalized_text=group,
                pronunciation_text=tts_text,
                segment_type="prose_part",
                pause_after_ms=pause_ms,
                pause_before_ms=0
            )
            
            part_id = f"{chunk_id}_part_{i}"
            out_path = audio_dir / f"{part_id}.wav"
            if not out_path.exists():
                try:
                    await provider.synthesize(seg, str(out_path))
                except Exception as e:
                    print(f"Failed to synthesize {part_id}: {e}")
                    qa_report.append({"chunk_id": part_id, "error": str(e)})
                    continue
            seg.audio_file = str(out_path)
            final_master_chunks.append(seg)
            
    print("Synthesizing completed. Assembling final master...")
    
    # 5. Assemble chunks
    assembler = AudioAssembler(str(out_dir / "master_improved.wav"), speed=1.0)
    assembler.assemble(final_master_chunks)
    
    print("Mastering audio (-16 LUFS, -1.5 dBTP)...")
    # Apply Mastering via AudioEnhancer but with modified parameters
    AudioEnhancer.apply_studio_mastering(
        input_path=str(out_dir / "master_improved.wav"),
        output_path=str(out_dir / "master_improved.mp3"),
        lossless=False,
        speed=1.0,
        eq_profile="smooth",
        target_lufs=-16.0,
        true_peak=-1.5
    )
    
    # QA JSON report
    with open(out_dir / "qa_report.json", "w", encoding="utf-8") as f:
        json.dump(qa_report, f, indent=2, ensure_ascii=False)
        
    print("Pipeline completed.")

if __name__ == "__main__":
    asyncio.run(process_project(Path("projects/HINR0791_MAN_SADHE_JIVAN_SADHEI_Re2014")))
