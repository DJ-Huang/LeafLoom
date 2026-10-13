"""Small stdlib-only gettext-style catalogue shared by desktop and web."""
from __future__ import annotations
import functools
import json
import locale
import os
import re
from pathlib import Path

def resolve_locale(value='auto'):
    if value == 'auto':
        value = locale.getlocale()[0] or os.environ.get('LANG', 'en')
        if os.name == 'nt':
            import ctypes
            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)): value = buffer.value
    value = str(value).lower().replace('_', '-')
    return 'zh-CN' if value.startswith('zh') else 'ja' if value.startswith('ja') else 'en'

@functools.lru_cache(maxsize=3)
def catalogue(language):
    return json.loads((Path(__file__).parent/'locales'/f'{language}.json').read_text(encoding='utf-8'))

def t(message, directory=None, language=None, **params):
    if language is None:
        try: language = json.loads((Path(directory)/'preferences.json').read_text(encoding='utf-8')).get('locale', 'auto')
        except (OSError, ValueError, TypeError): language = 'auto'
    values = catalogue(resolve_locale(language))
    text = values.get(message)
    if text is None:
        text = message
        # Composite launcher/status messages contain paths and original diagnostics.
        for key in sorted(values, key=len, reverse=True):
            if len(key)>4 and key in text and key!=values[key]: text=text.replace(key,values[key])
    return re.sub(r'\{(\w+)\}', lambda match: str(params.get(match[1], match[0])), text)

def error_code(message):
    import hashlib
    return 'message.' + hashlib.sha256(message.encode()).hexdigest()[:12]
