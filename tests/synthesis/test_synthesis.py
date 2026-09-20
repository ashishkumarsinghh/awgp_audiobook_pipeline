import pytest
from src.synthesis.parser.xml_parser import XMLParser
from src.synthesis.models.document import SemanticTag
from src.synthesis.speech.planner import SpeechPlanner
from src.synthesis.models.config import SynthesisConfig
from src.synthesis.ssml.providers.edge import EdgeTTSRenderer
from src.synthesis.ssml.validator import SSMLValidator

def test_xml_parser():
    xml = "<heading>सन्ध्या-वन्दन</heading>\n<prose>सन्ध्या का समय अत्यन्त पवित्र माना गया है।</prose>\n<shloka>ॐ भूर्भुवः स्वः।</shloka>"
    doc = XMLParser.parse(xml)
    assert len(doc.blocks) == 3
    assert doc.blocks[0].tag == SemanticTag.HEADING
    assert doc.blocks[1].tag == SemanticTag.PROSE
    assert doc.blocks[2].tag == SemanticTag.SHLOKA

def test_speech_planner():
    xml = "<shloka>ॐ भूर्भुवः स्वः।</shloka>"
    doc = XMLParser.parse(xml)
    planner = SpeechPlanner(SynthesisConfig())
    plan = planner.plan(doc)
    assert plan[0]['rate'] == 0.82

def test_ssml_preservation():
    xml = "<prose>सन्ध्या का समय अत्यन्त पवित्र माना गया है।</prose>"
    doc = XMLParser.parse(xml)
    planner = SpeechPlanner(SynthesisConfig())
    plan = planner.plan(doc)
    
    renderer = EdgeTTSRenderer()
    ssml = renderer.render(plan)
    
    # original text in plan
    orig_text = plan[0]['text']
    assert SSMLValidator.validate_preservation(orig_text, ssml) == True

def test_segmenter_xml_tag_stripping_and_chunking():
    from src.normalize.segmenter import SemanticSegmenter
    
    raw_xml = (
        "<heading>गायत्री महाविज्ञान</heading>\n"
        "<shloka>ॐ भूर्भुवः स्वः। तत्सवितुर्वरेण्यं भर्गो देवस्य धीमहि। धियो यो नः प्रचोदयात्॥</shloka>\n"
        "<prose>\n"
        "गायत्री साधना से आत्मबल बढ़ता है। यह मन को एकाग्र बनाती है। जीवन में दिव्य प्रकाश का संचार होता है। "
        "सद्बुद्धि की प्राप्ति होती है। समस्त विकारों का शमन होता है। इस महामंत्र की शक्ति अपार है। "
        "ऋषियों ने इसे जीवन-शोधक माना है। निरंतर जप से अंतःकरण पवित्र होता है। साधक को शांति का अनुभव होता है। "
        "परमात्मा की कृपा सहज ही सुलभ हो जाती है। यह सनातन मार्ग है। हम सभी को इसका अभ्यास करना चाहिए।\n"
        "</prose>"
    )
    
    segmenter = SemanticSegmenter(sentences_per_chunk=5)
    segments = segmenter.segment_text(raw_xml)
    
    # Check that tags are completely absent
    for s in segments:
        assert "<prose>" not in s.source_text
        assert "</prose>" not in s.source_text
        assert "<heading>" not in s.source_text
        assert "</heading>" not in s.source_text
        assert "<shloka>" not in s.source_text
        assert "</shloka>" not in s.source_text

    # Segment 0: Heading
    assert segments[0].segment_type == "heading"
    assert segments[0].source_text == "गायत्री महाविज्ञान"
    assert segments[0].pause_after_ms == 1000

    # Segment 1: Shloka
    assert segments[1].segment_type == "shloka"
    assert "ॐ भूर्भुवः स्वः" in segments[1].source_text
    assert segments[1].pause_after_ms == 800

    # Segments 2 & 3: Prose chunks (12 sentences -> 2 chunks of 5 and 5+2=7 or 5+5+2)
    prose_segments = [s for s in segments if s.segment_type == "prose"]
    assert len(prose_segments) >= 2
    # Ensure prose chunks contain multiple sentences rather than tiny 1-clause fragments
    for ps in prose_segments:
        assert ps.source_text.count("।") >= 2 or len(ps.source_text) > 80

