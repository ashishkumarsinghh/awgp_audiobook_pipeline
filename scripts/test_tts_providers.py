import os
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.types import SpeechSegment
from src.synthesis.providers import EdgeTTSProvider, GeminiTTSProvider


async def test_edge_tts():
    """Test EdgeTTSProvider"""
    print("=" * 60)
    print("Testing EdgeTTSProvider")
    print("=" * 60)
    
    provider = EdgeTTSProvider(voice="hi-IN-SwaraNeural")
    
    test_cases = [
        SpeechSegment(
            source_text="नमस्ते, यह एक परीक्षण है।",
            normalized_text="नमस्ते, यह एक परीक्षण है।",
            pronunciation_text="नमस्ते, यह एक परीक्षण है।",
            segment_type="prose"
        ),
        SpeechSegment(
            source_text="ॐ भूर्भुवः स्वः",
            normalized_text="ॐ भूर्भुवः स्वः",
            pronunciation_text="ॐ भूर्भुवः स्वः",
            segment_type="shloka"
        ),
        SpeechSegment(
            source_text="अध्याय एक",
            normalized_text="अध्याय एक",
            pronunciation_text="अध्याय एक",
            segment_type="heading"
        ),
    ]
    
    output_dir = Path("/tmp/tts_test")
    output_dir.mkdir(exist_ok=True)
    
    for i, segment in enumerate(test_cases):
        output_path = output_dir / f"edge_test_{i+1}.wav"
        print(f"\nTest {i+1}: {segment.segment_type} - {segment.source_text[:50]}")
        try:
            result = await provider.synthesize(segment, str(output_path))
            if output_path.exists() and output_path.stat().st_size > 100:
                print(f"  ✓ Success: {output_path} ({output_path.stat().st_size} bytes)")
            else:
                print(f"  ✗ Failed: File not created or too small")
        except Exception as e:
            print(f"  ✗ Error: {e}")


async def test_gemini_tts():
    """Test GeminiTTSProvider"""
    print("\n" + "=" * 60)
    print("Testing GeminiTTSProvider")
    print("=" * 60)
    
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("⚠ GEMINI_API_KEY not set - skipping Gemini TTS test")
        return
    
    provider = GeminiTTSProvider(voice="hi-IN-AaryaNeural")
    
    test_cases = [
        SpeechSegment(
            source_text="नमस्ते, यह एक परीक्षण है।",
            normalized_text="नमस्ते, यह एक परीक्षण है।",
            pronunciation_text="नमस्ते, यह एक परीक्षण है।",
            segment_type="prose"
        ),
        SpeechSegment(
            source_text="ॐ भूर्भुवः स्वः",
            normalized_text="ॐ भूर्भुवः स्वः",
            pronunciation_text="ॐ भूर्भुवः स्वः",
            segment_type="shloka"
        ),
    ]
    
    output_dir = Path("/tmp/tts_test")
    output_dir.mkdir(exist_ok=True)
    
    for i, segment in enumerate(test_cases):
        output_path = output_dir / f"gemini_test_{i+1}.wav"
        print(f"\nTest {i+1}: {segment.segment_type} - {segment.source_text[:50]}")
        try:
            result = await provider.synthesize(segment, str(output_path))
            if output_path.exists() and output_path.stat().st_size > 100:
                print(f"  ✓ Success: {output_path} ({output_path.stat().st_size} bytes)")
            else:
                print(f"  ✗ Failed: File not created or too small")
        except Exception as e:
            print(f"  ✗ Error: {e}")


async def main():
    print("TTS Provider Independent Test")
    print("=" * 60)
    
    await test_edge_tts()
    await test_gemini_tts()
    
    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())