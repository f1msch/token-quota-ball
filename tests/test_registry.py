from token_quota_ball.config import PROVIDER_IDS
from token_quota_ball.providers.registry import PROVIDERS, normalize_provider_id


def test_providers_cover_all_ids():
    assert set(PROVIDERS) == set(PROVIDER_IDS)


def test_normalize_provider_id():
    assert normalize_provider_id("CURSOR") == "cursor"
    assert normalize_provider_id("nope") == "cursor"
    assert normalize_provider_id(None) == "cursor"
