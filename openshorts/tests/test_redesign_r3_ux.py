"""
Rediseño R3 — UX Simplificada (Action-First)
============================================
Verifica los criterios de experiencia de usuario simplificada:
  1. MediaInput.jsx:
     - Opciones avanzadas colapsadas por defecto (showAdvanced = false).
     - Formato de salida predeterminado a 'vertical' (9:16).
     - Acción principal evidente (Upload File / Video URL).
  2. App.jsx:
     - Eliminación del terminal de logs duplicado en el panel izquierdo
       (ProcessingPanel se encarga de mostrar el progreso real y los logs plegados).
     - Los detalles técnicos y logs permanecen plegados por defecto.
  3. ProcessingPanel / CollapsibleLogs:
     - CollapsibleLogs tiene defaultOpen={false} para no sobrecargar de texto técnico.
  4. StarBanner:
     - Usa brandConfig en lugar de referencias hardcoded a OpenShorts o URLs fijas.
"""

import os
import re

DASHBOARD_SRC = os.path.join(
    os.path.dirname(__file__), "..", "dashboard", "src"
)
MEDIA_INPUT_JSX = os.path.join(DASHBOARD_SRC, "components", "MediaInput.jsx")
APP_JSX = os.path.join(DASHBOARD_SRC, "App.jsx")
STAR_BANNER_JSX = os.path.join(DASHBOARD_SRC, "components", "StarBanner.jsx")
PROCESSING_PANEL_JSX = os.path.join(
    DASHBOARD_SRC, "components", "processing", "ProcessingPanel.jsx"
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_mediainput_advanced_options_collapsed_by_default():
    """Advanced options must be collapsed by default to avoid cognitive overload."""
    src = _read(MEDIA_INPUT_JSX)
    # Must initialize showAdvanced to false
    assert "useState(false)" in src
    # Must have the advanced options disclosure trigger
    assert "showAdvanced" in src
    assert "advanced options" in src.lower()


def test_mediainput_default_output_format_is_vertical():
    """Vertical (9:16) must be the default format for AI shorts creation."""
    src = _read(MEDIA_INPUT_JSX)
    assert "useState('vertical')" in src or 'useState("vertical")' in src


def test_mediainput_has_primary_actions():
    """Primary actions must include Upload File and Video URL."""
    src = _read(MEDIA_INPUT_JSX)
    assert "Upload File" in src
    assert "Video URL" in src
    assert "Generate Clips" in src


def test_app_jsx_no_duplicate_system_logs_terminal():
    """App.jsx must not render a second redundant System Logs terminal in the left panel."""
    src = _read(APP_JSX)
    # The duplicate header "<Terminal size={12} /> System Logs" was removed
    assert "<Terminal size={12} /> System Logs" not in src


def test_processing_panel_logs_collapsed_by_default():
    """ProcessingPanel must render CollapsibleLogs with defaultOpen={false}."""
    src = _read(PROCESSING_PANEL_JSX)
    assert "CollapsibleLogs" in src
    assert "defaultOpen={false}" in src


def test_star_banner_uses_brand_config():
    """StarBanner must use brandConfig instead of hardcoded external branding."""
    src = _read(STAR_BANNER_JSX)
    assert "brandConfig" in src
    assert "brandConfig.githubUrl" in src
    assert "Enjoying OpenShorts" not in src
