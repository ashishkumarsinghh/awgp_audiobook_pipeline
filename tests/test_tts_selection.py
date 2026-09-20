from src.synthesis.providers import (
    VOICE_CATALOG, GoogleCloudTTSProvider, AzureSpeechProvider,
    GoogleAIStudioTTSProvider, SarvamTTSProvider
)
from src.pipeline_v3 import ProjectManager
from src.core.types import SpeechSegment
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
import base64


def test_curated_catalog_contains_hindi_sanskrit_choices():
    providers = {item["provider"] for item in VOICE_CATALOG}
    assert {"edge", "google", "azure", "studio", "sarvam"} <= providers
    assert all(item["sanskrit"] for item in VOICE_CATALOG)


def test_project_manager_selects_new_adapters(tmp_path):
    assert isinstance(ProjectManager(str(tmp_path), "google").tts, GoogleCloudTTSProvider)
    assert isinstance(ProjectManager(str(tmp_path), "azure").tts, AzureSpeechProvider)
    studio_pm = ProjectManager(str(tmp_path), "studio")
    assert isinstance(studio_pm.tts, GoogleAIStudioTTSProvider)
    assert studio_pm.tts.voice == "Kore"
    studio_charon = ProjectManager(str(tmp_path), "studio", tts_voice="Charon")
    assert studio_charon.tts.voice == "Charon"
    sarvam_pm = ProjectManager(str(tmp_path), "sarvam")
    assert isinstance(sarvam_pm.tts, SarvamTTSProvider)
    assert sarvam_pm.tts.voice == "shubh"


@pytest.mark.anyio
async def test_google_ai_studio_provider_synthesis(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key")
    provider = GoogleAIStudioTTSProvider(voice="Kore")

    mock_client = MagicMock()
    mock_part = MagicMock()
    # 24kHz 16-bit mono PCM silence: 2400 samples = 4800 bytes
    dummy_pcm = b"\x01\x00" * 2400
    mock_part.inline_data.data = dummy_pcm
    mock_part.inline_data.mime_type = "audio/l16; rate=24000; channels=1"
    mock_response = MagicMock()
    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_response.candidates = [mock_candidate]
    mock_client.models.generate_content.return_value = mock_response

    with patch("google.genai.Client", return_value=mock_client):
        seg = SpeechSegment(
            source_text="<prose>गायत्री साधना</prose>",
            normalized_text="<prose>गायत्री साधना</prose>",
            pronunciation_text="<prose>गायत्री साधना</prose>",
            segment_type="prose"
        )
        out_wav = str(tmp_path / "test.wav")
        res = await provider.synthesize(seg, out_wav)
        assert res == out_wav
        assert Path(out_wav).is_file()
        assert Path(out_wav).stat().st_size > len(dummy_pcm) # includes WAV header


@pytest.mark.anyio
async def test_google_ai_studio_provider_empty_narration(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key")
    provider = GoogleAIStudioTTSProvider(voice="Kore")
    seg = SpeechSegment(
        source_text="<tag></tag>",
        normalized_text="<tag></tag>",
        pronunciation_text="<tag></tag>",
        segment_type="prose"
    )
    with pytest.raises(ValueError, match="Cannot synthesize empty narration"):
        await provider.synthesize(seg, str(tmp_path / "out.wav"))


def test_google_ai_studio_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GoogleAIStudioTTSProvider(voice="Kore")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY environment variable is required"):
        _ = provider.client


@pytest.mark.anyio
async def test_sarvam_provider_synthesis(tmp_path, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "dummy_sarvam_key")
    provider = SarvamTTSProvider(voice="shubh")

    dummy_wav = b"RIFF" + b"\x00" * 36 + b"data" + b"\x00" * 100
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "request_id": "test_req",
        "audios": [base64.b64encode(dummy_wav).decode("ascii")]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        seg = SpeechSegment(
            source_text="मन के हारे हार है",
            normalized_text="मन के हारे हार है",
            pronunciation_text="मन के हारे हार है",
            segment_type="prose",
            rate="-5%"
        )
        out_wav = str(tmp_path / "sarvam_out.wav")
        res = await provider.synthesize(seg, out_wav)
        assert res == out_wav
        assert Path(out_wav).is_file()
        assert Path(out_wav).read_bytes() == dummy_wav


@pytest.mark.anyio
async def test_sarvam_provider_empty_narration(tmp_path, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "dummy_sarvam_key")
    provider = SarvamTTSProvider(voice="shubh")
    seg = SpeechSegment(
        source_text="<break></break>",
        normalized_text="",
        pronunciation_text="",
        segment_type="prose"
    )
    with pytest.raises(ValueError, match="Cannot synthesize empty narration"):
        await provider.synthesize(seg, str(tmp_path / "out.wav"))


def test_sarvam_provider_missing_key(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    provider = SarvamTTSProvider(voice="shubh")
    with pytest.raises(RuntimeError, match="SARVAM_API_KEY environment variable is required"):
        _ = provider.api_key


@pytest.mark.anyio
async def test_google_cloud_provider_synthesis(tmp_path):
    provider = GoogleCloudTTSProvider(voice="hi-IN-Neural2-B")
    mock_client = MagicMock()
    dummy_wav = b"RIFF" + b"\x00" * 36 + b"data" + b"\x00" * 50
    mock_resp = MagicMock()
    mock_resp.audio_content = dummy_wav
    mock_client.synthesize_speech.return_value = mock_resp

    provider._tts_client = mock_client
    seg = SpeechSegment(
        source_text="मन जीते जग जीत",
        normalized_text="मन जीते जग जीत",
        pronunciation_text="मन जीते जग जीत",
        segment_type="prose",
        rate="+5%"
    )
    out_wav = str(tmp_path / "gcloud_out.wav")
    res = await provider.synthesize(seg, out_wav)
    assert res == out_wav
    assert Path(out_wav).is_file()
    assert Path(out_wav).read_bytes() == dummy_wav



