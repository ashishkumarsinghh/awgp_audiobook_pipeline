import asyncio
import edge_tts
from pathlib import Path

async def main():
    out_dir = Path("projects/HINR0791_MAN_SADHE_JIVAN_SADHEI_Re2014/test_audio")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Natural Devanagari text (as written by author)
    t1 = "मनुष्य की वास्तविक शक्ति मनोबल ही है। धर्म, सत्य और न्याय की सदा विजय होती है। युद्ध और शस्त्र विहीन सेना समाप्त हो गई।"
    c1 = edge_tts.Communicate(t1, voice="hi-IN-MadhurNeural")
    p1 = out_dir / "1_natural.mp3"
    await c1.save(str(p1))
    print(f"Generated natural: {p1} ({p1.stat().st_size} bytes)")
    
    # 2. Text with halants injected by the current regex rule
    t2 = "मनुष्य् की वास्तविक शक्ति मनोबल ही है। धर्म्, सत्य् और न्याय् की सदा विजय होती है। युद्ध् और शस्त्र् विहीन सेना समाप्त् हो गई।"
    c2 = edge_tts.Communicate(t2, voice="hi-IN-MadhurNeural")
    p2 = out_dir / "2_with_halants.mp3"
    await c2.save(str(p2))
    print(f"Generated halants: {p2} ({p2.stat().st_size} bytes)")

if __name__ == "__main__":
    asyncio.run(main())
