import pytest  # type: ignore

from email_assistant_app.application.dependencies import _email_agent_llm
from email_assistant_app.errors import ConfigurationError
from email_assistant_app.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_llm_factory_uses_groq_by_default(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    get_settings.cache_clear()

    llm = _email_agent_llm(get_settings())

    assert llm.provider == "groq"
    assert llm.model == "openai/gpt-oss-120b"


def test_settings_report_groq_as_only_llm_provider(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.llm_provider == "groq"
    assert settings.llm_model == "openai/gpt-oss-120b"
    assert settings.llm_configured is True


def test_llm_factory_requires_active_provider_credentials(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError) as exc_info:
        _email_agent_llm(get_settings())

    assert exc_info.value.message == "LLM provider is not configured."
    assert exc_info.value.details == {"provider": "groq", "required_env": ["GROQ_API_KEY"]}
