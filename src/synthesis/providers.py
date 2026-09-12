import os
import re
import asyncio
import edge_tts
import tempfile
from pathlib import Path
from src.synthesis.audio.io import run_ffmpeg
from typing import List, Optional
from src.core.types import SpeechSegment

class TTSProvider:
    async def synthesize(self, segment: SpeechSegment, output_path: str) -> str:
        raise NotImplementedError

class EdgeTTSProvider(TTSProvider):
    def __init__(self, voice: str = "hi-IN-SwaraNeural"):
        self.voice = voice

    async def synthesize(self, segment: SpeechSegment, output_path: str) -> str:
        text = segment.pronunciation_text or segment.normalized_text or segment.source_text
        text = re.sub(r'<[^>]+>', '', text or '').strip()
        if not text:
            raise ValueError("Cannot synthesize empty narration.")
        output = Path(output_path)
        if output.suffix.lower() not in {".wav", ".mp3"}:
            raise ValueError("Edge TTS output must be .wav or .mp3.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".edge-", dir=output.parent) as temporary:
            mp3 = Path(temporary) / "speech.mp3"
            communicate = edge_tts.Communicate(
                text=text, voice=self.voice, rate=segment.rate or "+0%",
                pitch=segment.pitch or "+0Hz", volume=segment.volume or "+0%")
            await asyncio.wait_for(communicate.save(str(mp3)), timeout=30)
            if not mp3.is_file() or not mp3.stat().st_size:
                raise RuntimeError("Edge TTS returned no audio.")
            if output.suffix.lower() == ".wav":
                await asyncio.to_thread(run_ffmpeg, ["-i", mp3, "-ac", "1", "-ar", "24000", "-acodec", "pcm_s16le", output])
            else:
                os.replace(mp3, output)
        segment.audio_file = str(output)
        return str(output)

class GeminiTTSProvider(TTSProvider):
    """Legacy gemini option: Google Cloud TTS with ADC, not Gemini audio generation.

    This adapter fails explicitly rather than silently changing the selected voice/provider.
    """
    def __init__(self, voice: str = "hi-IN-Wavenet-A"):
        self.voice = voice
        self._client = None
        self._tts_client = None

    @property
    def client(self):
        if self._client is None:
            api_key = os.environ.get('GEMINI_API_KEY')
            if api_key:
                try:
                    from google import genai
                    self._client = genai.Client(api_key=api_key)
                except ImportError:
                    pass
        return self._client

    @property
    def tts_client(self):
        """Get Google Cloud TTS client if credentials are available"""
        if self._tts_client is None:
            try:
                from google.cloud import texttospeech
                # This will use Application Default Credentials
                self._tts_client = texttospeech.TextToSpeechClient()
            except (ImportError, Exception):
                pass
        return self._tts_client

    async def synthesize(self, segment: SpeechSegment, output_path: str) -> str:
        text = segment.pronunciation_text or segment.normalized_text or segment.source_text
        text = text.strip() if text else ""

        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        is_wav = output_path.endswith(".wav")

        if not text:
            raise ValueError("Cannot synthesize empty narration.")
        if not is_wav:
            raise ValueError("Google Cloud TTS currently requires .wav output.")
        if not self.tts_client:
            raise RuntimeError("Google Cloud TTS is unavailable. Install google-cloud-texttospeech and configure Application Default Credentials, or explicitly select Edge.")
        return await self._synthesize_with_gcloud_tts(segment, output_path, text, is_wav)

    async def _synthesize_with_gcloud_tts(self, segment: SpeechSegment, output_path: str, text: str, is_wav: bool) -> str:
        """Use Google Cloud Text-to-Speech API"""
        try:
            from google.cloud import texttospeech

            synthesis_input = texttospeech.SynthesisInput(text=text)

            # Map segment type to voice
            voice_name = self.voice

            voice = texttospeech.VoiceSelectionParams(
                language_code="hi-IN",
                name=voice_name,
            )

            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
                speaking_rate=max(0.25, min(2.0, 1 + int(segment.rate.rstrip("%")) / 100)),
            )

            response = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.tts_client.synthesize_speech(
                        input=synthesis_input,
                        voice=voice,
                        audio_config=audio_config
                    )
                ),
                timeout=60.0
            )

            with open(output_path, 'wb') as f:
                f.write(response.audio_content)

            segment.audio_file = output_path
            return output_path

        except Exception as e:
            raise RuntimeError(f"Google Cloud TTS failed: {e}") from e

class AzureSpeechProvider(TTSProvider):
    pass
