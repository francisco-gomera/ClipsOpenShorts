"""Characterize render throughput when disabled ASR leaves a stale high RTF."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from live.queue import LiveWorkQueue, RenderPriorityGate


def simulate(hours: int = 4, *, candidate_every_seconds: int = 150,
             render_duration_seconds: int = 60,
             release_when_asr_disabled: bool = False) -> dict:
    gate = RenderPriorityGate(samples=3)
    # The current transcriber returns its last high RTF after ASR is disabled.
    for _ in range(3):
        gate.update_asr_rtf(0.84)
    if release_when_asr_disabled:
        gate.release_for_asr_disabled()
    queue = LiveWorkQueue(max_queue=3)
    candidate_count = int(hours * 3600 / candidate_every_seconds)
    rendered = 0
    discarded = 0
    render_available_at = 0
    for index in range(candidate_count):
        arrival = index * candidate_every_seconds
        result = queue.offer({"id": f"live_{index:06d}", "predicted_score": 60})
        if result["status"] == "descartado_por_saturacion":
            discarded += 1
        # One deterministic render worker consumes one fixed-duration job at a time.
        if not gate.paused and arrival >= render_available_at:
            item = queue.get(timeout=0)
            if item:
                queue.complete(item["id"])
                rendered += 1
                render_available_at = arrival + render_duration_seconds
    if not gate.paused:
        while queue.snapshot()["queue_size"]:
            item = queue.get(timeout=0)
            if not item:
                break
            queue.complete(item["id"])
            rendered += 1
    return {"hours": hours, "candidates": candidate_count,
            "rendered": rendered, "discarded": discarded,
            "queued_at_end": queue.snapshot()["queue_size"], "render_paused": gate.paused,
            "render_seconds_per_clip": render_duration_seconds}


if __name__ == "__main__":
    print("Antes:", simulate(release_when_asr_disabled=False))
    print("Con liberación al desactivar ASR:", simulate(release_when_asr_disabled=True))
