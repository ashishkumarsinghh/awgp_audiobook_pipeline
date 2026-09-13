import os
import re
import asyncio
import edge_tts
import tempfile
import html
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

class GoogleCloudTTSProvider(GeminiTTSProvider):
    """Preferred name for the Google Cloud Text-to-Speech adapter.

    GeminiTTSProvider remains as a compatibility alias for existing projects.
    """


class AzureSpeechProvider(TTSProvider):
    """Azure Speech SDK adapter producing the pipeline's canonical WAV format."""
    def __init__(self, voice: str = "hi-IN-SwaraNeural"):
        self.voice = voice
        self._sdk = None

    def _speech_config(self):
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as exc:
            raise RuntimeError("Azure Speech is unavailable. Install azure-cognitiveservices-speech.") from exc
        key, region = os.environ.get("AZURE_SPEECH_KEY"), os.environ.get("AZURE_SPEECH_REGION")
        if not key or not region:
            raise RuntimeError("Azure Speech requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION.")
        config = speechsdk.SpeechConfig(subscription=key, region=region)
        config.speech_synthesis_voice_name = self.voice
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
        )
        return speechsdk, config

    async def synthesize(self, segment: SpeechSegment, output_path: str) -> str:
        text = segment.pronunciation_text or segment.normalized_text or segment.source_text
        text = re.sub(r"<[^>]+>", "", text or "").strip()
        if not text:
            raise ValueError("Cannot synthesize empty narration.")
        if not str(output_path).lower().endswith(".wav"):
            raise ValueError("Azure Speech output must be .wav.")
        speechsdk, config = self._speech_config()
        escaped = html.escape(text)
        ssml = (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xml:lang="hi-IN"><voice name="{html.escape(self.voice)}">'
                f'<prosody rate="{segment.rate or "+0%"}" pitch="{segment.pitch or "+0Hz"}" '
                f'volume="{segment.volume or "+0%"}">{escaped}</prosody></voice></speak>')
        output = str(output_path)

        def run():
            audio = speechsdk.audio.AudioOutputConfig(filename=output)
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=audio)
            result = synthesizer.speak_ssml_async(ssml).get()
            if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
                details = getattr(result, "cancellation_details", None)
                raise RuntimeError(f"Azure Speech failed: {details or result.reason}")

        await asyncio.to_thread(run)
        if not Path(output).is_file() or not Path(output).stat().st_size:
            raise RuntimeError("Azure Speech returned no audio.")
        segment.audio_file = output
        return output


VOICE_CATALOG = [
    {"provider": "edge", "voice": "hi-IN-SwaraNeural", "label": "Swara (Hindi, female)", "tier": "recommended", "sanskrit": True},
    {"provider": "edge", "voice": "hi-IN-MadhurNeural", "label": "Madhur (Hindi, male)", "tier": "recommended", "sanskrit": True},
    {"provider": "google", "voice": "hi-IN-Neural2-A", "label": "Neural2 A (Hindi, female)", "tier": "recommended", "sanskrit": True},
    {"provider": "google", "voice": "hi-IN-Neural2-B", "label": "Neural2 B (Hindi, male)", "tier": "recommended", "sanskrit": True},
    {"provider": "azure", "voice": "hi-IN-SwaraNeural", "label": "Swara (Hindi, female)", "tier": "recommended", "sanskrit": True},
    {"provider": "azure", "voice": "hi-IN-MadhurNeural", "label": "Madhur (Hindi, male)", "tier": "recommended", "sanskrit": True},
]
