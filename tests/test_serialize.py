from token_quota_ball.api.serialize import reset_fact, snapshot_dict
from token_quota_ball.providers.models import ProviderSnapshot, unconfigured_snapshot


def test_snapshot_dict_never_none_keys():
    payload = snapshot_dict(None, "暂无数据")
    assert payload["ok"] is False
    assert payload["display_text"] == "--"
    assert "cursor" in payload


def test_unconfigured_snapshot():
    view = unconfigured_snapshot("deepseek", "未配置 API Key")
    payload = snapshot_dict(view)
    assert payload["status"] == "unconfigured"
    assert payload["ok"] is False


def test_reset_fact_prefers_cycle_line():
    view = ProviderSnapshot(
        provider_id="cursor",
        title="Cursor",
        extras=("更新于 12:00", "周期剩余 2 天", "备注"),
    )
    assert reset_fact(view) == "周期剩余 2 天"
