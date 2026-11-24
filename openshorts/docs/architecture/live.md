# Live clipping architecture (L0)

This document records the existing job and dashboard contracts that the live
clipper must follow. It describes the repository at the start of L0; live
capture and rendering are not implemented yet.

## Existing job output contract

- `main.py:71-86` initializes `ProgressReporter` against a job output directory
  and initializes its persisted stage data through `stage_tracker.init_stages`.
- `main.py:232-270` exposes `update_clip(index, substage, percent, status,
  ready, file)`. It stores entries in `stages.json` under `clips` and updates
  `counters` (`total`, `ready`, `failed`). `ready=True` sets completed/100%.
- `stage_tracker.py:246-300` persists the same per-clip shape for API-side
  updates. The app also saves child `PROGRESS {json}` output to
  `output/<job_id>/stages.json` (`app.py:3089-3111`).
- `main.py` emits `CLIP_READY <index> <filename>` only after a deliverable is
  ready (the regular and resume paths are around lines 3069 and 3122).
  `app.py:3112-3120` consumes this marker into `jobs[job_id]['ready_files']`.
- `app.py:966-1040` resolves canonical filenames and filters promised clips
  against files that actually exist. A live clip must therefore write its
  final media into its output directory before announcing it ready.
- Existing job artifacts use `output/<job_id>/`; final metadata is assembled
  by `run_job` in `app.py` (around line 3172 onward). Live work should use the
  same `shorts` clip metadata field names used by `DetailClipModel` and the
  existing result card.

## Process lifecycle and concurrency

- `app.py:73` reads `MAX_CONCURRENT_JOBS` (default 1 in this checkout), and
  `app.py:863` creates the semaphore for regular jobs. `run_job_wrapper`
  (`app.py:2147` onward) owns slot release and job cleanup; `run_job`
  (`app.py:3172` onward) launches and monitors the child process.
- `transcribe_backends.py:63-76` sets `ASR_HOST_SLOTS` (default 2) and
  `host_asr_slot()` coordinates ASR across processes with lock files. Live ASR
  must use that shared slot mechanism. The live session may retain its model
  while running, but must call `release_models()` when it stops.
- The current downloader and SSRF constraints are documented in
  `docs/architecture/proxy-routing.md` and `CLAUDE.md` under Download proxies.
  The live resolver must retain the allowlist, `noplaylist`, explicit
  `yt_clients.py` client list, and `ssrf_guard.guarded()` protections.

## Dashboard progress consumption

- `dashboard/src/App.jsx:565-578` derives `pendingClips` from
  `stages.clips`, excluding clips already represented by results or marked
  complete. The processing view around lines 2732-2760 renders the existing
  result cards and pending progress cards.
- The API's progressive job status combines `stages`, `clips`, `counters`, and
  partial `result` data. Live can reuse the clip metadata and card components,
  but a dedicated session endpoint and panel will be needed because the live
  lifecycle does not end when an ordinary job finishes.

## Integration implications

1. Keep each live session in a job-like output directory, write `.owner` where
   applicable, and only report a clip ready after its canonical file exists.
2. Reuse the `ProgressReporter` clip shape and ordinary clip metadata keys;
   live-specific state (capture, buffer, RTF, queue and notices) belongs in
   the live session response rather than overloading ordinary job stages.
3. Do not submit live sessions to the ordinary job semaphore as independent
   batch jobs. Coordinate their single render worker and ASR through explicit
   limits and `host_asr_slot()`.
4. Apply the authorization and media URL rules in
   `docs/architecture/agent-access.md` before exposing session media endpoints.

## L0 baseline

The requested local baseline command was `pytest tests/ -v`. In this checkout
it collected 830 tests (34 skipped) but stopped during collection with 38
import errors because the host Python environment lacks project dependencies
including `boto3`, `numpy`, and `PIL`. This is an environment baseline, not a
test failure attributable to live clipping. Re-run in the project container
once it is available.

## L1 capture implementation

- `live/resolver.py` accepts only YouTube video URL shapes using the repository
  `youtube_non_video_reason` allowlist, checks the submitted and extracted
  media URLs with `security_utils.assert_public_url`, and runs extraction in
  `ssrf_guard.guarded()`. It reuses `fallback_extractor_args()` from
  `yt_clients.py`, disables playlists, requests the best stream at or below
  720p, and follows direct → static → paid routing with cookie and anonymous
  attempts. It reports `programado`, `en_vivo`, or `no_en_vivo`.
- `live/recorder.py` maps separate video and audio streams when yt-dlp provides
  them, copies to MPEG-TS segments, starts a new numbered CSV list per capture
  attempt to avoid truncating a previous run's list, and can re-resolve with
  bounded backoff after disconnects. Its process group is interrupted before
  the kill fallback.
- `live/buffer.py` indexes numbered segments from all CSV lists, supports pin
  and unpin for queued/rendering windows, and prunes expired unpinned files.
- `tests/test_live_capture.py` covers URL filtering, live/scheduled resolution,
  stream mapping/numbering, and pinned retention without network access.

## L2-L4 analysis, judging and scheduling

