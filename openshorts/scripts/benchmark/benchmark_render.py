import time
import json
import os
import subprocess
from ffmpeg_utils import cut_clip
from main import render_clip, auto_caption_clip

source_video = "/app/docs/reference_dataset/videos/single_speaker.mp4"
transcript_file = "/app/docs/reference_dataset/single_speaker_transcript.json"

with open(transcript_file, "r", encoding="utf-8") as f:
    transcript = json.load(f)

work_dir = "/app/docs/reference_dataset/render_baseline"
os.makedirs(work_dir, exist_ok=True)

raw_clip = os.path.join(work_dir, "ref_clip_raw.mp4")
vertical_clip = os.path.join(work_dir, "ref_clip_vertical.mp4")

# Clip boundaries: 10s to 40s (30s clip)
clip_start = 10.0
clip_end = 40.0

print("=== 1. Cutting 30s segment ===")
t0 = time.time()
cut_clip(source_video, raw_clip, clip_start, clip_end, 1)
cut_time = time.time() - t0
print(f"Cut finished in {cut_time:.2f}s")

print("=== 2. Reframe to 9:16 vertical on CPU ===")
t1 = time.time()
success = render_clip(raw_clip, vertical_clip, output_format="vertical")
reframe_time = time.time() - t1
print(f"Reframe finished (success={success}) in {reframe_time:.2f}s")

print("=== 3. Burning Subtitles ===")
t2 = time.time()
subtitled_clip = auto_caption_clip(vertical_clip, transcript, clip_start, clip_end)
subtitles_time = time.time() - t2
print(f"Subtitles burned to: {subtitled_clip} in {subtitles_time:.2f}s")

# Extract 5 baseline keyframes for visual reference (ssim baseline)
frames_dir = "/app/docs/reference_dataset/frames"
timestamps = [5, 10, 15, 20, 25] # in clip seconds
final_target = subtitled_clip if (subtitled_clip and os.path.exists(subtitled_clip)) else vertical_clip

for ts in timestamps:
    out_frame = os.path.join(frames_dir, f"frame_{ts:02d}s.png")
    cmd = [
        "ffmpeg", "-y", "-ss", str(ts),
        "-i", final_target,
        "-vframes", "1",
        "-q:v", "2",
        out_frame
    ]
    subprocess.run(cmd, check=True)
    print(f"Extracted baseline frame at {ts}s: {out_frame}")

summary = {
    "clip_start": clip_start,
    "clip_end": clip_end,
    "clip_duration": clip_end - clip_start,
    "cut_seconds": round(cut_time, 2),
    "reframe_seconds": round(reframe_time, 2),
    "subtitles_seconds": round(subtitles_time, 2),
    "total_render_pipeline_seconds": round(cut_time + reframe_time + subtitles_time, 2),
    "frames": [f"frame_{ts:02d}s.png" for ts in timestamps]
}

with open("/app/docs/reference_dataset/render_benchmark_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print("\nRender benchmark complete!")
