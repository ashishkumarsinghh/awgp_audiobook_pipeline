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
        wav.writeframes(struct.pack('h', 0) * num_frames)

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
    
    with patch('os.system') as mock_system:
        mock_system.return_value = 0
        assembler.assemble([seg1, seg2])
        
        # Verify the concat file was written correctly
        concat_file = os.path.join(str(tmp_path), "concat_list.txt")
        assert os.path.exists(concat_file)
        with open(concat_file, "r") as f:
            content = f.read()
            assert w1 in content
            assert w2 in content
