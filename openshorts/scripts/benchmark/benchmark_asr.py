import time
import json
import os
import sys

# Ensure CPU mode as specified in D3
os.environ["WHISPER_DEVICE"] = "cpu"
os.environ["WHISPER_COMPUTE_TYPE"] = "int8"
os.environ["TRANSCRIBE_BACKEND"] = "whisper"

from transcribe_backends import transcribe_media

VIDEOS = [
    {
        "name": "single_speaker",
        "path": "/app/docs/reference_dataset/videos/single_speaker.mp4",
        "out": "/app/docs/reference_dataset/single_speaker_transcript.json",
        "description": "Monologue / Single speaker (Barack Obama Weekly Address, 3m 49s)"
    },
    {
        "name": "two_speaker_podcast",
        "path": "/app/docs/reference_dataset/videos/two_speaker_podcast.mp4",
        "out": "/app/docs/reference_dataset/two_speaker_transcript.json",
        "description": "Conversation / 2 speakers (White House Marc Maron WTF Podcast, 3m 45s)"
    },
    {
        "name": "speechless_video",
        "path": "/app/docs/reference_dataset/videos/speechless_video.mp4",
        "out": "/app/docs/reference_dataset/speechless_transcript.json",
        "description": "Voiceless / Animation (Big Buck Bunny, 2m 42s)"
    }
]

results = []

for v in VIDEOS:
    print(f"\n==========================================")
    print(f"Starting ASR benchmark for: {v['name']}")
    print(f"Description: {v['description']}")
    print(f"Path: {v['path']}")
    print(f"==========================================")
    
    t0 = time.time()
    try:
        transcript = transcribe_media(v["path"])
        elapsed = time.time() - t0
        
        # Save transcript checkpoint
        with open(v["out"], "w", encoding="utf-8") as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)
            
        word_count = len(transcript.get("text", "").split())
        segment_count = len(transcript.get("segments", []))
        
        result_info = {
            "name": v["name"],
            "description": v["description"],
            "elapsed_seconds": round(elapsed, 2),
            "language": transcript.get("language"),
            "segment_count": segment_count,
            "word_count": word_count,
            "status": "success",
            "output_path": v["out"]
        }
        print(f"SUCCESS in {elapsed:.2f}s | Language: {transcript.get('language')} | Segments: {segment_count} | Words: {word_count}")
        results.append(result_info)
    except Exception as e:
        elapsed = time.time() - t0
        print(f"FAILED in {elapsed:.2f}s: {e}")
        results.append({
            "name": v["name"],
            "description": v["description"],
            "elapsed_seconds": round(elapsed, 2),
            "status": "failed",
            "error": str(e)
        })

summary_path = "/app/docs/reference_dataset/asr_benchmark_summary.json"
with open(summary_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\nAll done! Summary saved to:", summary_path)
