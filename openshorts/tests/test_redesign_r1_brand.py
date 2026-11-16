"""
Rediseño R1 — Brand Hygiene
============================
Verifica que ningún componente del dashboard expone 'OpenShorts' como
texto de marca hardcoded visible al usuario (labels, títulos, botones,
nombres de archivo, links de email/github).

Regla: 'OpenShorts' está permitido SOLO en:
  - Identificadores técnicos internos (SESSION_KEY, UPLOAD_DIR, etc.)
  - URLs de dominios externos (openshorts.app, github.com/mutonby/openshorts)
  - Comentarios de código (// o /* ... */)
  - brand.config.js (que lo usa como BRAND_PLACEHOLDER en posición de fallback)
  - Landing.jsx (página de marketing, fuera del flujo del dashboard)
"""

import os
import re

DASHBOARD_SRC = os.path.join(
    os.path.dirname(__file__), "..", "dashboard", "src"
)
INDEX_HTML = os.path.join(
    os.path.dirname(__file__), "..", "dashboard", "index.html"
)
MAIN_JSX = os.path.join(DASHBOARD_SRC, "main.jsx")
APP_JSX = os.path.join(DASHBOARD_SRC, "App.jsx")
BRAND_CONFIG = os.path.join(DASHBOARD_SRC, "brand.config.js")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_comments(src: str) -> str:
    """Remove // line comments and /* block */ comments from JS/JSX source."""
    # Block comments
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.DOTALL)
    # Line comments
    src = re.sub(r'//[^\n]*', '', src)
    return src


def _strip_html_comments(html: str) -> str:
    return re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)


def _jsx_string_literals_containing(src: str, pattern: str) -> list[str]:
    """Return JSX/JS string literals (quoted) that contain pattern."""
    # Match single-quoted, double-quoted, and template literal content
    hits = []
    for m in re.finditer(
        r'''(?:['"`])([^'"`]*''' + re.escape(pattern) + r'''[^'"`]*)(?:['"`])''',
        src
    ):
        hits.append(m.group(1))
    # Also match JSX text nodes (between > and <)
    for m in re.finditer(r'>([^<>]*' + re.escape(pattern) + r'[^<>]*)<', src):
        hits.append(m.group(1).strip())
    return [h for h in hits if h.strip()]


INTERNAL_TECHNICAL_PATTERNS = [
    r'openshorts_session',       # localStorage key
    r'uploadPostKey_v3',         # localStorage key
    r'openshorts\.app',          # domain — not a brand label
    r'mutonby/openshorts',       # github repo path
    r'logo-openshorts\.png',     # asset filename
    r'aitoolnet\.com/openshorts', # external backlink
    r'creatorstoolbox\.com',      # external backlink
    r'ANALYTICS_HOSTS',           # JS variable name
    r'/openshorts',               # URL path segment
    r'Open-source',               # description, not brand name
    r'BRAND_PLACEHOLDER',         # brand.config.js internal
]


def _is_technical(text: str) -> bool:
    """True if the text matches a known technical/internal pattern."""
    for pat in INTERNAL_TECHNICAL_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


# ---------------------------------------------------------------------------
# 1. main.jsx — PageShell header uses brandConfig, not hardcoded "OpenShorts"
# ---------------------------------------------------------------------------

def test_main_jsx_page_shell_uses_brand_config():
    src = _read(MAIN_JSX)
    code = _strip_comments(src)
    # Must import brandConfig
    assert 'brandConfig' in code, "main.jsx must import brandConfig"
    # PageShell header must NOT contain hardcoded 'OpenShorts' text
    # Find the PageShell function body
    shell_match = re.search(
        r'function PageShell\b.*?\n\}',
        code, re.DOTALL
    )
    assert shell_match, "PageShell function not found in main.jsx"
    shell_body = shell_match.group(0)
    # No hardcoded string literal "OpenShorts" inside JSX text nodes
    hits = _jsx_string_literals_containing(shell_body, 'OpenShorts')
    non_technical = [h for h in hits if not _is_technical(h)]
    assert not non_technical, (
        f"PageShell still has hardcoded OpenShorts text: {non_technical}"
    )


def test_main_jsx_deleted_view_uses_brand_config():
    src = _read(MAIN_JSX)
    code = _strip_comments(src)
    deleted_match = re.search(
        r'function DeletedView\b.*?\n\}',
        code, re.DOTALL
    )
    assert deleted_match, "DeletedView function not found in main.jsx"
    body = deleted_match.group(0)
    hits = _jsx_string_literals_containing(body, 'openshorts.app')
    assert not hits, (
        f"DeletedView still has hardcoded openshorts.app text: {hits}"
    )


# ---------------------------------------------------------------------------
# 2. App.jsx — download filename and footer links use brandConfig
# ---------------------------------------------------------------------------

def test_app_jsx_download_zip_no_openshorts_prefix():
    src = _read(APP_JSX)
    code = _strip_comments(src)
    # download attribute must not start with openshorts_clips
    assert 'openshorts_clips_' not in code, (
        "App.jsx download filename still uses openshorts_clips_ prefix"
    )


def test_app_jsx_footer_github_uses_brand_config():
    src = _read(APP_JSX)
    code = _strip_comments(src)
    # Footer github link must use brandConfig.githubUrl, not hardcoded URL
    assert 'brandConfig.githubUrl' in code, (
        "App.jsx footer github link must use brandConfig.githubUrl"
    )


