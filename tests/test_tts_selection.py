from src.synthesis.providers import VOICE_CATALOG, GoogleCloudTTSProvider, AzureSpeechProvider
from src.pipeline_v3 import ProjectManager


def test_curated_catalog_contains_hindi_sanskrit_choices():
    providers = {item["provider"] for item in VOICE_CATALOG}
    assert {"edge", "google", "azure"} <= providers
    assert all(item["sanskrit"] for item in VOICE_CATALOG)


def test_project_manager_selects_new_adapters(tmp_path):
    assert isinstance(ProjectManager(str(tmp_path), "google").tts, GoogleCloudTTSProvider)
    assert isinstance(ProjectManager(str(tmp_path), "azure").tts, AzureSpeechProvider)
