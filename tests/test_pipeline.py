from unittest.mock import patch
import pytest
from src.core.types import SpeechSegment
from src.synthesis.assembler import AudioAssembler
import os
import wave
import struct

def create_fake_wav(path, duration_ms=100):
    with wave.open(path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        num_frames = int((duration_ms / 1000) * 24000)
        wav.writeframes(b''.join(struct.pack('<h', 2000 if i % 48 < 24 else -2000) for i in range(num_frames)))

def test_speech_segment():
    seg = SpeechSegment(
        source_text="Hello",
        normalized_text="hello",
        pronunciation_text="h e l o",
        pause_after_ms=500
    )
    assert seg.source_text == "Hello"
    assert seg.pause_after_ms == 500

def test_audio_assembler_lossless(tmp_path):
    output = str(tmp_path / "master.mp3")
    assembler = AudioAssembler(output)
    
    # Fake a few WAV chunks
    w1 = str(tmp_path / "chunk1.wav")
    w2 = str(tmp_path / "chunk2.wav")
    create_fake_wav(w1, 100)
    create_fake_wav(w2, 100)
    
    seg1 = SpeechSegment(source_text="1", normalized_text="1", pronunciation_text="1", pause_after_ms=10)
    seg1.audio_file = w1
    seg2 = SpeechSegment(source_text="2", normalized_text="2", pronunciation_text="2", pause_after_ms=0)
    seg2.audio_file = w2
    
    def capture_master(input_path, output_path, **kwargs):
        with wave.open(input_path, "rb") as combined:
            assert combined.getnframes() == int(0.21 * 24000)
        with open(output_path, "wb") as stream:
            stream.write(b"mastered")
    with patch("src.synthesis.assembler.AudioEnhancer.apply_studio_mastering", side_effect=capture_master):
        assembler.assemble([seg1, seg2])
    assert open(output, "rb").read() == b"mastered"


def test_audio_enhancer_eq_profiles(tmp_path):
    from src.synthesis.audio.enhancer import AudioEnhancer
    dummy_in = str(tmp_path / "in.wav")
    dummy_out = str(tmp_path / "out.mp3")
    create_fake_wav(dummy_in, 100)

    captured_filters = []
    def mock_run(cmd):
        idx = cmd.index("-filter_complex")
        captured_filters.append(cmd[idx + 1])

    with patch.object(AudioEnhancer, "_run", side_effect=mock_run):
        # Default smooth EQ: uses firequalizer with the user's calibrated curve
        AudioEnhancer.apply_studio_mastering(dummy_in, dummy_out, eq_profile="smooth")
        assert "firequalizer" in captured_filters[-1]
        assert "entry(62, 11)" in captured_filters[-1]
        assert "entry(16000, -12)" in captured_filters[-1]
        assert "zero_phase=on" in captured_filters[-1]

        # Balanced EQ: uses anequalizer
        AudioEnhancer.apply_studio_mastering(dummy_in, dummy_out, eq_profile="balanced")
        assert "anequalizer" in captured_filters[-1]

        # Flat EQ: bypasses multi-band coloration
        AudioEnhancer.apply_studio_mastering(dummy_in, dummy_out, eq_profile="flat")
        assert "firequalizer" not in captured_filters[-1]
        assert "anequalizer" not in captured_filters[-1]


def test_audio_assembler_passes_eq_profile(tmp_path):
    output = str(tmp_path / "master.mp3")
    assembler = AudioAssembler(output, eq_profile="smooth")
    w1 = str(tmp_path / "chunk.wav")
    create_fake_wav(w1, 100)
    seg = SpeechSegment(source_text="1", normalized_text="1", pronunciation_text="1")
    seg.audio_file = w1

    captured_kwargs = {}
    def mock_master(src, dest, **kwargs):
        captured_kwargs.update(kwargs)
        with open(dest, "wb") as f:
            f.write(b"mastered")

    with patch("src.synthesis.assembler.AudioEnhancer.apply_studio_mastering", side_effect=mock_master):
        assembler.assemble([seg], eq_profile="balanced")
        assert captured_kwargs.get("eq_profile") == "balanced"

