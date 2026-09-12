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
