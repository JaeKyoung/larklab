from larklab import config as config_module
from larklab.config import Config, load_config


def test_the_slack_token_never_shows_up_in_repr_or_tracebacks():
    secret = "xoxb-super-secret"
    settings = Config("creds.json", "token.json", secret, "library.db")

    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert settings.slack_bot_token == secret  # still usable


def test_settings_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "load_dotenv", lambda path: None)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-from-env")
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))
    monkeypatch.delenv("GMAIL_CREDENTIALS_PATH", raising=False)

    settings = load_config()

    assert settings.slack_bot_token == "xoxb-from-env"
    assert settings.token_path == str(tmp_path / "token.json")  # absolute paths stay
    assert settings.credentials_path.endswith("credentials/credentials.json")
    assert settings.db_path.endswith("data/larklab.db")
