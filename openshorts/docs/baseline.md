# Línea Base y Auditoría Inicial (Fase 0) — OpenShorts

**Fecha:** 15 de noviembre de 2026  
**Rama:** `fase-0-auditoria`  
**Etiqueta:** `baseline-2026-11-15`  
**Commit base:** `5d6dd3a` (feat: agregar codigo de openshorts)  
**Entorno de ejecución:** Docker Desktop en Windows (Host: Windows 11, GPU AMD / CPU principal sin aceleración NVIDIA).

---

## 1. Resumen de la Línea Base

Este documento establece las mediciones exactas y reproducibles de la plataforma antes de introducir cambios de comportamiento o refactorizaciones arquitectónicas. Servirá como referencia estricta para contrastar los resultados de rendimiento, fidelidad visual y estabilidad en las Fases 1 a 9.

---

## 2. Limpieza del Repositorio y Configuración de Git

1. **Etiqueta creada:** `baseline-2026-11-15` en el commit inicial `5d6dd3a`.
2. **Archivos `.bak` eliminados del rastreo y del disco:**
   - `openshorts/app.py.bak`
   - `openshorts/clip_selection.py.bak`
   - `openshorts/dashboard/src/components/ClipEditor.jsx.bak`
   - `openshorts/dashboard/src/components/MediaInput.jsx.bak`
   - `openshorts/mcp_server.py.bak`
   - `openshorts/recut.py.bak`
3. **Regla añadida a `.gitignore` (raíz y `openshorts/`):**
   ```gitignore
   # Backup files
   *.bak
   ```
4. **Commit de limpieza:** `1295637` (*chore: eliminar archivos .bak rastreados e ignorar *.bak*).

---

## 3. Resultados de Pruebas Automatizadas y CI

### 3.1. Suite de Pruebas de Backend (`pytest`)

- **Comando exacto:**
  ```bash
  docker exec openshorts-backend /opt/venv/bin/pytest tests/ -v
  ```
- **Plataforma:** Linux / Python 3.11.18 en contenedor Docker `openshorts-backend`.
- **Resultado:**
  - Total ítems recolectados: **1609**
  - **Pruebas superadas:** **1599 PASSED** (100% de las pruebas activas)
  - **Pruebas omitidas:** **10 SKIPPED** (pruebas condicionales a GPU/NVENC o R2 cloud)
  - **Fallos / Errores:** **0 FAILED / 0 ERRORS**
  - **Tiempo de ejecución:** **254.62s (4 min 14s)**

### 3.2. Compilación del Frontend (`npm run build`)

- **Comando exacto:**
  ```bash
  docker exec openshorts-frontend npm run build
  ```
- **Resultado:** **Éxito total en 27.63s**. Genera los bundles optimizados en `dashboard/dist/` (1611 módulos transformados).

### 3.3. Análisis Estático del Frontend (`npm run lint`)

- **Comando exacto:**
  ```bash
  docker exec openshorts-frontend npm run lint
  ```
- **Resultado:** **10 problemas preexistentes** (coinciden exactamente con los 10 avisos de la línea base documentada en `docs/implementation-audit.md`):
  1. `/app/public/op1.js:1:3536` — `no-unused-vars` ('e')
  2. `/app/public/op1.js:1:6148` — `no-unreachable`
  3. `/app/public/op1.js:1:6762` — `no-empty`
  4. `/app/public/op1.js:1:8372` — `no-empty`
  5. `/app/public/op1.js:1:8565` — `no-empty`
  6. `/app/src/Legal.jsx:84:40` — `no-unused-vars` ('Icon')
  7. `/app/src/components/PricingPage.jsx:217:42` — `no-unused-vars` ('Icon')
  8. `/app/src/lib/consent.js:55:71` — `no-empty`
  9. `/app/src/lib/consent.js:60:78` — `no-empty`
  10. `/app/src/lib/consent.js:114:9` — `no-unused-vars` ('before')

---

## 4. Conjunto de Referencia (Dataset de 3 Vídeos)

Se seleccionaron y descargaron 3 vídeos representativos bajo licencias públicas (Dominio Público del Gobierno de EE. UU. / Creative Commons Attribution 3.0), ubicados en `docs/reference_dataset/videos/`:

