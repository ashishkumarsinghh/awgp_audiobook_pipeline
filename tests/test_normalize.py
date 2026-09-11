import pytest
from src.normalize.text_cleaner import apply_shantikunj_rules, fix_ocr_punctuation

def test_fix_ocr_punctuation():
    # Test converting english pipes to hindi dandas
    assert fix_ocr_punctuation('गायत्री मंत्र|') == 'गायत्री मंत्र।'
    assert fix_ocr_punctuation('ॐ भूर्भुवः स्वः||') == 'ॐ भूर्भुवः स्वः॥'

def test_apply_shantikunj_rules_anusvara():
    # Test standardization of half-letters to anusvara
    assert apply_shantikunj_rules('अङ्क') == 'अंक'
    assert apply_shantikunj_rules('चञ्चल') == 'चंचल'
    assert apply_shantikunj_rules('खण्ड') == 'खंड'
    assert apply_shantikunj_rules('शान्त') == 'शांत'
    assert apply_shantikunj_rules('सम्पत्ति') == 'संपत्ति'

def test_apply_shantikunj_rules_matra_spacing():
    # Test fixing spaces before matras (common OCR artifact)
    assert apply_shantikunj_rules('ह ोता') == 'होता'
    assert apply_shantikunj_rules('म ेरी') == 'मेरी'