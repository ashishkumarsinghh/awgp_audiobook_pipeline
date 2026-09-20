import pytest
from src.normalize.text_cleaner import (
    apply_shantikunj_rules,
    fix_ocr_punctuation,
    clean_book_headers_and_metadata,
    is_metadata_block,
)

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

def test_clean_writer_and_publisher_headers():
    raw_ocr = (
        "<heading>मन साधे जीवन सधै</heading>\n"
        "<prose>—श्रीराम शर्मा आचार्य</prose>\n"
        "<heading>मन साधे जीवन सधै</heading>\n"
        "<subheading>लेखक</subheading>\n"
        "<prose>पं० श्रीराम शर्मा आचार्य</prose>\n"
        "<subheading>प्रकाशक</subheading>\n"
        "<prose>युग निर्माण योजना विस्तार ट्रस्ट</prose>\n"
        "<prose>गायत्री तपोभूमि, मथुरा-२८१००३</prose>\n"
        "<heading>मन के हारे हार है, मन के जीते जीत</heading>\n"
        "<prose>कहा जाता है—“मन के हारे हार है, मन के जीते जीत।”</prose>"
    )
    cleaned = clean_book_headers_and_metadata(raw_ocr, book_title="मन साधे जीवन सधै")
    # Writer and publisher metadata must be stripped
    assert "लेखक" not in cleaned
    assert "प्रकाशक" not in cleaned
    assert "युग निर्माण योजना" not in cleaned
    assert "गायत्री तपोभूमि" not in cleaned
    assert "पं० श्रीराम शर्मा" not in cleaned
    assert "—श्रीराम शर्मा" not in cleaned
    # Substantive chapter heading and prose must be preserved
    assert "<heading>मन के हारे हार है, मन के जीते जीत</heading>" in cleaned
    assert "कहा जाता है" in cleaned

def test_clean_running_headers_and_page_numbers():
    raw_ocr = (
        "<prose>पेरिस का पतन हो चुका था, किंतु मन संधे जीवन सधे ) ( ५</prose>\n"
        "<prose>मन साधे जीवन सधे ) ( १५</pro5e>\n"
        "<prose>शारीरिक दृष्टि से सबल बन जाएगा। निश्चय ही मन साधे जीवन सधै ।</prose>\n"
        "<prose>ही हम उसी ओर बढ़ेंगे।</prose>"
    )
    cleaned = clean_book_headers_and_metadata(raw_ocr, book_title="मन साधे जीवन सधै")
    assert ") ( ५" not in cleaned
    assert ") ( १५" not in cleaned
    assert "<prose>मन साधे जीवन सधे</prose>" not in cleaned
    assert "पेरिस का पतन हो चुका था, किंतु" in cleaned
    assert "ही हम उसी ओर बढ़ेंगे।" in cleaned

def test_is_metadata_block():
    assert is_metadata_block("subheading", "लेखक") is True
    assert is_metadata_block("subheading", "प्रकाशक") is True
    assert is_metadata_block("prose", "पं० श्रीराम शर्मा आचार्य") is True
    assert is_metadata_block("prose", "( ५ )") is True
    assert is_metadata_block("prose", "मनुष्य की वास्तविक शक्ति मनोबल ही है।") is False


def test_cross_page_sentence_stitching_heals_broken_sentences():
    # Test that sentences severed across page breaks (without terminal punctuation) are stitched together
    raw_ocr = (
        "<prose>शस्त्र विहीन हो गई। नौबत यहाँ</prose>\n\n"
        "<prose>तक आ पहुँचा कि शत्रु को भी भ्रम में डालने के लिए खजूर के पेड़ लगाए गए।</prose>"
    )
    cleaned = clean_book_headers_and_metadata(raw_ocr)
    assert "नौबत यहाँ तक आ पहुँचा" in cleaned
    assert "</prose>\n\n<prose>" not in cleaned

    # Test that segmenter treats it as an unbroken sentence
    from src.normalize.segmenter import SemanticSegmenter
    segments = SemanticSegmenter().segment_text(raw_ocr)
    assert len(segments) == 1
    assert "नौबत यहाँ तक आ पहुँचा कि" in segments[0].source_text


def test_cross_page_deduplicates_overlapping_catchwords():
    # Test OCR page overlap where a word is repeated across the page break
    raw_ocr = (
        "<prose>हमारे विचारों का प्रवाह जिस ओर होगा, निश्चय ही</prose>\n\n"
        "<prose>ही हम उसी ओर बढ़ेंगे।</prose>"
    )
    cleaned = clean_book_headers_and_metadata(raw_ocr)
    assert "निश्चय ही हम उसी ओर बढ़ेंगे।" in cleaned
    assert "ही ही" not in cleaned


def test_abbreviations_do_not_cause_false_sentence_splits():
    # Test that Hindi and common abbreviations do not trigger sentence boundaries
    from src.normalize.segmenter import SemanticSegmenter
    seg = SemanticSegmenter()
    text = "<prose>युगऋषि पं. श्रीराम शर्मा आचार्य का संदेश अत्यंत पावन है। डॉ. कलाम एक महान वैज्ञानिक थे।</prose>"
    segments = seg.segment_text(text)
    # Should not split on 'पं.' or 'डॉ.'
    assert len(segments) == 1
    assert "पं. श्रीराम शर्मा" in segments[0].source_text
    assert "डॉ. कलाम" in segments[0].source_text


def test_intra_sentence_piece_splits_have_zero_pause():
    # Test that if a sentence must be split due to max_chars_per_chunk, intra-sentence pieces get 0ms pause
    from src.normalize.segmenter import SemanticSegmenter
    long_sentence = "यह एक बहुत लम्बा वाक्य है " * 15 + "जो बिना किसी विराम के चलता जा रहा है।"
    seg = SemanticSegmenter(max_chars_per_chunk=80)
    segments = seg.segment_text(f"<prose>{long_sentence}</prose>")
    assert len(segments) > 1
    # All intermediate pieces of this single sentence must have 0ms pause
    for s in segments[:-1]:
        assert s.pause_after_ms == 0, f"Expected 0ms pause mid-sentence, got {s.pause_after_ms}ms"
    # Final piece ending with danda gets normal pause
    assert segments[-1].pause_after_ms > 0