| ID | Nombre | Descripción | Fuente / Licencia | Duración | Tamaño |
|---|---|---|---|---|---|
| **V1** | `single_speaker.mp4` | Monólogo / una sola persona hablando a cámara | White House Weekly Address (Dominio Público) | 3m 48.9s (228.9s) | 39.1 MB |
| **V2** | `two_speaker_podcast.mp4` | Conversación / podcast de 2 personas (Marc Maron y Barack Obama) | White House WTF Podcast (Dominio Público) | 3m 45.0s (225.0s) | 19.4 MB |
| **V3** | `speechless_video.mp4` | Vídeo sin voz (animación y música) | Big Buck Bunny (Blender Foundation, CC-BY 3.0) | 2m 42.2s (162.2s) | 32.9 MB |

---

## 5. Tiempos Reales por Etapa en CPU

### 5.1. Transcripción ASR (Faster-Whisper `small`, int8, CPU)

- **Script de medición:** `scripts/benchmark/benchmark_asr.py`
- **Comando exacto:**
  ```bash
  docker exec openshorts-backend /opt/venv/bin/python scripts/benchmark/benchmark_asr.py
  ```
- **Resultados:**

| Vídeo | Duración del Vídeo | Tiempo ASR en CPU | Palabras | Segmentos | Idioma | Ratio de Velocidad (xRT) |
|---|---|---|---|---|---|---|
| **V1: Persona Única** | 228.9s | **61.60s** | 587 | 60 | `en` | **3.71x** tiempo real |
| **V2: Podcast 2 Hablantes**| 225.0s | **57.87s** | 674 | 45 | `en` | **3.89x** tiempo real |
| **V3: Sin Voz (VAD/Música)**| 162.2s | **7.61s** | 1 | 1 | `en` | **21.3x** tiempo real |

> **Checkpoints deterministas guardados:**
> - `docs/reference_dataset/single_speaker_transcript.json`
> - `docs/reference_dataset/two_speaker_transcript.json`
> - `docs/reference_dataset/speechless_transcript.json`

### 5.2. Pipeline de Renderizado y Edición en CPU (Clip de 30s)

- **Script de medición:** `scripts/benchmark/benchmark_render.py`
- **Vídeo base:** `single_speaker.mp4` (rango $t=10.0\text{s}$ a $t=40.0\text{s}$, 30 segundos)
- **Comando exacto:**
  ```bash
  docker exec openshorts-backend /opt/venv/bin/python scripts/benchmark/benchmark_render.py
  ```
- **Desglose de tiempos por subetapa en CPU:**

| Subetapa | Operación | Motor / Códec | Tiempo en CPU |
|---|---|---|---|
| **1. Corte** | `cut_clip` | FFmpeg / libx264 | **10.52s** |
| **2. Reencuadre 9:16** | `render_clip` (vertical 1080x1920) | `reframe_v2` / TransNetV2 | **77.47s** |
| **3. Subtítulos** | `auto_caption_clip` | FFmpeg / `libass` / libx264 | **32.48s** |
| **Total Renderizado** | Pipeline completo para 30s | CPU x264 CRF 18 | **120.46s (2m 0.46s)** |

---

## 6. Línea Base Visual (SSIM de Referencia)

Para garantizar que futuras optimizaciones de velocidad o paralelismo no degraden la calidad visual (`SSIM \ge 0.99` exigido en el criterio de aceptación de la Fase 9), se extrajeron 5 fotogramas clave a resolución nativa 1080x1920 en `docs/reference_dataset/frames/`:

1. `frame_05s.png` (segundo 5 del clip vertical con subtítulos quemados)
2. `frame_10s.png` (segundo 10 del clip vertical)
3. `frame_15s.png` (segundo 15 del clip vertical)
4. `frame_20s.png` (segundo 20 del clip vertical)
5. `frame_25s.png` (segundo 25 del clip vertical)

---

## 7. Estado de la Fase 0

- [x] Etiqueta `baseline-2026-11-15` creada en `5d6dd3a`.
- [x] Rama `fase-0-auditoria` activa.
- [x] 6 archivos `.bak` eliminados e ignorados en `.gitignore`.
- [x] `pytest tests/ -v` verificado (1599 pass, 0 fail).
- [x] `npm run build` verificado (éxito en 27.63s).
- [x] `npm run lint` verificado (10 avisos preexistentes registrados).
- [x] Conjunto de 3 vídeos de referencia creado y almacenado.
- [x] Checkpoints deterministas de transcripción generados y almacenados.
- [x] Tiempos reales por etapa en CPU medidos y tabulados.
- [x] Fotogramas de referencia SSIM extraídos.
- [x] Criterio de aceptación satisfecho con `docs/baseline.md`.
