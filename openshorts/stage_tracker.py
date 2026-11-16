"""
Módulo de seguimiento y reintento de etapas de procesamiento (Fases 4 y 5).
Gestiona stages.json en el directorio del proyecto y permite:
- Registrar el progreso de cada etapa con timestamps y duración.
- Inferir el estado de etapas a partir de artefactos en disco.
- Determinar la última etapa válida para reanudar/reintentar trabajos fallidos o interrumpidos.
"""

import os
import json
import time
import glob
from typing import Dict, Any, Optional, List, Tuple


STAGES_ORDER = [
    "download",
    "transcription",
    "clip_selection",
    "cut_and_reframe",
    "hooks",
    "subtitles",
]

STAGE_LABELS = {
    "download": "Source Preparation",
    "transcription": "Audio Transcription",
    "clip_selection": "AI Moment Selection",
    "cut_and_reframe": "Cut & Reframe (9:16)",
    "hooks": "Visual Hooks",
    "subtitles": "Subtitle Burn-in",
}


"""
Módulo de seguimiento y reintento de etapas de procesamiento (Fases 1 y 2).
Gestiona stages.json en el directorio del proyecto con contrato uniforme y Lock thread-safe:
- Registrar el progreso de cada etapa con timestamps, duración, porcentaje, unidades y velocidad.
- Contrato uniforme con sub-etapas de clips, contadores y estado de recuperación.
- Estimación de progreso global y ETA con base en historial (output/.stats/stage_history.json).
- Inferir el estado de etapas a partir de artefactos en disco.
- Determinar la última etapa válida para reanudar/reintentar trabajos fallidos o interrumpidos.
"""

import os
import json
import time
import glob
import threading
from typing import Dict, Any, Optional, List, Tuple


_tracker_lock = threading.Lock()

STAGES_ORDER = [
    "download",
    "transcription",
    "clip_selection",
    "cut_and_reframe",
    "hooks",
    "subtitles",
]

STAGE_LABELS = {
    "download": "Source Preparation",
    "transcription": "Audio Transcription",
    "clip_selection": "AI Moment Selection",
    "cut_and_reframe": "Cut & Reframe (9:16)",
    "hooks": "Visual Hooks",
    "subtitles": "Subtitle Burn-in",
}


def _stages_file(job_dir: str) -> str:
    return os.path.join(job_dir, "stages.json")


def _stats_history_file(base_output_dir: str) -> str:
    stats_dir = os.path.join(base_output_dir, ".stats")
    os.makedirs(stats_dir, exist_ok=True)
    return os.path.join(stats_dir, "stage_history.json")


def _create_stage_item(st: str) -> Dict[str, Any]:
    return {
        "name": st,
        "label": STAGE_LABELS.get(st, st),
        "status": "pending",  # pending, running, completed, failed, skipped
        "mode": "determinate" if st in ("download", "transcription", "cut_and_reframe") else "indeterminate",
        "percent": 0.0 if st in ("download", "transcription", "cut_and_reframe") else None,
        "message": None,
        "started_at": None,
        "completed_at": None,
        "updated_at": None,
        "duration_seconds": None,
        "units": None,  # {"done": 0, "total": 0, "label": "..."}
        "bytes": None,
        "speed": None,
        "eta_seconds": None,
        "attempts": 1,
        "error": None,
        "skipped_reason": None,
    }


def init_stages(job_dir: str, job_id: Optional[str] = None) -> Dict[str, Any]:
    """Inicializa la estructura de stages.json con el Contrato Uniforme."""
    with _tracker_lock:
        os.makedirs(job_dir, exist_ok=True)
        stages = {st: _create_stage_item(st) for st in STAGES_ORDER}
        now = time.time()
        data = {
            "version": 1,
            "job_id": job_id or os.path.basename(job_dir),
            "status": "queued",
            "percent": None,
            "mode": "indeterminate",
            "eta_seconds": None,
            "eta_confidence": "none",
            "stage_index": 0,
            "stage_total": len(STAGES_ORDER),
            "current_stage": None,
            "created_at": now,
            "updated_at": now,
            "stages": stages,
            "clips": [],
            "counters": {
                "total": 0,
                "ready": 0,
                "failed": 0,
            },
            "recovery": {
                "state": "normal",  # normal, waiting_rate_limit, retrying
                "retry_at": None,
                "message": None,
            },
        }
        _save_stages_locked(job_dir, data)
        return data


