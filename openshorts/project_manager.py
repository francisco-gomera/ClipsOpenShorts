
"""
project_manager.py - Gestión, persistencia y recuperación de proyectos para OpenShorts.

Soporta el ciclo de vida completo de proyectos en modo autoalojado (Self-Host)
y garantiza la reconciliación idempotente entre el disco (output/, uploads/)
y el estado en memoria de FastAPI.
"""

import os
import glob
import json
import time
import shutil
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple


# Regex para identificar job_ids válidos (UUIDv4)
_JOB_ID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


def is_valid_job_id(job_id: str) -> bool:
    """Verifica si la cadena tiene formato de identificador UUIDv4."""
    if not isinstance(job_id, str):
        return False
    return bool(_JOB_ID_RE.match(job_id))


def validate_job_id(job_id: str, base_dir: Optional[str] = None) -> str:
    """Valida estrictamente que job_id sea un UUIDv4 válido y que,
    si se proporciona base_dir, la ruta resuelta con realpath resida estrictamente
    dentro de base_dir, previniendo Directory Traversal.
    Lanza ValueError si es inválido.
    """
    if not is_valid_job_id(job_id):
        raise ValueError(f"Identificador de trabajo inválido (no es UUIDv4): {job_id}")
    if base_dir:
        real_base = os.path.realpath(base_dir)
        target = os.path.realpath(os.path.join(base_dir, job_id))
        if target != real_base and not target.startswith(real_base + os.sep):
            raise ValueError(f"Intento de Directory Traversal detectado: {job_id}")
    return job_id


def canonical_clip_file(output_dir: str, base_name: str, index: int) -> str:
    """
    Determina el archivo más reciente a servir para el clip `index`.
    Prioriza versiones derivadas (subtituladas, con hook o con marca de agua)
    sobre la versión canónica limpia (`<base>_clip_<n>.mp4`).
    """
    clean = f"{base_name}_clip_{index + 1}.mp4"
    try:
        derived = (
            glob.glob(os.path.join(output_dir, f"subtitled_*_{clean}"))
            + glob.glob(os.path.join(output_dir, f"recut_*_{clean}"))
            + glob.glob(os.path.join(output_dir, f"hooked_*_{clean}"))
            + glob.glob(os.path.join(output_dir, f"hook_{clean}"))
            + glob.glob(os.path.join(output_dir, f"wm_*{clean}"))
        )
    except Exception:
        derived = []
    if not derived:
        return clean
    # La versión con fecha de modificación más reciente gana
    return os.path.basename(max(derived, key=os.path.getmtime))


def locate_source_file(job_id: str, output_dir: str, upload_dir: str) -> Tuple[Optional[str], str]:
    """
    Localiza el vídeo original del proyecto en disco.
    Retorna (ruta_al_archivo, tipo_origen: 'file' | 'url' | 'unknown').
    """
    if not job_id or ".." in job_id.replace("\\", "/").split("/") or "/" in job_id or "\\" in job_id:
        return None, "unknown"
    # 1. Buscar en UPLOAD_DIR (subidas directas del usuario)
    try:
        upload_matches = [
            f for f in glob.glob(os.path.join(upload_dir, f"{glob.escape(job_id)}_*"))
            if not os.path.basename(f).startswith("thumb_")
        ]
        if upload_matches and os.path.exists(upload_matches[0]):
            return upload_matches[0], "file"
    except Exception:
        pass

    # 2. Buscar en el directorio del proyecto (descargas de YouTube con --keep-original)
    job_path = os.path.join(output_dir, job_id)
    if os.path.isdir(job_path):
        try:
            metas = glob.glob(os.path.join(job_path, "*_metadata.json"))
            if metas:
                with open(metas[0], "r", encoding="utf-8") as f:
                    meta_data = json.load(f)
                source_video = meta_data.get("source_video")
                if source_video:
                    candidate = os.path.join(job_path, os.path.basename(source_video))
                    if os.path.exists(candidate):
                        return candidate, "url"
        except Exception:
            pass

        # 3. Comprobar si hay algún archivo de vídeo que no sea un clip generado
        try:
            for fname in os.listdir(job_path):
                if fname.endswith((".mp4", ".mov", ".mkv", ".webm")):
                    if "_clip_" not in fname and not fname.startswith("temp_"):
                        return os.path.join(job_path, fname), "url"
        except Exception:
            pass

    return None, "unknown"


