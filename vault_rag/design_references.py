"""Static resource references shared by editing, projection and library bundles."""
from __future__ import annotations
import ast
import json
import posixpath
import re
from urllib.parse import unquote, urlsplit

from vault_rag.design_literals import tokens


CALLS = {
    ('ctx', '.', 'assets', '.', 'resolve', '('): 'asset',
    ('ctx', '.', 'asset', '('): 'asset',  # First-generation component sources.
    ('ctx', '.', 'navigate', '('): 'page',
    ('ctx', '.', 'open', '('): 'page',
    ('ctx', '.', 'find', '('): 'node',
}


def script_references(source):
    result, items = [], tokens(source)
    def literal(index, kind):
        if index >= len(items):
            return
        value, start, stop = items[index]
        if not value.startswith(('"', "'", '`')) or value.startswith('`') and '${' in value:
            return
        try:
            decoded = value[1:-1] if value.startswith('`') else ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return
        if isinstance(decoded, str):
            result.append({'kind': kind, 'value': decoded, 'start': start, 'end': stop, 'quote': value[0]})

    for index in range(len(items)):
        for pattern, kind in CALLS.items():
            end = index + len(pattern)
            if end >= len(items) or tuple(value for value, _, _ in items[index:end]) != pattern:
                continue
            # Require a complete literal argument; concatenated/dynamic values
            # are intentionally left to the user's declared dependencies.
            if end + 1 >= len(items) or items[end + 1][0] not in (')', ','):
                continue
            literal(end, kind)
        keyword = items[index][0]
        if keyword == 'from':
            literal(index + 1, 'module')
        elif keyword == 'import':
            cursor = index + 1
            if cursor < len(items) and items[cursor][0] == '(':
                cursor += 1
            literal(cursor, 'module')
    return sorted(result, key=lambda reference: reference['start'])


def quoted(value, quote):
    result = value.replace('\\', '\\\\').replace(quote, '\\' + quote).replace('\r', '\\r').replace('\n', '\\n')
    if quote == '`':
        result = result.replace('${', '\\${')
    return quote + result + quote


def rewrite_script(source, resolve):
    edits = []
    for reference in script_references(source):
        value = resolve(reference['kind'], reference['value'])
        if value is not None and value != reference['value']:
            edits.append((reference['start'], reference['end'], quoted(value, reference['quote'])))
    for start, end, value in reversed(edits):
        source = source[:start] + value + source[end:]
    return source


CSS = re.compile(r'''/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|(?P<url>url\(\s*(?P<quote>['"]?)(?P<path>(?:\\.|[^'"\\)])*?)(?P=quote)\s*\))''', re.I)
TAG = re.compile(r'''<!--[\s\S]*?-->|<(?:"[^"]*"|'[^']*'|[^'">])*>''')
ATTRIBUTE = re.compile(r'''\b(?P<name>src|href|poster|srcset|style)\s*=\s*(?P<quote>['"])(?P<value>[\s\S]*?)(?P=quote)''', re.I)


