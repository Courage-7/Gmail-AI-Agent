import pytest

from email_assistant_app.application.dependencies import _gmail_docker_config
from email_assistant_app.errors import ConfigurationError
from email_assistant_app.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_gmail_docker_config_uses_settings_loaded_env(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_ADDRESS", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    monkeypatch.setenv("IMAP_HOST", "imap.gmail.com")
    monkeypatch.setenv("IMAP_PORT", "993")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("GMAIL_MCP_IMAGE", "yashtekwani/gmail-mcp")
    monkeypatch.setenv("TEST_SEND_TO", "receiver@example.com")

    config = _gmail_docker_config(get_settings())

    assert config.email_address == "sender@example.com"
    assert config.email_password == "app-password"
    assert config.test_send_to == "receiver@example.com"
    assert config.server_env()["EMAIL_ADDRESS"] == "sender@example.com"


def test_gmail_docker_config_reports_missing_settings(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_ADDRESS", "")
    monkeypatch.setenv("EMAIL_PASSWORD", "")
    monkeypatch.setenv("IMAP_HOST", "imap.gmail.com")
    monkeypatch.setenv("IMAP_PORT", "993")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("GMAIL_MCP_IMAGE", "yashtekwani/gmail-mcp")
    monkeypatch.setenv("TEST_SEND_TO", "")

    with pytest.raises(ConfigurationError) as exc_info:
        _gmail_docker_config(get_settings())

    assert exc_info.value.message == "Docker Gmail MCP is not configured."
    assert exc_info.value.details == {"required_env": ["EMAIL_ADDRESS", "EMAIL_PASSWORD", "TEST_SEND_TO"]}
