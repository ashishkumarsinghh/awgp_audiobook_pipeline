import os
import re
import asyncio
import edge_tts
from typing import List
from src.core.types import SpeechSegment

class TTSProvider:
    async def synthesize(self, segment: SpeechSegment, output_path: str) -> str:
        raise NotImplementedError

class EdgeTTSProvider(TTSProvider):
    def __init__(self, voice: str = "hi-IN-SwaraNeural"):
        self.voice = voice

    async def synthesize(self, segment: SpeechSegment, output_path: str) -> str:
        text = segment.pronunciation_text or segment.normalized_text or segment.source_text
        text = text.strip() if text else ""
        
        # Scrub any stray XML/HTML markup (e.g. <prose>, <shloka>, <heading>)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        is_wav = output_path.endswith(".wav")
        # Ensure temporary MP3 has a strictly distinct filename from final WAV
        tmp_mp3 = (output_path[:-4] if is_wav else output_path) + "_edge_tmp.mp3"
        
        if not text:
            # Generate a 100ms silent audio chunk if text is blank
            if is_wav:
                cmd = f"ffmpeg -y -f lavfi -i aevalsrc=0 -t 0.1 -ar 24000 -ac 1 -c:a pcm_s16le '{output_path}' -loglevel error"
                os.system(cmd)
            segment.audio_file = output_path
            return output_path

        # Use Madhur for shlokas and Swara for narration
        voice = "hi-IN-MadhurNeural" if segment.segment_type == "shloka" else self.voice
        rate = segment.rate if segment.rate else "+0%"
        pitch = segment.pitch if segment.pitch else "+0Hz"
        volume = segment.volume if segment.volume else "+0%"

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
            volume=volume
        )
        await communicate.save(tmp_mp3)

        if is_wav:
            # Convert to standard 24kHz mono 16-bit PCM WAV
            cmd = f"ffmpeg -y -i '{tmp_mp3}' -ac 1 -ar 24000 -acodec pcm_s16le '{output_path}' -loglevel error"
            ret = os.system(cmd)
            if os.path.exists(tmp_mp3):
                try:
                    os.remove(tmp_mp3)
                except OSError:
                    pass
            if ret != 0 or not os.path.exists(output_path):
                raise RuntimeError(f"FFmpeg audio conversion failed for {output_path}")

        segment.audio_file = output_path
        return output_path

class AzureSpeechProvider(TTSProvider):
    pass
