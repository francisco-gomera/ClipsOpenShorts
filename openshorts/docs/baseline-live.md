# Live clipping measurements

No live performance measurements have been collected yet. The Windows host
does not currently have access to the Docker daemon, and the local Python
environment lacks the media/ASR dependencies, so no capture or render has been
run. Do not treat the planned numbers in `PLAN_live_clipper_v2.md` as a new
measurement.

Fill this table from a 15–30 minute local direct session once Docker and the
configured Whisper model are available:

| Measurement | Result |
| --- | --- |
| CPU ASR RTF without rendering | pending |
| CPU ASR RTF while rendering | pending |
| Render time per clip (source duration and layout) | pending |
| Clips emitted / dropped by bounded queue | pending |
| Peak backend container RAM | pending |
| ffprobe output codec, dimensions, duration and A/V sync | pending |

Record the `LIVE_REFRAME` mode, `LIVE_WHISPER_MODEL`, and CPU thread count with
each run so later comparisons use the same settings.
