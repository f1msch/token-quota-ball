import json

from token_quota_ball import config


def test_temporary_overlay_does_not_write_disk(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("TOKEN_QUOTA_BALL_HOME", str(home))
    # Reload path constants bound at import time via direct override.
    monkeypatch.setattr(config, "CONFIG_DIR", home / "config")
    monkeypatch.setattr(config, "CONFIG_PATH", home / "config" / "providers.json")
    config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.CONFIG_PATH.write_text("{}\n", encoding="utf-8")

    with config.temporary_config_overlay(
        {"deepseek": {"api_key": "sk-test-not-persisted", "reference_balance": 1}}
    ):
        raw = config.load_raw()
        assert raw["deepseek"]["api_key"] == "sk-test-not-persisted"

    disk = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
    assert disk == {}
