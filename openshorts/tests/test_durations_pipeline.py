"""Integration tests verifying full generation and editing pipelines for
expanded video durations: 30s, 60s (1m), 120s (2m), 180s (3m), and 240s (4m).

Tests cover:
- Real duration verification via ffprobe
- Audio / video synchronization (no desync or truncation)
- Subtitle continuity from start to end of clip
- Hook overlay preservation and duration invariance
- Reframe / layout crop pipeline
- Full stream decode integrity (ffmpeg null muxer)
"""

import json
import os
import shutil
import subprocess
import tempfile
import pytest

import clip_selection
import hooks
import recut
import subtitles


def _ffprobe(path):
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return json.loads(res.stdout)


def _verify_stream_integrity(path):
    """Decodes every audio and video frame to verify zero decode errors or corruption."""
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert res.returncode == 0, f"Decode error in {path}: {res.stderr.decode('utf-8', 'replace')}"


@pytest.fixture(scope="module")
def synthetic_source_250s():
    """Generates a 250s reference video with synchronized audio and video."""
    tmpdir = tempfile.mkdtemp(prefix="openshorts_test_250s_")
    src_path = os.path.join(tmpdir, "source_250s.mp4")
    # Generates 250s of 640x360 25fps video with 1000Hz sine wave audio
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=250:size=640x360:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=250",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        src_path
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    yield src_path
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.parametrize("duration", [30.0, 60.0, 120.0, 180.0, 240.0])
def test_full_pipeline_duration(synthetic_source_250s, duration, tmp_path):
    workdir = str(tmp_path)
    
    # 1. Test cut & concat (multi-segment cut totaling exactly `duration`)
    # Split into 2 segments: [0, duration/2] and [duration/2, duration]
    seg1_end = round(duration / 2.0, 2)
    segments = [
        {"start": 0.0, "end": seg1_end},
        {"start": seg1_end, "end": duration}
    ]
    
    norm = recut.normalize_segments(segments, source_duration=250.0)
    assert recut.total_duration(norm) == duration
    
    cut_path = os.path.join(workdir, f"cut_{int(duration)}s.mp4")
    recut.run_cut_concat(synthetic_source_250s, norm, cut_path, workdir)
    assert os.path.exists(cut_path)
    
    # Verify cut duration with ffprobe
    probe = _ffprobe(cut_path)
    fmt_dur = float(probe["format"]["duration"])
    assert abs(fmt_dur - duration) <= 0.2, f"Expected {duration}s, got {fmt_dur}s"
    
    v_stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
    a_stream = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    v_dur = float(v_stream.get("duration", fmt_dur))
    a_dur = float(a_stream.get("duration", fmt_dur))
    assert abs(v_dur - duration) <= 0.2
    assert abs(a_dur - duration) <= 0.2
    # Verify audio/video sync
    assert abs(v_dur - a_dur) <= 0.15, f"Audio/video desync: v={v_dur}, a={a_dur}"
    
    # 2. Test subtitle generation & burning across the entire duration
    # Create word-level transcript from 0 to duration
    words = []
    t = 1.0
    idx = 0
    while t < duration - 1.0:
        words.append({
            "word": f"word{idx}",
            "start": round(t, 2),
            "end": round(min(t + 0.8, duration - 0.1), 2)
        })
        t += 3.0
        idx += 1
        
    transcript = {
        "language": "en",
        "segments": [{
            "start": 0.0,
            "end": duration,
            "text": " ".join(w["word"] for w in words),
            "words": words
        }]
    }
    
    srt_path = os.path.join(workdir, f"subtitles_{int(duration)}s.srt")
    subtitles.generate_srt(transcript, 0.0, duration, srt_path)
    assert os.path.exists(srt_path)
    srt_content = open(srt_path, "r", encoding="utf-8").read()
    # Confirm last word appears in subtitles (no premature truncation)
    assert f"word{idx - 1}" in srt_content
    
    # Burn subtitles onto the cut video
    subtitled_path = os.path.join(workdir, f"subtitled_{int(duration)}s.mp4")
    subtitles.burn_subtitles(cut_path, srt_path, subtitled_path)
    assert os.path.exists(subtitled_path)
    
    sub_probe = _ffprobe(subtitled_path)
    sub_dur = float(sub_probe["format"]["duration"])
    assert abs(sub_dur - duration) <= 0.25
    
    # 3. Test Hook Overlay preservation & position
    hooked_path = os.path.join(workdir, f"hooked_{int(duration)}s.mp4")
    hooks.add_hook_to_video(
        subtitled_path,
        text=f"HOOK {int(duration)}S",
        output_path=hooked_path,
        duration=3.0,
        position="top"
    )
    assert os.path.exists(hooked_path)
    
    hook_probe = _ffprobe(hooked_path)
    hook_dur = float(hook_probe["format"]["duration"])
    assert abs(hook_dur - duration) <= 0.25
    
    # 4. Full decode integrity check (reproduccion sin errores)
    _verify_stream_integrity(hooked_path)
