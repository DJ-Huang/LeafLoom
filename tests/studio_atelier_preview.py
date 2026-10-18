"""Render the packaged ATELIER preview using the real static export runtime.

Run from the repository root after installing the publishing dependencies and
Chromium: python tests/studio_atelier_preview.py
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from vault_rag.design_templates import load_template, template_path
from vault_rag.design_publishing import plan, render_item


def main():
    output = Path('.cache/studio-qa')
    output.mkdir(parents=True, exist_ok=True)
    document = load_template('atelier')
    items, _ = plan(document, [page['id'] for page in document['pages']], None, 1, 'png')
    report = []
    for item in items:
        rendered = render_item(item, {}, 'png', 1)
        (output / ('professional-template-source-' + item['page_id'] + '.png')).write_bytes(rendered)
        preflight = item.get('preflight', {})
        report.append({'page_id': item['page_id'], 'preflight': preflight})
        print(json.dumps(report[-1], ensure_ascii=False), flush=True)
        if item['page_id'] == 'atelier-home':
            with Image.open(io.BytesIO(rendered)) as screenshot:
                preview = screenshot.crop((0, 0, 1440, 830)).resize((1000, 576), Image.Resampling.LANCZOS).convert('RGB')
                preview.save(template_path('atelier') / 'preview.jpg', quality=90)
                preview.save(output / 'atelier-preview.jpg', quality=90)
    (output / 'atelier-source-preflight.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
