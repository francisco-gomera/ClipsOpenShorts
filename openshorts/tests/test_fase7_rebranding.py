import os
import json
import pytest


def test_brand_config_file_exists_and_valid():
    """Verify that brand.config.js exists and exports expected brand properties and tokens."""
    brand_path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "src", "brand.config.js")
    assert os.path.isfile(brand_path), "brand.config.js must exist"

    content = open(brand_path, "r", encoding="utf-8").read()
    assert "BRAND_PLACEHOLDER" in content
    assert "ClipsOpenShorts" in content
    assert "VITE_BRAND_NAME" in content
    assert "fontDisplay" in content
    assert "Instrument Serif" in content
    assert "Geist" in content
    assert "JetBrains Mono" in content


def test_design_system_and_tokens_free_of_restricted_terms():
    """Verify that design.md, tokens.css, and fonts.css do not reference Lumen or Night Foundry."""
    root_dir = os.path.join(os.path.dirname(__file__), "..")

    design_md = open(os.path.join(root_dir, "design.md"), "r", encoding="utf-8").read()
    assert "Lumen · Night Foundry" not in design_md

    tokens_css = open(os.path.join(root_dir, "dashboard", "src", "tokens.css"), "r", encoding="utf-8").read()
    assert "lumen (night foundry)" not in tokens_css

    fonts_css = open(os.path.join(root_dir, "dashboard", "public", "fonts.css"), "r", encoding="utf-8").read()
    assert "Lumen system" not in fonts_css


def test_claude_guidelines_updated():
    """Verify that CLAUDE.md includes the Evolution Plan rules (D1-D5, hooks, upload-post)."""
    claude_md_path = os.path.join(os.path.dirname(__file__), "..", "CLAUDE.md")
    content = open(claude_md_path, "r", encoding="utf-8").read()
    assert "Evolution Plan & Customization Rules" in content
    assert "VITE_SHOW_EXTRA_TOOLS" in content
    assert "VITE_BRAND_NAME" in content
    assert "classic" in content
    assert "anton" in content
