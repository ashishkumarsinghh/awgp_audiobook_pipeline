from src.qa.roman_feedback import resolve_phrase


def test_resolves_romanized_hindi_phrase_to_sentence():
    result = resolve_phrase("gali gali", "प्रमुख राजनगरों में पहुँच गई। वह गली-गली घूमती रही।")

    assert "गली-गली" in result["sentence"]
    assert result["score"] >= 0.72


def test_resolves_homophonic_romanized_phrase_without_changing_source():
    result = resolve_phrase("swayam he", "उन्होंने स्वयं ही यह कार्य किया।")

    assert "स्वयं ही" in result["sentence"]
    assert result["sentence"].rstrip("।") == "उन्होंने स्वयं ही यह कार्य किया"


def test_resolves_printed_zero_abbreviations_as_one_phrase():
    result = resolve_phrase("b shunya a shunya", "उन्होंने बी० ए० किया, फिर एम० ए० किया।")

    assert result["matched_window"] == "बी० ए०"
    assert result["score"] == 1.0
