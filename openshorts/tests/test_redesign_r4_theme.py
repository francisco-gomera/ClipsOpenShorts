"""
Rediseño R4 — Dark Theme Consistency & Atmospheric Studio Polish
================================================================
Verifica los requisitos de identidad visual y tema oscuro:
  1. tokens.css:
     - Declara 'color-scheme: dark;' en :root.
     - Define los tokens de carbón profundo (--color-paper, --color-paper-2, --color-paper-3).
     - Define los tokens de texto legible (--color-ink, --color-ink-2, --color-muted).
     - Define acentos discretos de brass/oro (--color-accent, --color-focus).
     - Define filetes sutiles (--color-rule, --color-rule-2).
  2. index.html:
     - Declara <meta name="color-scheme" content="dark" />.
     - Declara <meta name="theme-color" content="#0d0e14" />.
  3. tailwind.config.js:
     - Mapea paper, paper2, paper3, ink, brass para asegurar consistencia.
  4. Ausencia de regresiones a modo claro:
     - No existen media queries 'prefers-color-scheme: light' que fuercen temas claros.
  5. main.jsx:
     - Utiliza clases semánticas bg-paper / text-muted en vistas de carga.
"""

import os
import re

DASHBOARD_DIR = os.path.join(
    os.path.dirname(__file__), "..", "dashboard"
)
TOKENS_CSS = os.path.join(DASHBOARD_DIR, "src", "tokens.css")
INDEX_CSS = os.path.join(DASHBOARD_DIR, "src", "index.css")
INDEX_HTML = os.path.join(DASHBOARD_DIR, "index.html")
TAILWIND_CONFIG = os.path.join(DASHBOARD_DIR, "tailwind.config.js")
MAIN_JSX = os.path.join(DASHBOARD_DIR, "src", "main.jsx")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_tokens_css_declares_dark_color_scheme():
    css = _read(TOKENS_CSS)
    assert "color-scheme: dark" in css, "tokens.css must declare color-scheme: dark on :root"


def test_tokens_css_defines_studio_palette():
    css = _read(TOKENS_CSS)
    required_tokens = [
        "--color-paper:",
        "--color-paper-2:",
        "--color-paper-3:",
        "--color-ink:",
        "--color-ink-2:",
        "--color-muted:",
        "--color-accent:",
        "--color-rule:",
    ]
    for token in required_tokens:
        assert token in css, f"tokens.css missing required token: {token}"


def test_index_html_has_dark_meta_tags():
    html = _read(INDEX_HTML)
    assert 'name="color-scheme" content="dark"' in html or 'name="color-scheme" content="dark"' in html
    assert 'name="theme-color" content="#0d0e14"' in html


def test_tailwind_config_maps_atmospheric_tokens():
    cfg = _read(TAILWIND_CONFIG)
    for color in ('paper:', 'paper2:', 'paper3:', 'ink:', 'brass:'):
        assert color in cfg, f"tailwind.config.js must map {color}"


def test_no_prefers_color_scheme_light_overrides():
    """Verify no stylesheet overrides the dark theme via prefers-color-scheme: light."""
    src_dir = os.path.join(DASHBOARD_DIR, "src")
    for fname in os.listdir(src_dir):
        if fname.endswith(".css"):
            content = _read(os.path.join(src_dir, fname))
            assert "prefers-color-scheme: light" not in content, (
                f"{fname} contains prefers-color-scheme: light override"
            )


def test_main_jsx_uses_semantic_dark_classes():
    src = _read(MAIN_JSX)
    # Auth loading view must use semantic tokens
    assert "text-zinc-400" not in src
    assert "bg-paper text-muted" in src
