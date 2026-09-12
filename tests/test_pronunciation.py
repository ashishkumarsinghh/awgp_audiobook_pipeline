import pytest
from src.normalize.pronunciation import PronunciationDictionary

@pytest.fixture
def pd():
    return PronunciationDictionary()

def test_visarga_echo_i(pd):
    assert pd.apply("शान्तिः") == "शान्तिहि"
    assert pd.apply("हरिः।") == "हरिहि।"
    assert pd.apply("मतिः") == "मतिहि"

def test_visarga_echo_u(pd):
    assert pd.apply("विष्णुः") == "विष्णुहु"
    assert pd.apply("गुरुः") == "गुरुहु"
    assert pd.apply("भानुः") == "भानुहु"

def test_visarga_echo_a(pd):
    assert pd.apply("नमः") == "नमह"
    assert pd.apply("रामः") == "रामह"
    assert pd.apply("बुधैः") == "बुधैह"
    assert pd.apply("आगमैः") == "आगमैह"

def test_visarga_mid_word(pd):
    assert pd.apply("दुःख") == "दुःख" # Mid-word shouldn't be altered

def test_terminal_virama(pd):
    assert pd.apply("भगवान्", context="shloka") == "भगवान"
    assert pd.apply("पश्चात्", context="shloka") == "पश्चात"
    assert pd.apply("कुर्यात्", context="shloka") == "कुर्यात"
    assert pd.apply("अर्थात्", context="shloka") == "अर्थात"
    assert pd.apply("महान्", context="shloka") == "महान"
    assert pd.apply("यस्मात्", context="shloka") == "यस्मात"

def test_h_conjunct_metathesis(pd):
    assert pd.apply("ब्रह्म", context="shloka") == "ब्रम्ह"
    assert pd.apply("चिह्न", context="shloka") == "चिन्ह"
    assert pd.apply("प्रह्लाद", context="shloka") == "प्रल्हाद"

def test_vocalic_r(pd):
    assert pd.apply("ऋषि", context="shloka") == "रिषि"
    assert pd.apply("प्रकृति", context="shloka") == "प्रक्रिति"
    assert pd.apply("सृष्टि", context="shloka") == "स्रिष्टि"

def test_bija_mantras(pd):
    assert pd.apply("ॐ", context="shloka") == "ओम्"
    assert pd.apply("ह्रीं", context="shloka") == "ह्रीम"
    assert pd.apply("स्वाहा", context="shloka") == "स्वाहा"
    assert pd.apply("क्लीं", context="shloka") == "क्लीम"

def test_varga_nasals(pd):
    assert pd.apply("पञ्च", context="shloka") == "पंच"
    assert pd.apply("सङ्घ", context="shloka") == "संघ"
    assert pd.apply("कुण्डलिनी", context="shloka") == "कुंडलिनी"

def test_sandhi_splitting(pd):
    assert pd.apply("ॐ भूर्भुवः स्वः", context="shloka") == "ओम् भूर्भुवह स्वाह"
    assert pd.apply("धियो यो नः प्रचोदयात्", context="shloka") == "धियो यो नह प्रचोदयात"
    assert pd.apply("त्र्यम्बकं यजामहे", context="shloka") == "त्र्यम्बकम यजामहे"
    assert pd.apply("मृत्योर्मुक्षीय मामृतात्", context="shloka") == "म्रित्योर्मुक्षीय माम्रितात्"

def test_hindi_schwa_deletion(pd):
    # Test that the general hindi prose context appends halant to consonant clusters
    # And terminal virama drops the virama first
    # So 'धर्म' -> 'धर्म्'
    assert pd.apply("धर्म", context="prose") == "धर्म्"
    assert pd.apply("कर्म", context="prose") == "कर्म्"
    assert pd.apply("महत्त्व", context="prose") == "महत्त्व्"
    
def test_unicode_cleaning(pd):
    assert pd.apply("अ\u200Cत\u200Dः") == "अतह" # ZWNJ, ZWJ stripped
    
def test_public_api(pd):
    pd.add_word("टेस्ट", "परीक्षण")
    assert pd.apply("टेस्ट", context="shloka") == "परीक्षण"
    pd.remove_word("टेस्ट")
    assert pd.apply("टेस्ट", context="shloka") == "टेस्ट"
    
    pd.add_phrase("लम्बा वाक्य", "छोटा")
    assert pd.apply("लम्बा वाक्य", context="shloka") == "छोटा"
    pd.remove_phrase("लम्बा वाक्य")
    assert pd.apply("लम्बा वाक्य", context="shloka") == "लम्बा वाक्य"
    
    explanation = pd.explain("ॐ")
    assert explanation["original"] == "ॐ"
    assert explanation["transformed"] == "ओम्"
    assert explanation["modified"] == True
