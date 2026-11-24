import wave

from live.asr import IncrementalTranscriber, block_starts
from live.audio import aggregate_buckets, rms_db_buckets
from live.signals import AudioPeakDetector, keyword_events, robust_z_score
from live.transcript import RollingTranscript
from live.judge import _fallback, _transcript_context


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


def test_asr_overlap_deduplicates_timestamp_drift_within_overlap():
    calls = iter([
        {"text": " hola", "language": "es", "segments": [{"start": 28, "end": 29,
         "text": " hola", "words": [{"word": " hola", "start": 28.1, "end": 28.5}]}]},
        {"text": " hola", "language": "es", "segments": [{"start": 0.3, "end": 1,
         "text": " hola", "words": [{"word": " hola", "start": 0.3, "end": 0.7}]}]},
    ])
    transcriber = IncrementalTranscriber(transcribe=lambda _path: next(calls), block_seconds=30,
                                         overlap_seconds=2)
    transcriber.transcribe_block("a.wav", session_start=0, audio_duration=30)
    second = transcriber.transcribe_block("b.wav", session_start=28, audio_duration=30)

    assert len(second["segments"][0]["words"]) == 1
    assert second["segments"][0]["words"][0]["start"] == 28.1
    assert len(transcriber._previous_words) <= 3


def test_rolling_transcript_groups_segments_and_keeps_pinned_windows():
    transcript = RollingTranscript()
    transcript.add_words([
        {"word": " Hola", "start": 100, "end": 100.3},
        {"word": " mundo", "start": 100.4, "end": 100.8},
        {"word": " luego", "start": 103, "end": 103.3},
    ])
    transcript.pin("clip", 99, 101)
    removed = transcript.prune(102)

    assert removed == 0
    assert [part["text"] for part in transcript.segments(99, 104)] == ["Hola mundo", "luego"]
    transcript.unpin("clip")
    assert transcript.prune(102) == 2


def test_judge_context_uses_candidate_time_in_long_stream():
    transcript = {"segments": [
        {"start": 0, "end": 100, "text": "inicio del directo " * 100,
         "words": [{"word": "inicio", "start": 0, "end": 1}]},
        {"start": 2290, "end": 2320, "text": "candidato importante palabra",
         "words": [{"word": "candidato", "start": 2300, "end": 2301},
                   {"word": " importante", "start": 2301, "end": 2302}]},
    ]}
    context = _transcript_context(transcript, 2300, 2310)
    fallback = _fallback({"id": "live_1", "start": 2300, "end": 2310}, context)

    assert "candidato importante" in context
    assert not context.startswith("inicio del directo")
    assert fallback["viral_hook_text"].startswith("candidato importante")


def test_judge_contexts_are_independent_and_sparse_context_expands_locally():
    transcript = {"segments": [{"start": 0, "end": 5000, "text": "sesion completa",
        "words": ([{"word": f" inicio{i}", "start": i, "end": i + 0.2}
                   for i in range(20)] +
                  [{"word": f" tarde{i}", "start": 4900 + i, "end": 4900 + i + 0.2}
                   for i in range(20)])}]}
    early = _transcript_context(transcript, 3, 4)
    late = _transcript_context(transcript, 4903, 4904)

    assert "inicio" in early and "tarde" not in early
    assert "tarde" in late and "inicio" not in late


def test_judge_context_does_not_use_unsegmented_session_wide_text():
    transcript = {"segments": [{"start": 0, "end": 5000,
                                 "text": "texto de toda la transmision"}]}
    assert _transcript_context(transcript, 4900, 4910) == ""


def test_live_asr_block_schedule_has_two_second_overlap():
    assert list(block_starts(61, block_seconds=30, overlap_seconds=2)) == [0, 28, 56]


def test_disabling_asr_releases_render_gate_and_emits_notice_once(monkeypatch):
    import live.asr as asr_module
    from live.queue import RenderPriorityGate

    clock = [0.0]
    monkeypatch.setattr(asr_module.time, "monotonic",
                        lambda: (clock.__setitem__(0, clock[0] + 25.0) or clock[0]))
    transcriber = IncrementalTranscriber(model="small", transcribe=lambda _path: {
        "text": "", "language": "es", "segments": []})
    results = [transcriber.transcribe_block("fake.wav", session_start=index * 28,
                                            audio_duration=30) for index in range(6)]
    disabled = transcriber.transcribe_block("fake.wav", session_start=168, audio_duration=30)
    disabled_again = transcriber.transcribe_block("fake.wav", session_start=196, audio_duration=30)
    gate = RenderPriorityGate(samples=3)
    gate.update_asr_rtf(results[3]["rtf"])
    gate.update_asr_rtf(results[4]["rtf"])
    assert gate.update_asr_rtf(results[5]["rtf"]) is True
    assert gate.release_for_asr_disabled() is False

    assert results[2]["notice"] == "transcripción degradada a base por carga"
    assert results[5]["notice"] == "ASR detenido por carga; se mantienen las señales de audio"
    assert disabled["rtf"] is None
    assert disabled["notice"] is None
    assert disabled_again["notice"] is None
    assert gate.paused is False


def test_live_load_benchmark_shows_disabled_asr_does_not_strand_queue():
    from scripts.benchmark.benchmark_live_load import simulate

    before = simulate(hours=4, release_when_asr_disabled=False)
    after = simulate(hours=4, release_when_asr_disabled=True)

    assert before["rendered"] == 0
    assert before["discarded"] == 93
    assert after["rendered"] == 96
    assert after["discarded"] == 0