def extract_project_title(job_id: str, meta_data: dict, base_name: str) -> str:
    """Extrae un título legible y representativo para el proyecto."""
    # 1. Título explícito en metadatos
    if meta_data.get("title"):
        return meta_data["title"]
    # 2. Título de YouTube
    if meta_data.get("video_title_for_youtube"):
        return meta_data["video_title_for_youtube"]
    # 3. Título del primer clip
    shorts = meta_data.get("shorts", [])
    if shorts and isinstance(shorts, list):
        first_title = shorts[0].get("video_title_for_youtube_short") or shorts[0].get("title")
        if first_title:
            return first_title
    # 4. Nombre base del archivo original limpiando prefijo de job_id
    clean_base = base_name
    if clean_base.startswith(f"{job_id}_"):
        clean_base = clean_base[len(job_id) + 1:]
    clean_base = clean_base.replace("_", " ").strip()
    return clean_base or f"Project {job_id[:8]}"


def determine_project_status(
    job_id: str,
    job_path: str,
    meta_data: Optional[dict],
    in_memory_status: Optional[str] = None
) -> Tuple[str, Optional[str]]:
    """
    Determina el estado del proyecto contemplando:
    - queued
    - processing
    - completed
    - failed
    - interrupted
    - recoverable
    - partially_recoverable
    """
    # Si en memoria está activamente en cola o en ejecución, respetar ese estado
    if in_memory_status in ("queued", "processing"):
        return in_memory_status, None

    resume_file = os.path.join(job_path, ".resume.json")
    has_resume = os.path.isfile(resume_file)

    # Revisar si hay registro de etapas (stages.json)
    stages_file = os.path.join(job_path, "stages.json")
    if os.path.isfile(stages_file):
        try:
            with open(stages_file, "r", encoding="utf-8") as f:
                stages_data = json.load(f)
            if stages_data.get("status") == "failed":
                return "failed", stages_data.get("error") or "Failed at stage"
        except Exception:
            pass

    if not meta_data:
        # Sin metadatos:
        if has_resume:
            return "interrupted", "El procesamiento se interrumpió antes de completar el análisis inicial."
        # Buscar si existen clips aunque no haya metadata
        clips_found = glob.glob(os.path.join(job_path, "*_clip_*.mp4"))
        if clips_found:
            return "partially_recoverable", None
        return "failed", "Proyecto incompleto o sin metadatos disponibles."

    shorts = meta_data.get("shorts", [])
    if not shorts:
        if has_resume:
            return "interrupted", "Análisis completado pero sin clips generados."
        return "recoverable", None

    # Verificar cuántos clips existen realmente en disco
    base_name = ""
    metas = glob.glob(os.path.join(job_path, "*_metadata.json"))
    if metas:
        base_name = os.path.basename(metas[0]).replace("_metadata.json", "")

    existing_clips_count = 0
    for i, _ in enumerate(shorts):
        clip_name = canonical_clip_file(job_path, base_name, i) if base_name else f"clip_{i+1}.mp4"
        clip_path = os.path.join(job_path, clip_name)
        if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
            existing_clips_count += 1

    if existing_clips_count == len(shorts) and existing_clips_count > 0:
        if has_resume:
            return "interrupted", "Clips renderizados pero el proceso terminó inesperadamente."
        return "completed", None
    elif existing_clips_count > 0:
        return "partially_recoverable", f"{existing_clips_count} de {len(shorts)} clips disponibles."
    else:
        if has_resume:
            return "interrupted", "Interrumpido antes de renderizar clips."
        return "recoverable", "Metadatos y clips planificados, pendientes de renderizar."


