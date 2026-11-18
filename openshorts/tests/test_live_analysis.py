import wave

from live.asr import IncrementalTranscriber, block_starts
from live.audio import aggregate_buckets, rms_db_buckets
from live.signals import AudioPeakDetector, keyword_events, robust_z_score


def _wav(path, amplitude=10000, seconds=6):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        for second in range(seconds):
            value = amplitude if second in (4, 5) else 100
            wav.writeframes(int(value).to_bytes(2, "little", signed=True) * 16000)


def test_audio_energy_uses_dbfs_and_aggregates(tmp_path):
    path = tmp_path / "signal.wav"
    _wav(path)
    buckets = rms_db_buckets(path)
    grouped = aggregate_buckets(buckets, seconds=5)

    assert len(buckets) == 6
    assert buckets[4]["db"] > buckets[0]["db"] + 20
    assert len(grouped) == 2


def test_robust_peak_detector_warms_then_detects_spike():
    detector = AudioPeakDetector(warmup_seconds=0, threshold=3)
    baseline = [{"start": t, "end": t + 1, "db": -30.0} for t in range(5)]
    detector.add(baseline)
    peaks = detector.add([{"start": 5, "end": 6, "db": -5.0}])

    assert len(peaks) == 1
    assert peaks[0]["kind"] == "audio_peak"
    assert peaks[0]["z"] >= 3
    assert robust_z_score(-5, [-30, -30, -30]) >= 3


def test_keyword_detector_finds_reaction_and_clip_command():
    events = keyword_events("¡Wow! clipea esto", language="es")

    assert {event["text"] for event in events} == {"wow", "clipea esto"}


def test_incremental_transcription_offsets_and_deduplicates_overlap():
    def fake(_wav_path):
        return {"text": " Hola mundo", "language": "es", "segments": [
            {"start": 0.0, "end": 2.0, "text": " Hola mundo", "words": [
                {"word": " Hola", "start": 0.0, "end": 0.5},
                {"word": " mundo", "start": 0.6, "end": 1.0},
            ]},
        ]}

    transcriber = IncrementalTranscriber(transcribe=fake)
    transcriber.transcribe_block("a.wav", session_start=0, audio_duration=2)
    second = transcriber.transcribe_block("b.wav", session_start=0, audio_duration=2)

    assert second["segments"][0]["start"] == 0
    assert len(second["segments"][0]["words"]) == 2
    offset = transcriber.transcribe_block("c.wav", session_start=10, audio_duration=2)
    assert offset["segments"][0]["start"] == 10
    assert offset["segments"][0]["words"][0]["start"] == 10


def test_live_asr_block_schedule_has_two_second_overlap():
    assert list(block_starts(61, block_seconds=30, overlap_seconds=2)) == [0, 28, 56]
