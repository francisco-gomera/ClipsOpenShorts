import pytest

from live.config import (_bounded_int, DEFAULT_CLIP_MAX_SECONDS,
                         DEFAULT_CLIP_MIN_SECONDS, validate_clip_duration_range)


def test_live_clip_duration_defaults_and_environment_are_bounded(monkeypatch):
    assert (DEFAULT_CLIP_MIN_SECONDS, DEFAULT_CLIP_MAX_SECONDS) == (30, 60)
    monkeypatch.setenv("TEST_LIVE_BOUND", "1")
    assert _bounded_int("TEST_LIVE_BOUND", 30, 10, 240) == 10
    monkeypatch.setenv("TEST_LIVE_BOUND", "999")
    assert _bounded_int("TEST_LIVE_BOUND", 30, 10, 240) == 240
    monkeypatch.setenv("TEST_LIVE_BOUND", "not-a-number")
    assert _bounded_int("TEST_LIVE_BOUND", 30, 10, 240) == 30


@pytest.mark.parametrize("minimum,maximum", [(10, 30), (60, 60), (120, 240), (10, 240)])
def test_validate_session_duration_ranges(minimum, maximum):
    assert validate_clip_duration_range(minimum, maximum) == (minimum, maximum)


@pytest.mark.parametrize("minimum,maximum", [(9, 30), (30, 241), (61, 60), (30.5, 60), (True, 60)])
def test_reject_invalid_session_duration_ranges(minimum, maximum):
    with pytest.raises(ValueError):
        validate_clip_duration_range(minimum, maximum)
