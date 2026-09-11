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