def get_project_record(
    job_id: str,
    output_dir: str,
    upload_dir: str,
    in_memory_job: Optional[dict] = None
) -> Optional[dict]:
    """
    Construye la representación completa del modelo de proyecto para un job_id.
    Retorna un diccionario conforme a los requisitos del Plan Maestro.
    """
    if not job_id or ".." in job_id.replace("\\", "/").split("/") or "/" in job_id or "\\" in job_id:
        return None
    real_out = os.path.realpath(output_dir)
    job_path = os.path.realpath(os.path.join(output_dir, job_id))
    if not (job_path == real_out or job_path.startswith(real_out + os.sep)):
        return None
    if not os.path.isdir(job_path) or job_id == "thumbnails":
        return None

    # Leer metadatos si existen
    meta_data = None
    metadata_file_name = None
    base_name = ""
    try:
        metas = glob.glob(os.path.join(job_path, "*_metadata.json"))
        if metas:
            metadata_file_name = os.path.basename(metas[0])
            base_name = metadata_file_name.replace("_metadata.json", "")
            with open(metas[0], "r", encoding="utf-8") as f:
                meta_data = json.load(f)
    except Exception as e:
        print(f"⚠️ Error leyendo metadatos de {job_id}: {e}")

    # Localizar vídeo original
    source_file, source_type = locate_source_file(job_id, output_dir, upload_dir)
    has_source = bool(source_file and os.path.exists(source_file))

    # Determinar estado
    in_mem_status = in_memory_job.get("status") if in_memory_job else None
    status, last_error = determine_project_status(job_id, job_path, meta_data, in_mem_status)

    # Fechas
    try:
        st = os.stat(job_path)
        created_at_dt = datetime.fromtimestamp(st.st_ctime, tz=timezone.utc)
        updated_at_dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        created_at = created_at_dt.isoformat()
        updated_at = updated_at_dt.isoformat()
    except Exception:
        now_iso = datetime.now(timezone.utc).isoformat()
        created_at = now_iso
        updated_at = now_iso

    # Construir lista de clips válidos
    shorts = (meta_data.get("shorts", []) if meta_data else [])
    clips_list = []
    thumbnail_url = None

    for i, clip in enumerate(shorts):
        clip_copy = dict(clip)
        clip_fname = canonical_clip_file(job_path, base_name, i) if base_name else f"clip_{i+1}.mp4"
        clip_full_path = os.path.join(job_path, clip_fname)
        exists = os.path.exists(clip_full_path) and os.path.getsize(clip_full_path) > 0
        clip_copy["available"] = exists
        clip_copy["index"] = i
        if exists:
            video_url = f"/videos/{job_id}/{clip_fname}"
            clip_copy["video_url"] = video_url
            if not thumbnail_url:
                thumbnail_url = video_url
        clips_list.append(clip_copy)

    # Título
    title = extract_project_title(job_id, meta_data or {}, base_name)

    # Duración de la fuente si se conoce
    source_duration = None
    if meta_data and "duration" in meta_data:
        source_duration = meta_data.get("duration")

    return {
        "job_id": job_id,
        "title": title,
        "source_type": source_type,
        "source_url": f"/api/source/{job_id}" if has_source else None,
        "source_file": os.path.basename(source_file) if source_file else None,
        "has_source": has_source,
        "source_duration": source_duration,
        "created_at": created_at,
        "updated_at": updated_at,
        "status": status,
        "metadata_file": metadata_file_name,
        "clip_count": len(clips_list),
        "clips": clips_list,
        "thumbnail_url": thumbnail_url,
        "has_results": any(c.get("available") for c in clips_list),
        "last_error": last_error,
        "archived": False,
    }


def list_projects(output_dir: str, upload_dir: str, jobs_dict: Optional[dict] = None) -> List[dict]:
    """
    Retorna el catálogo completo de proyectos ordenados cronológicamente
    (los más recientes primero). Idempotente y tolerante a fallos.
    """
    projects = []
    if not os.path.isdir(output_dir):
        return projects

    jobs_dict = jobs_dict or {}

    for entry in os.listdir(output_dir):
        job_path = os.path.join(output_dir, entry)
        # Skip non-directories, hidden dirs (e.g. .stats, .ratelimit), and
        # any folder whose name is not a valid UUID job id.
        if not os.path.isdir(job_path):
            continue
        if entry.startswith('.') or not is_valid_job_id(entry):
            continue
        try:
            record = get_project_record(entry, output_dir, upload_dir, jobs_dict.get(entry))
            if record:
                projects.append(record)
        except Exception as e:
            print(f"⚠️ Error reconciliando proyecto {entry}: {e}")

    # Ordenar por updated_at descendente (más recientes primero)
    projects.sort(key=lambda p: p.get("updated_at") or "", reverse=True)
    return projects


