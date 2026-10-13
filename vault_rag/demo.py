"""Create only packaged examples; never import a user's configured vault."""
from __future__ import annotations
import json
from pathlib import Path
from vault_rag.i18n import resolve_locale
from vault_rag.platform_support import is_link

def create_demo(directory: Path, language: str):
    language = resolve_locale(language)
    examples = Path(__file__).parent / 'examples' / language
    parent = directory / 'demo'
    root = parent / language
    for path in (parent, root):
        if is_link(path): raise ValueError('Demo folder cannot be a symbolic link')
    root.mkdir(parents=True, exist_ok=True)
    for source in examples.rglob('*'):
        if not source.is_file() or source.name == 'manifest.json': continue
        target = root / source.relative_to(examples)
        for ancestor in (target, *target.parents):
            if ancestor == root: break
            if is_link(ancestor): raise ValueError('Demo folder cannot contain symbolic links')
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open('xb') as file: file.write(source.read_bytes())
        except FileExistsError:
            pass
    manifest = json.loads((examples/'manifest.json').read_text(encoding='utf-8'))
    return {'root': str(root.resolve()), 'homepage': manifest['homepage']}
