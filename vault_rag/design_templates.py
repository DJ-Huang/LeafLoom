"""Immutable, packaged design starters. Never load templates from user paths."""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATES = Path(__file__).parent / 'design_assets' / 'templates'


def template_path(template_id: str) -> Path:
    if template_id not in ('forma', 'motion', 'atelier'):
        raise ValueError('未知的内置设计模板')
    return TEMPLATES / template_id


def load_template(template_id: str) -> dict:
    # Parse anew on each creation; document creation also assigns a fresh identity.
    return json.loads((template_path(template_id) / 'project.json').read_text(encoding='utf-8'))
