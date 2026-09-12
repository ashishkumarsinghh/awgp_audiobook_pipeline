import asyncio
from pathlib import Path
import pytest
from src.synthesis.runner import synthesize_segments, load_manifest
from tests.test_pipeline import create_fake_wav


class Provider:
    voice = "test-voice"
    calls = 0

    async def synthesize(self, segment, output):
        self.calls += 1
        create_fake_wav(output)


def test_cache_changes_and_resume(tmp_path):
    provider = Provider()
    data = [{"id": "c1", "source_text": "Narration."}]
    def run():
        asyncio.run(synthesize_segments(data, tmp_path, provider, "fake", attempts=1))
    run()
    run()
    assert provider.calls == 1
    for key, value in [("source_text", "Changed narration."), ("rate", "-5%"), ("pitch", "+2Hz")]:
        data[0][key] = value
        run()
    provider.voice = "different-voice"
    run()
    assert provider.calls == 5
    (tmp_path / "c1.wav").write_bytes(b"broken")
    run()
    assert provider.calls == 6


@pytest.mark.parametrize("failure", ["exception", "missing", "silence"])
def test_failed_provider_cannot_complete(tmp_path, failure):
    class Broken(Provider):
        async def synthesize(self, segment, output):
            if failure == "exception":
                raise RuntimeError("provider offline")
            if failure == "silence":
                import wave
                with wave.open(output, "wb") as wav:
                    wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                    wav.writeframes(bytes(4800))
    with pytest.raises(RuntimeError, match="Narration incomplete.*c1"):
        asyncio.run(synthesize_segments([{"id": "c1", "source_text": "Text"}], tmp_path, Broken(), "fake", attempts=1))
    assert load_manifest(tmp_path)["chunks"]["c1"]["status"] == "failed"
    assert not (tmp_path / "c1.wav").exists()
