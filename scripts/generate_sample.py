"""Generates audio samples for user listening and verification.

Creates:
1. sample_page_1.mp3 (Page 1: Title + Opening 5 Paragraphs)
2. sample_transition_naubat.mp3 (Chunks 11-13: The healed cross-page transition with "नौबत यहाँ तक आ पहुँचा कि")
3. sample_pages_1_to_4.mp3 (Chunks 1-13: Continuous chapter audio)
"""
import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from src.synthesis.providers import EdgeTTSProvider
from src.synthesis.runner import synthesize_segments, as_segment
from src.synthesis.assembler import AudioAssembler



async def main():
    project_dir = Path("projects/HINR0791_MAN_SADHE_JIVAN_SADHEI_Re2014")
    phonetics_path = project_dir / "02_phonetics" / "phonetics.json"
    
    if not phonetics_path.is_file():
        phonetics_path = project_dir / "04_phonetics.json"
        
    print(f"Reading phonetics from: {phonetics_path}")
    with open(phonetics_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    
    # Target chunks 1 to 13 (covering Page 1 and the Page 3-4 healed transition)
    sample_chunks = [item for item in data if int(item["id"].split("_")[1]) <= 13]
    print(f"Total chunks selected for synthesis: {len(sample_chunks)}")
    
    sample_audio_dir = project_dir / "sample_audio"
    sample_audio_dir.mkdir(parents=True, exist_ok=True)
    
    tts = EdgeTTSProvider(voice="hi-IN-MadhurNeural")
    print(f"Synthesizing {len(sample_chunks)} chunks with EdgeTTS ({tts.voice})...")
    
    await synthesize_segments(
        sample_chunks,
        str(sample_audio_dir),
        tts,
        "edge",
        attempts=2,
        concurrency=3
    )
    print("Synthesis complete! Validating and assembling MP3 master files...")
    
    # 1. Page 1 Sample (Chunks 1 to 6)
    page1_items = [c for c in sample_chunks if int(c["id"].split("_")[1]) <= 6]
    page1_segments = [as_segment(c, str(sample_audio_dir)) for c in page1_items]
    page1_out = project_dir / "sample_page_1.mp3"
    AudioAssembler(str(page1_out)).assemble(page1_segments)
    print(f"Created: {page1_out} ({page1_out.stat().st_size / 1024:.1f} KB)")
    
    # 2. Healed Transition Sample (Chunks 11 to 13)
    transition_items = [c for c in sample_chunks if 11 <= int(c["id"].split("_")[1]) <= 13]
    transition_segments = [as_segment(c, str(sample_audio_dir)) for c in transition_items]
    transition_out = project_dir / "sample_transition_naubat.mp3"
    AudioAssembler(str(transition_out)).assemble(transition_segments)
    print(f"Created: {transition_out} ({transition_out.stat().st_size / 1024:.1f} KB)")
    
    # 3. Continuous Combined Sample (Chunks 1 to 13)
    full_segments = [as_segment(c, str(sample_audio_dir)) for c in sample_chunks]
    full_out = project_dir / "sample_pages_1_to_4.mp3"
    AudioAssembler(str(full_out)).assemble(full_segments)
    print(f"Created: {full_out} ({full_out.stat().st_size / 1024:.1f} KB)")
    
    print("\nAll samples generated successfully!")


if __name__ == "__main__":
    asyncio.run(main())
