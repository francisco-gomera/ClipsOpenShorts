"""Characterize render throughput when disabled ASR leaves a stale high RTF."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from live.queue import LiveWorkQueue, RenderPriorityGate


def simulate(hours: int = 4, *, candidate_every_seconds: int = 150,
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
    for index in range(candidate_count):
        result = queue.offer({"id": f"live_{index:06d}", "predicted_score": 60})
        if result["status"] == "descartado_por_saturacion":
            discarded += 1
        # The render worker waits at the priority gate and therefore never calls get().
        if not gate.paused:
            item = queue.get(timeout=0)
            if item:
                queue.complete(item["id"])
                rendered += 1
    return {"hours": hours, "candidates": candidate_count,
            "rendered": rendered, "discarded": discarded,
            "queued_at_end": queue.snapshot()["queue_size"], "render_paused": gate.paused}


if __name__ == "__main__":
    print("Antes:", simulate(release_when_asr_disabled=False))
    print("Con liberación al desactivar ASR:", simulate(release_when_asr_disabled=True))
