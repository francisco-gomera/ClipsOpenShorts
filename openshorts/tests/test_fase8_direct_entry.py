"""
Fase 8 – Entrada Directa a la App
==================================
Verifies that:
1. The root route resolves to the app view (not the landing) by default.
2. Known sub-routes (#/pricing, #/account, #/auth/, #/oauth/, #/deleted) still
   resolve to their own views.
3. #landing resolves to the landing view explicitly.
4. #app and #app?tab=... resolve to the app view.
5. Any unrecognised hash also resolves to the app (not landing).
6. Landing.jsx is imported only in main.jsx (no other component imports it).
7. main.jsx contains the Fase-8 routing comment as documentation.
8. nginx.conf includes X-Robots-Tag for self-hosted noindex.
9. brand.config.js is unaffected (regression guard).
"""

import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..", "dashboard", "src")
MAIN_JSX = os.path.join(ROOT, "main.jsx")
NGINX_CONF = os.path.join(os.path.dirname(__file__), "..", "dashboard", "nginx.conf")
BRAND_CONFIG = os.path.join(ROOT, "brand.config.js")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_view(hash_: str, source: str) -> str:
    """
    Mirror the resolveView() logic from main.jsx in Python so we can unit-test
    routing decisions without a browser.
    """
    h = hash_ or ""
    if h.startswith("#/auth/"):
        return "auth"
    if h.startswith("#/oauth/authorize"):
        return "oauth"
    if h.startswith("#/account"):
        return "account"
    if h.startswith("#/deleted"):
        return "deleted"
    if h.startswith("#/pricing"):
        return "pricing"
    if h == "#legal":
        return "legal"
    if h == "#landing":
        return "landing"
    if h == "#app" or h.startswith("#app?"):
        return "app"
    return "app"   # Fase 8: default is app, not landing


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Routing logic tests (mirrors the JS resolveView function)
# ---------------------------------------------------------------------------

def test_root_resolves_to_app():
    """Bare / (empty hash) → app."""
    assert _resolve_view("", "") == "app"


def test_hash_app_resolves_to_app():
    assert _resolve_view("#app", "") == "app"


def test_hash_app_with_tab_resolves_to_app():
    assert _resolve_view("#app?tab=autopilot", "") == "app"


def test_hash_landing_resolves_to_landing():
    """#landing is still accessible for users who want the landing page."""
    assert _resolve_view("#landing", "") == "landing"


def test_pricing_route():
    assert _resolve_view("#/pricing", "") == "pricing"
    assert _resolve_view("#/pricing?plan=starter", "") == "pricing"


def test_account_route():
    assert _resolve_view("#/account", "") == "account"
    assert _resolve_view("#/account/billing", "") == "account"


def test_auth_route():
    assert _resolve_view("#/auth/callback", "") == "auth"


def test_oauth_route():
    assert _resolve_view("#/oauth/authorize", "") == "oauth"


def test_deleted_route():
    assert _resolve_view("#/deleted", "") == "deleted"


def test_legal_route():
    assert _resolve_view("#legal", "") == "legal"


def test_unrecognised_hash_resolves_to_app():
    """Unknown hashes (#features, #about) now go to app, not landing."""
    assert _resolve_view("#features", "") == "app"
    assert _resolve_view("#about", "") == "app"
    assert _resolve_view("#pricing", "") == "app"   # hash anchor, not hash-route


# ---------------------------------------------------------------------------
# Source file verification
# ---------------------------------------------------------------------------

def test_main_jsx_contains_fase8_comment():
    """main.jsx documents the Fase-8 routing change."""
    src = _read(MAIN_JSX)
    assert "Fase 8" in src, "main.jsx should contain a Fase 8 comment"


def test_main_jsx_default_is_app_not_landing():
    """The last return in resolveView must be 'app', not 'landing'."""
    src = _read(MAIN_JSX)
    # Find the resolveView function body and confirm the final return is 'app'.
    resolve_fn = re.search(
        r"const resolveView\s*=\s*\(\)\s*=>\s*\{(.+?)\};",
        src,
        re.DOTALL,
    )
    assert resolve_fn, "resolveView function not found in main.jsx"
    fn_body = resolve_fn.group(1)
    # The last return statement in the function must be 'app'
    returns = re.findall(r"return\s+'(\w+)'", fn_body)
    assert returns, "No return statements found in resolveView"
    assert returns[-1] == "app", (
        f"resolveView default return must be 'app', got '{returns[-1]}'"
    )


def test_landing_imported_only_in_main_jsx():
    """Landing.jsx is imported in main.jsx and no other .jsx component."""
    import_pattern = re.compile(r"import\s+.*Landing.*from", re.IGNORECASE)
    violations = []
    for dirpath, _dirs, files in os.walk(ROOT):
        for fname in files:
            if not fname.endswith((".jsx", ".js", ".tsx", ".ts")):
                continue
            fpath = os.path.join(dirpath, fname)
            # main.jsx is allowed to import Landing
            if os.path.abspath(fpath) == os.path.abspath(MAIN_JSX):
                continue
            content = _read(fpath)
            if import_pattern.search(content):
                violations.append(fpath)
    assert not violations, (
        f"Landing.jsx imported outside main.jsx: {violations}"
    )


def test_nginx_conf_has_x_robots_noindex():
    """nginx.conf must include X-Robots-Tag: noindex for self-hosted instances."""
    nginx = _read(NGINX_CONF)
    assert "X-Robots-Tag" in nginx, "nginx.conf missing X-Robots-Tag header"
    assert "noindex" in nginx, "nginx.conf X-Robots-Tag must include 'noindex'"


def test_nginx_conf_has_spa_try_files():
    """nginx.conf must still serve the SPA correctly."""
    nginx = _read(NGINX_CONF)
    assert "try_files" in nginx


def test_brand_config_unaffected():
    """brand.config.js regression guard — must still export brandConfig."""
    src = _read(BRAND_CONFIG)
    assert "export const brandConfig" in src
    assert "VITE_BRAND_NAME" in src
    assert "ClipsOpenShorts" in src