class AssetReferences:
    def __init__(self, assets):
        self.assets = assets
        self.paths = {}
        for asset_id, asset in assets.items():
            if asset.get('path'):
                self.paths.setdefault(asset['path'], set()).add(asset_id)

    @staticmethod
    def path(value, base_path=''):
        if not isinstance(value, str) or not value or value.startswith(('data:', 'blob:', '#')):
            return None
        marker = '__STUDIO_ASSET__/'
        if value.startswith(marker):
            value, base_path = value[len(marker):], ''
        try:
            url = urlsplit(value)
        except ValueError:
            return None
        if url.scheme or url.netloc:
            return None
        path = unquote(url.path)
        if path.startswith('/'):
            base_path = ''
        if base_path and not base_path.endswith('/') and '.' in posixpath.basename(base_path):
            base_path = posixpath.dirname(base_path)
        path = posixpath.normpath(posixpath.join(base_path, path.lstrip('/')))
        return path if path not in ('', '.', '..') and not path.startswith('../') else None

    def resolve(self, value, base_path='', *, allow_id=False):
        if allow_id and isinstance(value, str) and value in self.assets:
            return {value}
        root = self.path(value)
        found = self.paths.get(root, set())
        return set(found or self.paths.get(self.path(value, base_path), set()))

    def process(self, value, *, base_path='', context=None, old_id=None, new_id=None):
        """Collect references; optional replacement edits only defined fields."""
        found = set()
        old_path = self.assets.get(old_id, {}).get('path')
        new_path = self.assets.get(new_id, {}).get('path')

        def path_value(text, base):
            uses = self.resolve(text, base)
            found.update(uses)
            if old_id not in uses or not new_path:
                return text
            marker = '__STUDIO_ASSET__/'
            raw = text[len(marker):] if text.startswith(marker) else text
            url = urlsplit(raw)
            suffix = ('?' + url.query if url.query else '') + ('#' + url.fragment if url.fragment else '')
            if text.startswith(marker):
                return marker + new_path + suffix
            if url.path.startswith('/'):
                return '/' + new_path + suffix
            if base and self.path(text) != old_path and self.path(text, base) == old_path:
                directory = posixpath.dirname(base) if not base.endswith('/') and '.' in posixpath.basename(base) else base
                return posixpath.relpath(new_path, directory or '.') + suffix
            return ('./' if text.startswith('./') else '') + new_path + suffix

        def script(text):
            def resolve(kind, name):
                if kind != 'asset':
                    return None
                uses = self.resolve(name, allow_id=True)
                found.update(uses)
                if old_id in uses and new_id:
                    return new_id if name == old_id else path_value(name, '')
                return None
            return rewrite_script(text, resolve)

        def css(text, base):
            edits = []
            for match in CSS.finditer(text):
                if match.group('url') is None:
                    continue
                raw = match.group('path')
                reference = raw.strip()
                replacement = path_value(reference, base)
                if reference != replacement:
                    start, end = match.span('path')
                    offset = len(raw) - len(raw.lstrip())
                    edits.append((start + offset, end - (len(raw) - len(raw.rstrip())), replacement))
            for start, end, replacement in reversed(edits):
                text = text[:start] + replacement + text[end:]
            return text

        def srcset(text, base):
            if text.lstrip().startswith('data:'):
                return text
            return ','.join(re.sub(r'^(\s*)(\S+)', lambda match: match[1] + path_value(match[2], base), part) for part in text.split(','))

        def html(text, base):
            def tag(match):
                original = match[0]
                if original.startswith('<!--'):
                    return original
                def attribute(item):
                    name, raw = item['name'].lower(), item['value']
                    changed = css(raw, base) if name == 'style' else srcset(raw, base) if name == 'srcset' else path_value(raw, base)
                    start, end = item.span('value')
                    return item[0][:start - item.start()] + changed + item[0][end - item.start():]
                return ATTRIBUTE.sub(attribute, original)
            return TAG.sub(tag, text)

        def walk(item, mode=None, base=base_path):
            if isinstance(item, dict):
                local_base = item.get('basePath', base) if isinstance(item.get('basePath', base), str) else base
                for key, child in list(item.items()):
                    if key == 'assetId' and isinstance(child, str):
                        if child in self.assets:
                            found.add(child)
                        if child == old_id and new_id:
                            item[key] = new_id
                    elif isinstance(child, str):
                        if key in ('src', 'href', 'poster'):
                            item[key] = path_value(child, local_base)
                        elif key == 'srcset':
                            item[key] = srcset(child, local_base)
                        elif key == 'source':
                            item[key] = script(child)
                        elif key == 'css' or key == 'style' or mode == 'style':
                            item[key] = css(child, local_base)
                        elif key in ('html', 'svg'):
                            item[key] = html(child, local_base)
                    elif isinstance(child, (dict, list)):
                        walk(child, 'style' if key == 'style' else None, local_base)
            elif isinstance(item, list):
                for child in item:
                    walk(child, mode, base)
            elif isinstance(item, str):
                return script(item) if mode == 'script' else css(item, base) if mode == 'style' else item
            return item

        result = walk(value, context)
        return found, result
