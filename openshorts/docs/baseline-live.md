# Live clipping measurements

The figures below are deterministic synthetic measurements. They cover bounded
in-memory detector work, cached CSV refresh and a four-hour queue simulation;
they are not YouTube capture or Whisper/render throughput measurements.

## Retention optimization benchmarks

Measured on an AMD Ryzen 5 7535HS with Radeon Graphics, Windows host, Python
3.12.10. `LIVE_WHISPER_MODEL=small` is the configured default; the detector and
buffer benchmarks do not load or invoke Whisper. Scripts ran at commit
`78e4e9a` (F1 `1163c65`, F2 `67acdfb`, F4 `4a00b7b`).

| Script / scenario | Result |
| --- | --- |
| `benchmark_live_retention.py`, detector at 1 h | 0.040 ms/call |
| `benchmark_live_retention.py`, detector at 4 h | 0.040 ms/call |
| `benchmark_live_retention.py`, detector at 12 h | 0.075 ms/call |
| `benchmark_live_retention.py`, detector at 24 h | 0.041 ms/call |
| `benchmark_live_buffer.py`, cached refresh for 24 h of CSV rows | 1.895 ms/call |
| `benchmark_live_load.py`, 4 h before releasing the gate | 96 candidates, 0 rendered, 93 discarded, 3 queued |
| `benchmark_live_load.py`, 4 h after releasing the gate | 96 candidates, 96 rendered, 0 discarded, 0 queued |

F4 uses synthetic ASR timing and a bounded queue. It does not represent a
measured CPU Whisper session. A real YouTube session, A/V probe, render timing,
container RAM and browser network measurement remain pending.

For each real run, record the `LIVE_REFRAME` mode, `LIVE_WHISPER_MODEL`, CPU
model and thread count so later comparisons use the same settings.
