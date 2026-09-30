from app.core.config import MerchantCatalog, RuntimeSettings
from app.demo_data.repository import DemoDataRepository


def test_star_select_configuration_and_required_fixtures_are_valid():
    catalog = MerchantCatalog()
    merchant = catalog.get("star_select")
    counts = DemoDataRepository(catalog).validate_merchant_fixtures("star_select")

    assert merchant.config.display_name.startswith("星选生活")
    assert merchant.config.enabled_skills == [
        "knowledge_qa",
        "order_lookup",
        "refund_eligibility",
        "human_handoff",
    ]
    assert counts == {
        "products": 10,
        "customers": 3,
        "orders": 12,
        "knowledge_documents": 5,
        "failure_scenarios": 5,
    }


def test_runtime_settings_default_to_mock(monkeypatch):
    for key in ("LLM_MODE", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_TIMEOUT", "LLM_MAX_RETRIES"):
        monkeypatch.delenv(key, raising=False)

    settings = RuntimeSettings.from_environment()

    assert settings.llm_mode == "mock"
    assert settings.llm_timeout_seconds == 30
    assert settings.llm_max_retries == 2


def test_runtime_settings_accept_openai_compatible_environment(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://model.example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    monkeypatch.setenv("LLM_MODEL", "demo-model")
    monkeypatch.setenv("LLM_TIMEOUT", "12.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")

    settings = RuntimeSettings.from_environment()

    assert settings.llm_mode == "openai_compatible"
    assert settings.llm_base_url == "https://model.example.test/v1"
    assert settings.llm_model == "demo-model"
    assert settings.llm_timeout_seconds == 12.5
    assert settings.llm_max_retries == 1


def test_api_key_mode_requires_a_nonempty_principal_configuration(monkeypatch):
    monkeypatch.setenv("FRAMEWORK_AUTH_MODE", "api_key")
    monkeypatch.delenv("FRAMEWORK_API_KEYS_JSON", raising=False)

    try:
        RuntimeSettings.from_environment()
    except RuntimeError as exc:
        assert "FRAMEWORK_API_KEYS_JSON" in str(exc)
    else:
        raise AssertionError("api_key mode without a principal configuration must fail")
