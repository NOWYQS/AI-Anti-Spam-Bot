from config import Config


def test_sensitive_config_uses_environment_overrides(monkeypatch, tmp_path):
    (tmp_path / "config.yml").write_text(
        """telegram:\n  token: file-token\n  owners: [\"1\"]\nopenai:\n  api_key: file-key\n  base_url: https://file.example/v1\n  model: file-model\n""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_TOKEN", "env-token")
    monkeypatch.setenv("TELEGRAM_OWNERS", "10,20")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    Config._config = None

    try:
        assert Config.get("telegram.token") == "env-token"
        assert Config.get("telegram.owners") == ["10", "20"]
        assert Config.get("openai.api_key") == "env-key"
        assert Config.get("openai.base_url") == "https://env.example/v1"
        assert Config.get("openai.model") == "env-model"
    finally:
        Config._config = None
