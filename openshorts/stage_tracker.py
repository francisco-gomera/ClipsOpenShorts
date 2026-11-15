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


def _stages_file(job_dir: str) -> str:
    return os.path.join(job_dir, "stages.json")


def init_stages(job_dir: str, job_id: Optional[str] = None) -> Dict[str, Any]:
    """Inicializa la estructura de stages.json para un nuevo job."""
    os.makedirs(job_dir, exist_ok=True)
    stages = {}
    for st in STAGES_ORDER:
        stages[st] = {
            "name": st,
            "label": STAGE_LABELS.get(st, st),
            "status": "pending",  # pending, running, completed, failed, skipped
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "error": None,
        }
    data = {
        "job_id": job_id or os.path.basename(job_dir),
        "status": "queued",
        "current_stage": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "stages": stages,
    }
    _save_stages(job_dir, data)
    return data


def read_stages(job_dir: str) -> Optional[Dict[str, Any]]:
    """Lee stages.json del directorio del trabajo."""
    path = _stages_file(job_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Error leyendo stages.json en {job_dir}: {e}")
        return None


def _save_stages(job_dir: str, data: Dict[str, Any]):
    """Guarda de forma atómica stages.json."""
    os.makedirs(job_dir, exist_ok=True)
    path = _stages_file(job_dir)
    temp_path = f"{path}.tmp.{os.getpid()}"
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


def start_stage(job_dir: str, stage_name: str) -> Dict[str, Any]:
    """Marca una etapa como 'running'."""
    data = read_stages(job_dir) or init_stages(job_dir)
    data["status"] = "processing"
    data["current_stage"] = stage_name
    stage_info = data.get("stages", {}).setdefault(stage_name, {
        "name": stage_name,
        "label": STAGE_LABELS.get(stage_name, stage_name),
    })
    stage_info["status"] = "running"
    stage_info["started_at"] = time.time()
    stage_info["error"] = None
    _save_stages(job_dir, data)
    return data


def finish_stage(
    job_dir: str,
    stage_name: str,
    error: Optional[str] = None,
    skip: bool = False
) -> Dict[str, Any]:
    """Marca una etapa como 'completed', 'failed' o 'skipped'."""
    data = read_stages(job_dir) or init_stages(job_dir)
    stage_info = data.get("stages", {}).setdefault(stage_name, {
        "name": stage_name,
        "label": STAGE_LABELS.get(stage_name, stage_name),
    })
    now = time.time()
    if error:
        stage_info["status"] = "failed"
        stage_info["error"] = str(error)
        data["status"] = "failed"
        data["error"] = str(error)
    elif skip:
        stage_info["status"] = "skipped"
    else:
        stage_info["status"] = "completed"
        stage_info["error"] = None

    stage_info["completed_at"] = now
    if stage_info.get("started_at"):
        stage_info["duration_seconds"] = round(now - stage_info["started_at"], 2)

    _save_stages(job_dir, data)
    return data


def complete_job(job_dir: str) -> Dict[str, Any]:
    """Marca el trabajo completo en stages.json."""
    data = read_stages(job_dir) or init_stages(job_dir)
    data["status"] = "completed"
    data["current_stage"] = "complete"
    _save_stages(job_dir, data)
    return data


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
    job_dir = os.path.join(output_dir, job_id)
    if not os.path.isdir(job_dir):
        return False, "Project directory not found", {}

    stages_data = infer_stages_from_disk(job_dir, job_id)
    stages = stages_data.get("stages", {})

    # Para poder reintentar necesitamos al menos que exista o pueda recuperarse la fuente
    # o un transcript válido
    from project_manager import locate_source_file
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
    """
    import sys
    from project_manager import locate_source_file

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

    # 4. Conservar parámetros adicionales del comando base (format, etc.)
    if base_cmd:
        for i, arg in enumerate(base_cmd):
            if arg in ("--format",) and i + 1 < len(base_cmd):
                cmd.extend([arg, base_cmd[i + 1]])
            elif arg in ("--keep-original",):
                cmd.append(arg)

    return cmd