def recover_all_projects_to_memory(jobs_dict: dict, output_dir: str, upload_dir: str) -> int:
    """
    Examina OUTPUT_DIR y reconstruye en el diccionario en memoria `jobs_dict`
    todos los proyectos reconocibles para que los endpoints de FastAPI puedan
    operar sobre ellos de inmediato sin volver a procesarlos.
    Retorna la cantidad de proyectos recuperados.
    """
    recovered_count = 0
    if not os.path.isdir(output_dir):
        return 0

    for job_id in os.listdir(output_dir):
        job_path = os.path.join(output_dir, job_id)
        # Skip non-directories, hidden dirs (e.g. .stats, .ratelimit), and
        # any folder whose name is not a valid UUID job id.
        if not os.path.isdir(job_path):
            continue
        if job_id.startswith('.') or not is_valid_job_id(job_id):
            continue

        # No sobrescribir trabajos activamente en cola o en ejecución
        existing = jobs_dict.get(job_id)
        if existing and existing.get("status") in ("queued", "processing"):
            continue

        try:
            record = get_project_record(job_id, output_dir, upload_dir, existing)
            if not record:
                continue

            # Construir resultado con los clips disponibles
            available_clips = [c for c in record["clips"] if c.get("available")]
            
            # Cargar metadatos para cost_analysis y transcript
            cost_analysis = None
            if record.get("metadata_file"):
                meta_path = os.path.join(job_path, record["metadata_file"])
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        m_data = json.load(f)
                    cost_analysis = m_data.get("cost_analysis")
                except Exception:
                    pass

            # Propietario si existe sidecar .owner
            owner = None
            owner_file = os.path.join(job_path, ".owner")
            if os.path.isfile(owner_file):
                try:
                    with open(owner_file, "r") as f:
                        raw = f.read().strip()
                    owner = int(raw) if raw.isdigit() else (raw or None)
                except Exception:
                    pass

            jobs_dict[job_id] = {
                "status": record["status"],
                "logs": [f"♻️ Proyecto recuperado del disco ({record['status']})."],
                "output_dir": job_path,
                "user_id": owner,
                "result": {
                    "clips": available_clips,
                    "cost_analysis": cost_analysis,
                },
                "title": record["title"],
                "project_record": record,
            }
            recovered_count += 1
        except Exception as e:
            print(f"⚠️ No se pudo recuperar el proyecto {job_id}: {e}")

    if recovered_count > 0:
        print(f"♻️  Se recuperaron {recovered_count} proyecto(s) del almacenamiento local.")
    return recovered_count


def delete_project(job_id: str, jobs_dict: dict, output_dir: str, upload_dir: str) -> bool:
    """
    Eliminación explícita y completa de un proyecto y sus artefactos.
    Elimina output/{job_id}, los ficheros de origen asociados en uploads/
    y el registro en memoria.
    """
    validate_job_id(job_id, output_dir)
    validate_job_id(job_id, upload_dir)

    # Si el trabajo está en ejecución, no permitir borrado
    job = jobs_dict.get(job_id)
    if job and job.get("status") in ("queued", "processing"):
        raise RuntimeError("No se puede eliminar un proyecto en procesamiento.")

    success = False
    job_path = os.path.join(output_dir, job_id)
    if os.path.isdir(job_path) and job_id != "thumbnails":
        shutil.rmtree(job_path, ignore_errors=True)
        success = True

    # Eliminar vídeo de origen en uploads/ si existe
    try:
        matches = glob.glob(os.path.join(upload_dir, f"{glob.escape(job_id)}_*"))
        for m in matches:
            if os.path.isfile(m):
                os.remove(m)
    except Exception as e:
        print(f"⚠️ Error eliminando archivos de uploads para {job_id}: {e}")

    # Retirar de memoria
    jobs_dict.pop(job_id, None)
    return success


def clean_project_temp_files(job_id: str, output_dir: str, max_age_seconds: int = 1800) -> int:
    """
    Limpia únicamente los archivos temporales generados durante el procesamiento
    (temp_*.mp4, temp_*.jpg) que hayan superado max_age_seconds, conservando
    intactos los clips canónicos, metadatos, recetas y subtítulos.
    """
    validate_job_id(job_id, output_dir)
    cleaned_count = 0
    job_path = os.path.join(output_dir, job_id)
    if not os.path.isdir(job_path):
        return 0

    now = time.time()
    try:
        for fname in os.listdir(job_path):
            if fname.startswith("temp_"):
                fpath = os.path.join(job_path, fname)
                try:
                    if os.path.isfile(fpath) and (now - os.path.getmtime(fpath) > max_age_seconds):
                        os.remove(fpath)
                        cleaned_count += 1
                except OSError:
                    pass
    except Exception:
        pass
    return cleaned_count