- `live/audio.py` converts media/segment windows to mono 16 kHz PCM and measures
  per-second dBFS, with a five-second aggregation helper. `live/asr.py` uses
  `run_whisper_transcription()`, `host_asr_slot()`, and the shared Whisper
  parameters. It emits absolute session timestamps, removes duplicate overlap
  words, measures RTF, degrades `small` to `base` and then audio-only after
  three consecutive blocks above 0.8 RTF, and exposes `close()` to call
  `release_models()` at session shutdown.
- `live/signals.py` maintains robust median/MAD audio scores and phrase cues.
  `live/detector.py` fuses audio and keyword evidence, requires two signals or
  one strong signal, snaps to word boundaries, deduplicates overlaps, and
  applies the configured cooldown. `live/judge.py` requests the existing
  `DetailClipModel` shape from the local OpenAI-compatible backend or Gemini,
  bounds its timeout, serializes calls, uses `/no_think` when `LLM_THINK=0`, and falls
  back to transcript-derived metadata on any failure. LLM scoring is fused at
  0.35 with audio 0.45 and keywords 0.20, renormalizing absent signals.
- `live/queue.py` caps render work, evicts the lowest-score queued candidate,
  tracks visible queue/render/discard states, pins source segments, and pauses
  rendering while the three-block ASR RTF average exceeds 0.8.
- `live/window.py` assembles the required MPEG-TS source window, returns the
  time offset and local clip boundaries, and translates word timestamps.
  `tests/test_live_analysis.py`, `tests/test_live_detector.py`, and
  `tests/test_live_queue_window.py` cover these pure/data-level contracts.
- `live/clipper.py` reproduces the regular cut → `main.render_clip` → optional
  hook grounding → hook → captions chain, forces one render worker, disables
  watermarking for self-host, and writes an SRT sidecar. `LIVE_REFRAME=fast`
  forces GENERAL for landscape sources (TRACK for already vertical sources);
  `auto` currently keeps the established renderer until a live benchmark can
  establish a safe automatic threshold. L5 render timings and codec probes
  remain unmeasured until the container is available.

## L6 session API and dashboard

- `live/session.py` launches `live_worker.py` as a separate process in a UUID
  output directory. UUIDs intentionally match the existing project manager's
  job-id contract; `live_metadata.json` and `live_clip_N.mp4` let its project
  scanner recognize generated files. A `.owner` file is written for managed
  sessions. State and project metadata are atomically persisted under a
  process-shared lock, and metadata edits survive the worker's later state
  updates.
- The worker captures segments, runs rolling ASR/audio analysis, judges
  candidates asynchronously, and uses one bounded render queue. Stop mode
  `terminar_pendientes` stops capture and drains the queue; `detener_ya` drops
  queued work and terminates the worker process group after stopping capture.
  Startup recovery marks interrupted sessions stopped without auto-resuming.
- `live_api.py` exposes session creation/list/status/stop, clip metadata edit,
  individual MP4 download and a ZIP containing MP4/SRT/descriptions. App setup
  supplies existing owner, entitlement and media-signing callbacks; media
  links use the existing `/videos` authorization and signatures.
- `dashboard/src/components/LivePanel.jsx` polls state, displays capture/ASR/
  queue notices, renders existing `ResultCard`s, supports editing generated
  text, and exports individual clips or a ZIP. `/en-vivo` loads the app directly
  and the Core navigation includes En vivo on desktop and mobile.

## Remaining live acceptance checks

The synthetic tests validate component contracts but do not replace a real
YouTube session, ffprobe A/V checks, orphan-process check, CPU RTF/render timing,
or end-to-end dashboard/browser run. Those measurements remain pending in
`docs/baseline-live.md`.

## Retention and bounded state

- `RollingTranscript` stores timestamped words and groups them into short
  segments by pause. The detector scans newly available time plus a one-second
  overlap; judge and renderer receive only the candidate's time window.
  Candidate transcript windows stay pinned while judging or rendering.
- `LIVE_TRANSCRIPT_KEEP_SECONDS` defaults to the segment buffer retention plus
  120 seconds. A pinned candidate may extend retention until it finishes.
- `SegmentBuffer` reads newly appended complete CSV rows, retains absolute
  session offsets as media files are pruned, and rereads a CSV after truncation.
  `segments` counts retained files; `segments_total` counts the full capture.
- `LIVE_HISTORY_CANDIDATES` and `LIVE_HISTORY_QUEUE` default to 50 terminal
  records. Active candidates and renders remain in state. Cumulative `stats`
  preserve detection, discard, error and completed-render totals. Finished
  clips and their metadata remain deliverables and are not pruned by these
  history limits.
- State JSON is compact and writes are rate-limited to one per second except at
  transitions. `live_metadata.json` is updated only when clips change.
  `GET /api/live` returns a summary without candidate/queue arrays or signed
  media URLs; `GET /api/live/{id}` returns the selected session detail.
- If Whisper disables itself because CPU load is high, it emits one notice and
  releases the render gate because there is no transcription work left to
  protect. Audio-only detection continues; the configured queue limit remains.
- Live exclusivity is intentional: while capture is active, the rest of the app
  stays disabled through `liveExclusive`, the admission middleware and
  `_assert_live_admission`.
- The optional browser preview is independent of server capture. YouTube
  chooses its preview quality; the iframe does not request a resolution.
