"""Mirror the TypeScript orb geometry helpers for regression safety."""


def clamp(x, y, screen, ball, dock_sliver, allow_dock):
    sliver = dock_sliver if allow_dock else ball
    min_x = screen["x"] - (ball - sliver)
    max_x = screen["x"] + screen["width"] - sliver
    min_y = screen["y"] - (ball - sliver)
    max_y = screen["y"] + screen["height"] - sliver
    return {
        "x": max(min_x, min(x, max_x)),
        "y": max(min_y, min(y, max_y)),
    }


def test_clamp_keeps_dock_sliver():
    screen = {"x": 0, "y": 0, "width": 1920, "height": 1080}
    pos = clamp(-200, 100, screen, ball=108, dock_sliver=26, allow_dock=True)
    assert pos["x"] == 0 - (108 - 26)
