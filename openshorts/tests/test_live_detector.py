import pytest

from live.detector import LiveDetector
from live.judge import judge_candidate
from live.signals import AudioPeakDetector
from live.transcript import RollingTranscript


def test_detector_fuses_audio_and_keyword_and_applies_cooldown():
    detector = LiveDetector(cooldown_seconds=20, min_seconds=25, max_seconds=60,
                            audio_detector=AudioPeakDetector(warmup_seconds=0, threshold=3))
    detector.detect([{"start": 0, "end": 1, "db": -30},
                     {"start": 1, "end": 2, "db": -30},
                     {"start": 2, "end": 3, "db": -30}], {"segments": []}, latest_time=3)
    transcript = {"language": "es", "segments": [{"start": 40, "end": 43,
        "text": "clipea esto", "words": [
            {"word": "clipea", "start": 40.0, "end": 41.0},
            {"word": " esto", "start": 41.1, "end": 42.0},
        ]}]}
    candidates = detector.detect([{"start": 42, "end": 43, "db": -5}], transcript, latest_time=80)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["signals"] == ["audio", "keyword"]
    assert candidate["keyword"] == "clipea esto"
    assert 25 <= candidate["end"] - candidate["start"] <= 60
    assert candidate["start"] >= 0
    assert detector.detect([], transcript, latest_time=80) == []


def test_rolling_detector_matches_full_transcript_for_one_hour():
    class FixedPeaks:
        def add(self, _buckets):
            return [{"start": 1800.0, "end": 1801.0, "z": 5.0}]

    words = [{"word": " palabra", "start": float(index), "end": float(index) + 0.2}
             for index in range(3600)]
    words[1800] = {"word": " clipea", "start": 1800.0, "end": 1800.3}
    words[1801] = {"word": " esto", "start": 1800.4, "end": 1800.7}
    rolling = RollingTranscript()
    rolling.language = "es"
    rolling.add_words(words)
    full = {"language": "es", "segments": rolling.segments(0, 3600)}
    expected = LiveDetector(cooldown_seconds=0, min_seconds=30, max_seconds=60,
                            audio_detector=FixedPeaks()).detect([], full, latest_time=3600)
    actual = LiveDetector(cooldown_seconds=0, min_seconds=30, max_seconds=60,
                          audio_detector=FixedPeaks()).detect([], rolling, latest_time=3600)

    assert [(item["id"], item["start"], item["end"]) for item in actual] == [
        (item["id"], item["start"], item["end"]) for item in expected]


@pytest.mark.parametrize("minimum,maximum", [(10, 30), (30, 60), (60, 120), (120, 240)])
def test_detector_builds_configured_windows_around_highlights(monkeypatch, minimum, maximum):
    import live.detector as detector_module

    monkeypatch.setattr(detector_module, "_keyword_hits", lambda *_args: [{
        "start": 15.0, "end": 16.0, "phrase": "clipea esto", "score": 1.0, "explicit": True,
    }])
    detector = LiveDetector(cooldown_seconds=0, min_seconds=minimum, max_seconds=maximum,
                            audio_detector=AudioPeakDetector(warmup_seconds=0))
    candidate = detector.detect([], {"language": "es", "segments": []}, latest_time=300)[0]

    duration = candidate["end"] - candidate["start"]
    assert minimum <= duration <= maximum
    assert candidate["start"] <= 15 <= candidate["end"]
    assert candidate["min_clip_seconds"] == minimum
    assert candidate["max_clip_seconds"] == maximum


def test_detector_waits_for_minimum_material_or_reports_pending_discard(monkeypatch):
    import live.detector as detector_module

    monkeypatch.setattr(detector_module, "_keyword_hits", lambda *_args: [{
        "start": 5.0, "end": 6.0, "phrase": "clipea esto", "score": 1.0, "explicit": True,
    }])
    detector = LiveDetector(cooldown_seconds=0, min_seconds=30, max_seconds=60,
                            audio_detector=AudioPeakDetector(warmup_seconds=0))

    assert detector.detect([], {"segments": []}, latest_time=10) == []
    assert detector.discard_pending() == 1

    detector.detect([], {"segments": []}, latest_time=10)
    candidates = detector.detect([], {"segments": []}, latest_time=30)
    assert len(candidates) == 1
    assert candidates[0]["end"] - candidates[0]["start"] == 30


def test_judge_falls_back_to_transcript_templates():
    candidate = {"id": "live_1", "start": 2, "end": 32, "predicted_score": 80,
                 "signals": ["audio"], "audio_z": 7, "why": "Pico de audio"}
    result = judge_candidate(candidate, {"segments": [{"start": 1, "end": 34,
        "text": "La jugada increíble cambia todo"}]}, generate=lambda *_args, **_kwargs: None)

    assert result["start"] == 2
    assert result["source_window_id"] == "live_1"
    assert result["viral_hook_text"]
    assert result["predicted_score"] == 80


def test_judge_fuses_llm_score_with_signals():
    candidate = {"id": "live_2", "start": 5, "end": 35, "predicted_score": 100,
                 "signals": ["audio", "keyword"], "audio_z": 6,
                 "keyword_score": 1, "why": "Pico con reacción"}

    def fake_generate(_prompt, _schema, model=None):
        return ({"start": 99, "end": 100, "source_window_id": "bad",
                 "predicted_score": 20, "video_description_for_tiktok": "t",
                 "video_description_for_instagram": "i",
                 "video_title_for_youtube_short": "title", "viral_hook_text": "hook",
                 "why": "reason"}, None)

    result = judge_candidate(candidate, {"segments": []}, generate=fake_generate)

    assert result["start"] == 5
    assert result["end"] == 35
    assert result["source_window_id"] == "live_2"
    assert result["predicted_score"] == 72
