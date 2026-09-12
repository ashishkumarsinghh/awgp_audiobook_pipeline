import os
import asyncio
from typing import List
from src.core.types import SpeechSegment

class TTSProvider:
    async def synthesize(self, segment: SpeechSegment, output_path: str) -> str:
        raise NotImplementedError

class EdgeTTSProvider(TTSProvider):
    def __init__(self, voice: str):
        self.voice = voice

    async def synthesize(self, segment: SpeechSegment, output_path: str) -> str:
        text = segment.pronunciation_text.replace("'", "'\''")
        cmd = (
            f"edge-tts --voice {self.voice} "
            f"--rate='{segment.rate}' "
            f"--pitch='{segment.pitch}' "
            f"--volume='{segment.volume}' "
            f"--text='{text}' "
            f"--write-media '{output_path}'"
        )
        
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        segment.audio_file = output_path
        return output_path

class AzureSpeechProvider(TTSProvider):
    pass