def test_edge_tts_provider_tag_stripping(tmp_path):
    import asyncio
    from src.synthesis.providers import EdgeTTSProvider
    from src.core.types import SpeechSegment
    from unittest.mock import patch, AsyncMock

    provider = EdgeTTSProvider()
    seg = SpeechSegment(
        source_text="<prose>गायत्री साधना</prose>",
        normalized_text="<prose>गायत्री साधना</prose>",
        pronunciation_text="<prose>गायत्री साधना</prose>",
        segment_type="prose"
    )
    output = str(tmp_path / "out.mp3")

    async def _run():
        from pathlib import Path
        with patch("edge_tts.Communicate") as mock_comm:
            mock_instance = AsyncMock()
            mock_instance.save.side_effect = lambda path: Path(path).write_bytes(b"mock encoded speech")
            mock_comm.return_value = mock_instance
            await provider.synthesize(seg, output)
            assert mock_comm.call_args.kwargs["text"] == "गायत्री साधना"
            assert Path(output).read_bytes() == b"mock encoded speech"

    asyncio.run(_run())

def test_google_cloud_tts_provider_none_rate(tmp_path):
    import asyncio
    import sys
    import types
    from unittest.mock import MagicMock
    from src.synthesis.providers import GoogleCloudTTSProvider
    from src.core.types import SpeechSegment

    mock_tts = MagicMock()
    mock_response = MagicMock()
    mock_response.audio_content = b"fake-wav-data"
    mock_client = MagicMock()
    mock_client.synthesize_speech.return_value = mock_response
    mock_tts.TextToSpeechClient.return_value = mock_client

    mock_cloud = types.ModuleType("google.cloud")
    mock_cloud.texttospeech = mock_tts

    orig_cloud = sys.modules.get("google.cloud")
    orig_tts = sys.modules.get("google.cloud.texttospeech")
    sys.modules["google.cloud"] = mock_cloud
    sys.modules["google.cloud.texttospeech"] = mock_tts
    try:
        provider = GoogleCloudTTSProvider()
        provider._tts_client = mock_client
        seg = SpeechSegment(
            source_text="गायत्री साधना",
            normalized_text="गायत्री साधना",
            pronunciation_text="गायत्री साधना",
            segment_type="prose",
            rate=None,
            pitch=None,
        )
        out_file = str(tmp_path / "gtts_out.wav")
        result = asyncio.run(provider.synthesize(seg, out_file))

        assert result == out_file
        assert open(out_file, "rb").read() == b"fake-wav-data"
        mock_client.synthesize_speech.assert_called_once()
        mock_tts.AudioConfig.assert_called_once()
        assert mock_tts.AudioConfig.call_args.kwargs["speaking_rate"] == 1.0
    finally:
        if orig_cloud is not None:
            sys.modules["google.cloud"] = orig_cloud
        else:
            sys.modules.pop("google.cloud", None)
        if orig_tts is not None:
            sys.modules["google.cloud.texttospeech"] = orig_tts
        else:
            sys.modules.pop("google.cloud.texttospeech", None)


def test_prosodic_marking_breath_commas():
    from src.synthesis.prosody import apply_prosodic_marking
    raw_sentence = "संसार के सारे कार्य शरीर द्वारा ही संपादित होते हैं किंतु उसका संचालक मन ही हुआ करता है।"
    marked = apply_prosodic_marking(raw_sentence, "prose")
    # Comma should be injected before 'किंतु' for natural breath pause
    assert ", किंतु" in marked

    question_sentence = "क्या आप जानते हैं कि आपका मन कितना शक्तिशाली है"
    marked_q = apply_prosodic_marking(question_sentence, "question")
    assert marked_q.endswith("?")

    shloka = "ॐ भूर्भुवः स्वः"
    marked_s = apply_prosodic_marking(shloka, "shloka")
    assert marked_s.endswith("॥")


def test_prosody_planner_parameters():
    from src.synthesis.prosody import ProsodyPlanner
    from src.core.types import SpeechSegment, NarrationProfile

    planner = ProsodyPlanner(NarrationProfile())
    segments = [
        SpeechSegment(source_text="मन साधे जीवन सधै", normalized_text="मन साधे जीवन सधै", pronunciation_text="मन साधे जीवन सधै", segment_type="heading"),
        SpeechSegment(source_text="क्या मन ही सब कुछ है?", normalized_text="क्या मन ही सब कुछ है?", pronunciation_text="क्या मन ही सब कुछ है?", segment_type="question"),
        SpeechSegment(source_text="ॐ भूर्भुवः स्वः॥", normalized_text="ॐ भूर्भुवः स्वः॥", pronunciation_text="ॐ भूर्भुवः स्वः॥", segment_type="shloka"),
        SpeechSegment(source_text="मनुष्य का वास्तविक बल मनोबल ही है।", normalized_text="मनुष्य का वास्तविक बल मनोबल ही है।", pronunciation_text="मनुष्य का वास्तविक बल मनोबल ही है।", segment_type="prose"),
    ]
    planned = planner.apply_prosody(segments)

    # Heading: deliberate pace, lower pitch, long pauses
    assert planned[0].rate == "-11%"
    assert planned[0].pitch == "-2Hz"
    assert planned[0].pause_before_ms >= 700
    assert planned[0].pause_after_ms >= 1000

    # Question: rising pitch
    assert planned[1].pitch == "+3Hz"
    assert planned[1].pause_after_ms >= 500

    # Shloka: reverent slower rate
    assert planned[2].rate == "-15%"
    assert planned[2].pitch == "-2Hz"
    assert planned[2].pause_after_ms >= 900