def test_app_jsx_footer_email_uses_brand_config():
    src = _read(APP_JSX)
    code = _strip_comments(src)
    assert 'brandConfig.supportEmail' in code, (
        "App.jsx footer email must use brandConfig.supportEmail"
    )
    # Must NOT have hardcoded info@openshorts.app as an href value
    assert 'href="mailto:info@openshorts.app"' not in code, (
        "App.jsx still has hardcoded mailto:info@openshorts.app href"
    )


# ---------------------------------------------------------------------------
# 3. index.html — public meta tags use %VITE_BRAND_NAME%, not hardcoded brand
# ---------------------------------------------------------------------------

def test_index_html_title_uses_vite_brand_name():
    html = _read(INDEX_HTML)
    html_no_comments = _strip_html_comments(html)
    # <title> must contain the Vite env placeholder, not hardcoded OpenShorts
    title_m = re.search(r'<title>(.*?)</title>', html_no_comments)
    assert title_m, "<title> tag not found in index.html"
    title = title_m.group(1)
    assert '%VITE_BRAND_NAME%' in title, (
        f"<title> must use %VITE_BRAND_NAME%, got: {title!r}"
    )
    assert 'OpenShorts' not in title, (
        f"<title> must not contain hardcoded OpenShorts, got: {title!r}"
    )


def test_index_html_og_title_uses_vite_brand_name():
    html = _read(INDEX_HTML)
    html_no_comments = _strip_html_comments(html)
    og_title_m = re.search(
        r'<meta\s+property="og:title"\s+content="([^"]+)"', html_no_comments
    )
    assert og_title_m, "og:title meta not found in index.html"
    og_title = og_title_m.group(1)
    assert '%VITE_BRAND_NAME%' in og_title, (
        f"og:title must use %VITE_BRAND_NAME%, got: {og_title!r}"
    )


def test_index_html_og_site_name_uses_vite_brand_name():
    html = _read(INDEX_HTML)
    og_m = re.search(
        r'property="og:site_name"\s+content="([^"]+)"', html
    )
    assert og_m, "og:site_name not found in index.html"
    assert '%VITE_BRAND_NAME%' in og_m.group(1), (
        "og:site_name must use %VITE_BRAND_NAME%"
    )


def test_index_html_twitter_title_uses_vite_brand_name():
    html = _read(INDEX_HTML)
    tw_m = re.search(
        r'name="twitter:title"\s+content="([^"]+)"', html
    )
    assert tw_m, "twitter:title not found in index.html"
    assert '%VITE_BRAND_NAME%' in tw_m.group(1), (
        "twitter:title must use %VITE_BRAND_NAME%"
    )


def test_index_html_meta_author_uses_vite_brand_name():
    html = _read(INDEX_HTML)
    auth_m = re.search(r'name="author"\s+content="([^"]+)"', html)
    assert auth_m, "meta author not found in index.html"
    assert '%VITE_BRAND_NAME%' in auth_m.group(1), (
        "meta author must use %VITE_BRAND_NAME%"
    )


def test_index_html_no_openshorts_in_visible_meta():
    """Verifies that visible meta tags (title, og:title, twitter:title,
    og:site_name, meta author) contain no hardcoded 'OpenShorts'."""
    html = _strip_html_comments(_read(INDEX_HTML))
    # Collect all meta content values and the title
    visible_meta_patterns = [
        r'<title>(.*?)</title>',
        r'property="og:title"\s+content="([^"]+)"',
        r'property="og:site_name"\s+content="([^"]+)"',
        r'name="twitter:title"\s+content="([^"]+)"',
        r'name="author"\s+content="([^"]+)"',
    ]
    for pat in visible_meta_patterns:
        m = re.search(pat, html)
        if m:
            assert 'OpenShorts' not in m.group(1), (
                f"Hardcoded OpenShorts found in meta: {m.group(1)!r}"
            )


# ---------------------------------------------------------------------------
# 4. brand.config.js — still intact (regression guard)
# ---------------------------------------------------------------------------

def test_brand_config_still_has_all_required_fields():
    src = _read(BRAND_CONFIG)
    for field in ('name', 'supportEmail', 'githubUrl', 'logo', 'tagline'):
        assert field in src, f"brand.config.js missing field: {field}"
    assert 'VITE_BRAND_NAME' in src
    assert 'ClipsOpenShorts' in src   # BRAND_PLACEHOLDER still present


# ---------------------------------------------------------------------------
# 5. No new hardcoded "OpenShorts" text introduced in App.jsx visible labels
# ---------------------------------------------------------------------------

def test_app_jsx_no_new_openshorts_text_labels():
    """Scan App.jsx JSX text nodes for hardcoded OpenShorts that are not
    technical internal identifiers."""
    src = _read(APP_JSX)
    code = _strip_comments(src)
    # Find all JSX text node hits
    hits = []
    for m in re.finditer(r'>([^<>]+OpenShorts[^<>]*)<', code):
        text = m.group(1).strip()
        if not _is_technical(text):
            hits.append(text)
    assert not hits, (
        f"App.jsx still has hardcoded OpenShorts in JSX text nodes: {hits}"
    )