def read_stages(job_dir: str) -> Optional[Dict[str, Any]]:
    """Lee stages.json del directorio del trabajo de forma thread-safe."""
    with _tracker_lock:
        return _read_stages_unlocked(job_dir)


def _read_stages_unlocked(job_dir: str) -> Optional[Dict[str, Any]]:
    path = _stages_file(job_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Error leyendo stages.json en {job_dir}: {e}")
        return None


def save_stages_direct(job_dir: str, data: Dict[str, Any]):
    """Guarda stages.json de forma atómica y thread-safe directamente desde un búfer."""
    with _tracker_lock:
        _save_stages_locked(job_dir, data)


def _save_stages_locked(job_dir: str, data: Dict[str, Any]):
    """Guarda de forma atómica stages.json (asume _tracker_lock adquirido)."""
    os.makedirs(job_dir, exist_ok=True)
    path = _stages_file(job_dir)
    temp_path = f"{path}.tmp.{os.getpid()}_{threading.get_ident()}"
    try:
        data["updated_at"] = time.time()
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        print(f"⚠️ Error guardando stages.json en {job_dir}: {e}")


def _save_stages(job_dir: str, data: Dict[str, Any]):
    """Guarda stages.json adquiriendo el lock del tracker."""
    with _tracker_lock:
        _save_stages_locked(job_dir, data)


def start_stage(job_dir: str, stage_name: str, mode: Optional[str] = None) -> Dict[str, Any]:
    """Marca una etapa como 'running' con contrato uniforme."""
    with _tracker_lock:
        data = _read_stages_unlocked(job_dir) or init_stages(job_dir)
        data["status"] = "processing"
        data["current_stage"] = stage_name
        if stage_name in STAGES_ORDER:
            data["stage_index"] = STAGES_ORDER.index(stage_name) + 1

        stage_info = data.get("stages", {}).setdefault(stage_name, _create_stage_item(stage_name))
        stage_info["status"] = "running"
        stage_info["started_at"] = time.time()
        stage_info["updated_at"] = time.time()
        stage_info["error"] = None
        if mode:
            stage_info["mode"] = mode
        _save_stages_locked(job_dir, data)
        return data


def update_stage_progress(
    job_dir: str,
    stage_name: str,
    percent: Optional[float] = None,
    mode: Optional[str] = None,
    message: Optional[str] = None,
    units: Optional[Dict[str, Any]] = None,
    bytes_count: Optional[int] = None,
    speed: Optional[float] = None,
    eta_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Actualiza métricas de progreso de una etapa activa."""
    with _tracker_lock:
        data = _read_stages_unlocked(job_dir) or init_stages(job_dir)
        stage_info = data.get("stages", {}).setdefault(stage_name, _create_stage_item(stage_name))
        stage_info["updated_at"] = time.time()
        if percent is not None:
            stage_info["percent"] = round(float(percent), 1)
        if mode:
            stage_info["mode"] = mode
        if message is not None:
            stage_info["message"] = str(message)
        if units is not None:
            stage_info["units"] = units
        if bytes_count is not None:
            stage_info["bytes"] = int(bytes_count)
        if speed is not None:
            stage_info["speed"] = round(float(speed), 1)
        if eta_seconds is not None:
            stage_info["eta_seconds"] = max(0, int(eta_seconds))

        _save_stages_locked(job_dir, data)
        return data


def update_clip_progress(
    job_dir: str,
    clip_index: int,
    substage: Optional[str] = None,
    percent: Optional[float] = None,
    status: Optional[str] = None,
    ready: bool = False,
    file: Optional[str] = None,
) -> Dict[str, Any]:
    """Actualiza el progreso de un clip individual en clips[] y contadores."""
    with _tracker_lock:
        data = _read_stages_unlocked(job_dir) or init_stages(job_dir)
        clips = data.setdefault("clips", [])

        # Asegurar tamaño suficiente en clips list
        while len(clips) <= clip_index:
            idx = len(clips)
            clips.append({
                "index": idx,
                "status": "pending",
                "substage": None,
                "percent": 0.0,
                "ready": False,
                "file": None,
            })

        c = clips[clip_index]
        if status:
            c["status"] = status
        if substage:
            c["substage"] = substage
        if percent is not None:
            c["percent"] = round(float(percent), 1)
        if ready:
            c["ready"] = True
            c["status"] = "completed"
            c["percent"] = 100.0
        if file:
            c["file"] = file

        # Recalcular counters
        total = len(clips)
        ready_count = sum(1 for item in clips if item.get("ready"))
        failed_count = sum(1 for item in clips if item.get("status") == "failed")
        data["counters"] = {
            "total": total,
            "ready": ready_count,
            "failed": failed_count,
        }

        _save_stages_locked(job_dir, data)
        return data


def set_recovery_state(
    job_dir: str,
    state: str = "normal",
    retry_at: Optional[float] = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Actualiza el estado de recuperación (ej. waiting_rate_limit de Gemini)."""
    with _tracker_lock:
        data = _read_stages_unlocked(job_dir) or init_stages(job_dir)
        data["recovery"] = {
            "state": state,
            "retry_at": retry_at,
            "message": message,
        }
        _save_stages_locked(job_dir, data)
        return data


def finish_stage(
    job_dir: str,
    stage_name: str,
    error: Optional[str] = None,
    skip: bool = False,
    skipped_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Marca una etapa como 'completed', 'failed' o 'skipped'."""
    with _tracker_lock:
        data = _read_stages_unlocked(job_dir) or init_stages(job_dir)
        stage_info = data.get("stages", {}).setdefault(stage_name, _create_stage_item(stage_name))
        now = time.time()
        stage_info["updated_at"] = now
        if error:
            stage_info["status"] = "failed"
            stage_info["error"] = str(error)
            data["status"] = "failed"
            data["error"] = str(error)
        elif skip:
            stage_info["status"] = "skipped"
            stage_info["skipped_reason"] = skipped_reason or "Stage not requested"
            stage_info["percent"] = 100.0
        else:
            stage_info["status"] = "completed"
            stage_info["error"] = None
            stage_info["percent"] = 100.0

        stage_info["completed_at"] = now
        if stage_info.get("started_at"):
            stage_info["duration_seconds"] = round(now - stage_info["started_at"], 2)

        _save_stages_locked(job_dir, data)
        return data


def complete_job(job_dir: str, media_duration_seconds: Optional[float] = None) -> Dict[str, Any]:
    """Marca el trabajo completo en stages.json y registra histórico."""
    with _tracker_lock:
        data = _read_stages_unlocked(job_dir) or init_stages(job_dir)
        data["status"] = "completed"
        data["current_stage"] = "complete"
        data["percent"] = 100.0
        data["mode"] = "determinate"
        data["eta_seconds"] = 0
        data["stage_index"] = len(STAGES_ORDER)
        _save_stages_locked(job_dir, data)

        # Registrar en histórico si hay información de duración de medio
        if media_duration_seconds and media_duration_seconds > 0:
            base_out = os.path.dirname(job_dir.rstrip("/\\"))
            job_id = data.get("job_id", os.path.basename(job_dir))
            record_stage_history(base_out, job_id, media_duration_seconds, data.get("stages", {}))

        return data


def record_stage_history(
    base_output_dir: str,
    job_id: str,
    media_duration_seconds: float,
    stages_dict: Dict[str, Any]
):
    """Guarda la duración de cada etapa normalizada por minuto de medio en output/.stats/stage_history.json
    con tamaño máximo y rotación de hasta 500 registros.
    """
    if not media_duration_seconds or media_duration_seconds <= 0:
        return
    history_file = _stats_history_file(base_output_dir)
    media_minutes = max(0.1, media_duration_seconds / 60.0)

    stage_durations = {}
    for st_name, st_info in stages_dict.items():
        dur = st_info.get("duration_seconds")
        if dur is not None and dur > 0 and st_info.get("status") == "completed":
            stage_durations[st_name] = round(dur / media_minutes, 3)

    if not stage_durations:
        return

    record = {
        "job_id": job_id,
        "timestamp": time.time(),
        "media_minutes": round(media_minutes, 2),
        "normalized_durations": stage_durations,
    }

    try:
        entries = []
        if os.path.isfile(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    entries = json.load(f)
                if not isinstance(entries, list):
                    entries = []
            except Exception:
                entries = []

        entries.append(record)
        # Rotación a máximo 500 entradas
        if len(entries) > 500:
            entries = entries[-500:]

        tmp_hist = f"{history_file}.tmp.{os.getpid()}"
        with open(tmp_hist, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp_hist, history_file)
    except Exception as e:
        print(f"⚠️ Error guardando stage_history.json: {e}")


def load_stage_history_averages(base_output_dir: str) -> Optional[Dict[str, float]]:
    """Carga los promedios normalizados por minuto si hay al menos 5 muestras históricas."""
    history_file = os.path.join(base_output_dir, ".stats", "stage_history.json")
    if not os.path.isfile(history_file):
        return None
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            entries = json.load(f)
        if not isinstance(entries, list) or len(entries) < 5:
            return None

        # Calcular promedio por etapa
        totals = {}
        counts = {}
        for entry in entries:
            durations = entry.get("normalized_durations", {})
            for st, norm_dur in durations.items():
                totals[st] = totals.get(st, 0.0) + norm_dur
                counts[st] = counts.get(st, 0) + 1

        averages = {}
        for st, tot in totals.items():
            if counts.get(st, 0) >= 3:
                averages[st] = tot / counts[st]
        return averages if averages else None
    except Exception:
        return None


def mark_stage_failed(
    job_dir: str,
    stage_name: Optional[str] = None,
    error: Optional[str] = None
) -> Dict[str, Any]:
    """Marca la etapa indicada (o la etapa activa si no se especifica) como 'failed'
    en stages.json con el mensaje de error correspondiente.
    """
    data = read_stages(job_dir) or init_stages(job_dir)
    target_stage = stage_name or data.get("current_stage")

    if not target_stage or target_stage == "complete":
        for sname, sinfo in data.get("stages", {}).items():
            if sinfo.get("status") == "running":
                target_stage = sname
                break

    if not target_stage:
        for sname in reversed(list(data.get("stages", {}).keys())):
            if data.get("stages", {}).get(sname, {}).get("started_at"):
                target_stage = sname
                break

    if not target_stage:
        target_stage = "download"

    return finish_stage(job_dir, target_stage, error=error or "Stage execution failed")


def infer_stages_from_disk(job_dir: str, job_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Reconstruye o infiere el estado de las etapas a partir de los artefactos
    existentes en disco si stages.json no existe o está incompleto.
    """
    existing = read_stages(job_dir)
    if existing and existing.get("stages"):
        return existing

    job_id = job_id or os.path.basename(job_dir)
    data = init_stages(job_dir, job_id)
    stages = data["stages"]

    # 1. Comprobar fuente original
    has_source = any(
        f.endswith((".mp4", ".mov", ".mkv", ".webm")) and not f.startswith("temp_") and "_clip_" not in f
        for f in os.listdir(job_dir)
    ) if os.path.isdir(job_dir) else False

    if has_source:
        stages["download"]["status"] = "completed"

    # 2. Comprobar transcripción
    transcript_checkpoint = os.path.join(job_dir, ".transcript_checkpoint.json")
    has_transcript = os.path.isfile(transcript_checkpoint)
    meta_files = glob.glob(os.path.join(job_dir, "*_metadata.json"))
    meta_has_transcript = False
    if meta_files:
        try:
            with open(meta_files[0], "r", encoding="utf-8") as f:
                mdata = json.load(f)
                if mdata.get("transcript", {}).get("segments"):
                    meta_has_transcript = True
        except Exception:
            pass

    if has_transcript or meta_has_transcript:
        stages["download"]["status"] = "completed"
        stages["transcription"]["status"] = "completed"

    # 3. Comprobar selección de momentos (metadata.json con shorts)
    has_shorts = False
    if meta_files:
        try:
            with open(meta_files[0], "r", encoding="utf-8") as f:
                mdata = json.load(f)
                if mdata.get("shorts"):
                    has_shorts = True
        except Exception:
            pass

    if has_shorts:
        stages["clip_selection"]["status"] = "completed"

    # 4. Comprobar clips renderizados
    clips = glob.glob(os.path.join(job_dir, "*_clip_*.mp4"))
    clean_clips = [c for c in clips if not os.path.basename(c).startswith("temp_")]
    if clean_clips:
        stages["cut_and_reframe"]["status"] = "completed"

    # 5. Comprobar subtítulos / hooks
    subtitled = glob.glob(os.path.join(job_dir, "subtitled_*_*.mp4"))
    if subtitled:
        stages["subtitles"]["status"] = "completed"
    hooked = glob.glob(os.path.join(job_dir, "hooked_*_*.mp4"))
    if hooked:
        stages["hooks"]["status"] = "completed"

    if clean_clips and has_shorts:
        data["status"] = "completed"
    elif has_source or has_transcript or has_shorts:
        data["status"] = "interrupted"

    _save_stages(job_dir, data)
    return data


def can_retry_job(
    job_id: str,
    output_dir: str,
    upload_dir: str
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Verifica si un trabajo puede reintentarse desde su última etapa válida.
    Retorna (can_retry, reason, stage_info).
    """
    from project_manager import locate_source_file
    if not job_id or ".." in job_id.replace("\\", "/").split("/") or "/" in job_id or "\\" in job_id:
        return False, "Identificador de trabajo con traversal o inválido", {}

    job_dir = os.path.join(output_dir, job_id)
    if not os.path.isdir(job_dir):
        return False, "Project directory not found", {}

    stages_data = infer_stages_from_disk(job_dir, job_id)
    stages = stages_data.get("stages", {})

    # Para poder reintentar necesitamos al menos que exista o pueda recuperarse la fuente
    # o un transcript válido
    source_path, _ = locate_source_file(job_id, output_dir, upload_dir)
    has_source = bool(source_path and os.path.isfile(source_path))

    has_transcript = os.path.isfile(os.path.join(job_dir, ".transcript_checkpoint.json"))
    has_meta = bool(glob.glob(os.path.join(job_dir, "*_metadata.json")))

    if not has_source and not has_transcript and not has_meta:
        return False, "No source video or valid intermediate artifacts found to retry", stages_data

    return True, "Job can be resumed from intermediate artifacts", stages_data


def build_retry_command(
    job_id: str,
    output_dir: str,
    upload_dir: str,
    base_cmd: Optional[List[str]] = None
) -> List[str]:
    """
    Construye la línea de comandos optimizada para reintentar el trabajo
    reutilizando artefactos válidos (evita re-descargar o re-transcribir).
    Restaura opciones originales guardadas en job_options.json (sin secretos).
    """
    import sys
    from project_manager import locate_source_file
    if not job_id or ".." in job_id.replace("\\", "/").split("/") or "/" in job_id or "\\" in job_id:
        raise ValueError(f"Identificador de trabajo con traversal o inválido: {job_id}")

    job_dir = os.path.join(output_dir, job_id)
    source_path, _ = locate_source_file(job_id, output_dir, upload_dir)

    cmd = [sys.executable, "-u", "main.py"]

    # 1. Reusar fuente local existente
    if source_path and os.path.isfile(source_path):
        cmd.extend(["-i", source_path])
    elif base_cmd:
        # Reusar URL del comando original
        for i, arg in enumerate(base_cmd):
            if arg in ("-u", "--url") and i + 1 < len(base_cmd):
                cmd.extend(["-u", base_cmd[i + 1]])
                break
            elif arg in ("-i", "--input") and i + 1 < len(base_cmd):
                cmd.extend(["-i", base_cmd[i + 1]])
                break

    # 2. Reusar directorio de salida
    cmd.extend(["-o", job_dir])

    # 3. Reusar transcript precomputado si existe
    transcript_checkpoint = os.path.join(job_dir, ".transcript_checkpoint.json")
    if os.path.isfile(transcript_checkpoint):
        try:
            with open(transcript_checkpoint, "r", encoding="utf-8") as f:
                tdata = json.load(f)
            t_content = tdata.get("transcript")
            if t_content and t_content.get("segments"):
                precomputed_path = os.path.join(job_dir, "precomputed_transcript.json")
                with open(precomputed_path, "w", encoding="utf-8") as f:
                    json.dump(t_content, f)
                cmd.extend(["--transcript", precomputed_path])
        except Exception:
            pass

    # 4. Cargar opciones persistidas en job_options.json
    options_file = os.path.join(job_dir, "job_options.json")
    saved_options = {}
    if os.path.isfile(options_file):
        try:
            with open(options_file, "r", encoding="utf-8") as f:
                saved_options = json.load(f)
        except Exception:
            pass

    # 5. Conservar parámetros adicionales del comando base o de job_options.json
    if base_cmd:
        for i, arg in enumerate(base_cmd):
            if arg in ("--format",) and i + 1 < len(base_cmd):
                cmd.extend([arg, base_cmd[i + 1]])
            elif arg in ("--keep-original", "--skip-analysis"):
                if arg not in cmd:
                    cmd.append(arg)

    if saved_options.get("format") and "--format" not in cmd and saved_options["format"] != "auto":
        cmd.extend(["--format", saved_options["format"]])
    if saved_options.get("keep_original") and "--keep-original" not in cmd:
        cmd.append("--keep-original")
    if saved_options.get("skip_analysis") and "--skip-analysis" not in cmd:
        cmd.append("--skip-analysis")

    return cmd