def test_edge_tts_provider_ssml_break_conversion(tmp_path):
    import asyncio
    from src.synthesis.providers import EdgeTTSProvider
    from src.core.types import SpeechSegment
    from unittest.mock import patch, AsyncMock
    from pathlib import Path

    provider = EdgeTTSProvider()
    seg = SpeechSegment(
        source_text="पहला <break time='500ms'/> दूसरा",
        normalized_text="पहला <break time='500ms'/> दूसरा",
        pronunciation_text="पहला <break time='500ms'/> दूसरा",
        segment_type="prose"
    )
    output = str(tmp_path / "out_break.mp3")

    with patch("edge_tts.Communicate") as mock_comm:
        mock_instance = AsyncMock()
        mock_instance.save.side_effect = lambda path: Path(path).write_bytes(b"mock audio")
        mock_comm.return_value = mock_instance

        asyncio.run(provider.synthesize(seg, output))

        mock_comm.assert_called_once()
        passed_text = mock_comm.call_args.kwargs["text"]
        # Break tag should have been converted to prosodic pause '—' without raw XML
        assert "<break" not in passed_text
        assert "—" in passed_text


def test_hierarchical_discourse_prosody_declination():
    from src.synthesis.prosody import ProsodyPlanner
    from src.core.types import SpeechSegment, NarrationProfile

    planner = ProsodyPlanner(NarrationProfile())
    
    # 4-sentence paragraph followed by a heading and a 1-sentence paragraph
    segments = [
        SpeechSegment("पहला वाक्य", "पहला वाक्य", "पहला वाक्य", segment_type="prose", pause_after_ms=350),
        SpeechSegment("दूसरा वाक्य", "दूसरा वाक्य", "दूसरा वाक्य", segment_type="prose", pause_after_ms=350),
        SpeechSegment("तीसरा वाक्य", "तीसरा वाक्य", "तीसरा वाक्य", segment_type="prose", pause_after_ms=350),
        SpeechSegment("चौथा वाक्य", "चौथा वाक्य", "चौथा वाक्य", segment_type="prose", pause_after_ms=600),
        SpeechSegment("नया शीर्षक", "नया शीर्षक", "नया शीर्षक", segment_type="heading", pause_after_ms=1000),
        SpeechSegment("एकल वाक्य", "एकल वाक्य", "एकल वाक्य", segment_type="prose", pause_after_ms=600),
    ]

    planned = planner.apply_prosody(segments)

    # Sentence 0: Paragraph Opener (Pitch Reset: +2Hz, Deliberate: -3% + -5% = -8%)
    assert planned[0].pitch == "+2Hz"
    assert planned[0].rate == "-8%"

    # Sentence 1: Body 1 (F0 Declination tilt: +1Hz)
    assert planned[1].pitch == "+1Hz"

    # Sentence 2: Body 2 (F0 Declination tilt: +0Hz)
    assert planned[2].pitch == "+0Hz"

    # Sentence 3: Paragraph Closer (Terminal drop: -1Hz, Cadential deceleration: -4% + -5% = -9%, pause >= 650ms)
    assert planned[3].pitch == "-1Hz"
    assert planned[3].rate == "-9%"
    assert planned[3].pause_after_ms >= 600

    # Sentence 4: Heading
    assert planned[4].segment_type == "heading"
    assert planned[4].pitch == "-2Hz"

    # Sentence 5: Standalone paragraph (Single sentence opener & closer: pitch=+1Hz, rate=-7%)
    assert planned[5].pitch == "+1Hz"
    assert planned[5].rate == "-7%"
    assert planned[5].pause_after_ms >= 600


def test_subordinate_clause_respiration_commas():
    from src.synthesis.prosody import apply_prosodic_marking

    # Verbal trigger before complementizer 'कि'
    s1 = "नौबत यहाँ तक आ पहुँचा कि एक बार प्रधानमंत्री विंसटन चर्चिल रो पड़े।"
    marked1 = apply_prosodic_marking(s1, "prose")
    assert "पहुँचा, कि" in marked1

    # Predicate trigger before 'कि'
    s2 = "बहुत बार देखा जा सकता है कि साधन-शक्ति पर्याप्त नहीं होती।"
    marked2 = apply_prosodic_marking(s2, "prose")
    assert "सकता है, कि" in marked2

    # Relative clause marker
    s3 = "मनुष्य की वह आंतरिक शक्ति जिसके कारण विजय प्राप्त होती है।"
    marked3 = apply_prosodic_marking(s3, "prose")
    assert ", जिसके कारण" in marked3





