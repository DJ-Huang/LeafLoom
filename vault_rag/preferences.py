"""User interface preferences, deliberately separate from index configuration."""
from __future__ import annotations
import json
import threading
from pathlib import Path
from vault_rag.local_state import atomic_write, digest
from vault_rag.platform_support import private_file_mode, path_key

LOCALES = ('auto', 'zh-CN', 'en', 'ja')

class Preferences:
    def __init__(self, directory: Path):
        self.path = directory / 'preferences.json'
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            try:
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(value, dict): raise ValueError('Invalid preferences')
            except FileNotFoundError:
                value = {}
            if not isinstance(value.get('onboarding',{}),dict): raise ValueError('Invalid guide preferences')
            choice=value.get('locale','auto')
            return {'locale': choice if choice in LOCALES else 'auto', 'onboarding': value.get('onboarding', {})}

    def save(self, values, root=None):
        if not isinstance(values, dict): raise ValueError('Invalid preferences')
        with self.lock:
            current = self.read()
            if 'locale' in values:
                if values['locale'] not in LOCALES: raise ValueError('Unsupported language')
                current['locale'] = values['locale']
            if 'guide' in values:
                if not root: raise ValueError('Connect a folder first')
                guide = values['guide']
                if not isinstance(guide, dict): raise ValueError('Invalid guide preferences')
                key = digest(path_key(str(Path(root).resolve())))
                previous = current['onboarding'].get(key, {})
                checked = guide.get('checked', previous.get('checked', []))
                if not isinstance(checked, list) or any(x not in ('read','create','search','source','graph','ai') for x in checked):
                    raise ValueError('Invalid guide checklist')
                step = guide.get('step', previous.get('step', 'done'))
                if step not in ('scope', 'ready', 'done'): raise ValueError('Invalid guide step')
                current['onboarding'][key] = {'step': step, 'dismissed': bool(guide.get('dismissed', previous.get('dismissed', False))), 'checked': list(dict.fromkeys(checked))}
            atomic_write(self.path, json.dumps(current, ensure_ascii=False, indent=2).encode())
            private_file_mode(self.path)
            return current

    def for_root(self, root):
        value = self.read()
        value['guide'] = value['onboarding'].get(digest(path_key(str(Path(root).resolve())))) if root else None
        value.pop('onboarding')
        return value
