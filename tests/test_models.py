from token_quota_ball.providers.models import format_number, meter_color, used_percent


def test_used_percent_basic():
    assert used_percent(25, 100) == 25.0
    assert used_percent(None, 100, remaining=40) == 60.0
    assert used_percent(10, 0) is None
    assert used_percent(150, 100) == 100.0


def test_format_number():
    assert format_number(12.0) == "12"
    assert format_number(12.34, "元").endswith("元")


def test_meter_color_bands():
    assert meter_color(None) == "#5a6a7a"
    assert meter_color(50) == "#3ee89a"
    assert meter_color(85) == "#ffc24a"
    assert meter_color(99) == "#ff6b73"
