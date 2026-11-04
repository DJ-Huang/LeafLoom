"""Build a portable, page-scoped snapshot without changing the source document."""
from __future__ import annotations

import copy
import posixpath
import re

from vault_rag.design_references import AssetReferences, script_references


def select_export(document, page_ids):
    pages = {page['id']: page for page in document['pages']}
    if not isinstance(page_ids, list) or not page_ids or any(not isinstance(x, str) for x in page_ids):
        raise ValueError('Select at least one page to export')
    if len(set(page_ids)) != len(page_ids) or any(page_id not in pages for page_id in page_ids):
        raise ValueError('Export contains duplicate or unknown page IDs')
    selected = set(page_ids)
    result = copy.deepcopy(document)
    # Project metadata can describe unrelated source files and captures; it is
    # not read by the playback runtime and must not pull them into a subset.
    result.pop('metadata', None)
    result['pages'] = [page for page in result['pages'] if page['id'] in selected]
    source = {name: document.get(name, {}) for name in ('assets', 'components', 'styles', 'scripts', 'bindings')}
    used = {name: set() for name in source}
    asset_index = AssetReferences(source['assets'])
    script_paths = {(item.get('path', key) if isinstance(item, dict) else key): key
                    for key, item in source['scripts'].items()}
    missing_pages, paths, node_ids, font_text = set(), set(), set(), []
    has_script = False

    def include(table, key):
        if not isinstance(key, str) or not key or key in used[table]:
            return
        if key not in source[table]:
            raise ValueError(f'Missing export {table[:-1]}: {key}')
        used[table].add(key)
        value = source[table][key]
        if table == 'assets':
            if value.get('path'):
                paths.add(value['path'])
        elif table == 'bindings':
            if value.get('kind') == 'image':
                include('assets', value.get('value'))
        else:
            found, _ = asset_index.process(value, base_path=value.get('path', '') if isinstance(value, dict) else '', context='script' if table == 'scripts' else None)
            for asset_id in found:
                include('assets', asset_id)
            if table == 'scripts' and isinstance(value, str):
                scan({'source': value, 'path': key}, key)
            else:
                scan(value, value.get('path', '') if isinstance(value, dict) else '')

    def page_ref(value):
        if isinstance(value, str) and value in pages and value not in selected:
            missing_pages.add(value)

    def scan(value, base=''):
        nonlocal has_script
        if isinstance(value, dict):
            base = value.get('basePath', base) if isinstance(value.get('basePath', base), str) else base
            if value.get('type') and isinstance(value.get('id'), str):
                node_ids.add(value['id'])
            for key, child in value.items():
                table = {'assetId': 'assets', 'componentId': 'components', 'styleId': 'styles',
                         'scriptId': 'scripts', 'moduleId': 'scripts', 'bindingKey': 'bindings'}.get(key)
                if table and isinstance(child, str) and child:
                    include(table, child)
                elif key == 'styleIds' and isinstance(child, list):
                    for item in child:
                        include('styles', item)
                elif key in ('pageId', 'navigateTo') or key.startswith('data-'):
                    page_ref(child)
                if key == 'source' and isinstance(child, str):
                    has_script = bool(child.strip()) or has_script
                    module_path = value.get('path', base) if isinstance(value.get('path', base), str) else base
                    for ref in script_references(child):
                        if ref['kind'] == 'page':
                            page_ref(ref['value'])
                        elif ref['kind'] == 'asset':
                            ids = asset_index.resolve(ref['value'], allow_id=True)
                            for asset_id in ids:
                                include('assets', asset_id)
                            if not ids:
                                path = AssetReferences.path(ref['value'])
                                if path:
                                    paths.add(path)
                        elif ref['kind'] == 'module':
                            path = posixpath.normpath(posixpath.join(posixpath.dirname(module_path), ref['value']))
                            script_id = script_paths.get(path) or (ref['value'] if ref['value'] in source['scripts'] else None)
                            if script_id:
                                include('scripts', script_id)
                if key in ('fontFamily', 'font', 'css', 'style') and isinstance(child, str):
                    font_text.append(child.lower())
                if isinstance(child, (dict, list)):
                    scan(child, base)
        elif isinstance(value, list):
            for item in value:
                scan(item, base)
        elif isinstance(value, str):
            for ref in script_references(value):
                if ref['kind'] == 'page':
                    page_ref(ref['value'])

    for page in result['pages']:
        found, _ = asset_index.process(page, base_path=page.get('basePath', ''))
        for asset_id in found:
            include('assets', asset_id)
        scan(page, page.get('basePath', ''))
    for variant in result.get('variants', {}).values():
        variant['values'] = {key: val for key, val in variant.get('values', {}).items() if key in used['bindings']}
        variant['layout'] = {key: val for key, val in variant.get('layout', {}).items() if key in node_ids}
        variant['pageLayout'] = {key: val for key, val in variant.get('pageLayout', {}).items() if key in selected}
        for key, val in variant['values'].items():
            if source['bindings'][key].get('kind') == 'image':
                include('assets', val.get('value'))
        scan(variant['layout'])
    # Fonts are addressed by family name rather than assetId at runtime.
    text = ' '.join(font_text)
    for asset_id, asset in source['assets'].items():
        if re.search(r'\.(?:woff2?|ttf|otf)(?:$|[?#])', asset.get('path', ''), re.I):
            if any(str(name).lower() in text for name in (asset.get('fontFamily'), asset.get('name'), asset_id) if name):
                include('assets', asset_id)
    for name in source:
        result[name] = {key: value for key, value in result.get(name, {}).items() if key in used[name]}

    # An embedded page is a render dependency, not a navigation action. Leave a
    # blank container when it was not selected, rather than a broken placeholder.
    def prune(value):
        if isinstance(value, dict):
            if value.get('type') == 'page' and value.get('props', {}).get('pageId') not in selected:
                value['type'] = 'container'
                value['props'].pop('pageId', None)
                value['children'] = []
            # Imported anchors may carry a fallback HTML URL alongside the
            # Studio page ID. Keep the script-driven navigation but do not
            # bundle or open the original, unrelated HTML project.
            attrs = value.get('props', {}).get('attributes', {}) if isinstance(value.get('props'), dict) else {}
            if isinstance(attrs, dict) and any(key.startswith('data-') and target in pages
                                               for key, target in attrs.items() if isinstance(target, str)):
                href = attrs.get('href')
                if isinstance(href, str) and AssetReferences.path(href) and re.search(r'\.html?(?:[?#]|$)', href, re.I):
                    attrs['href'] = '#'
            migration = value.get('migration')
            if isinstance(migration, dict) and isinstance(migration.get('contextVariants'), list):
                migration['contextVariants'] = [item for item in migration['contextVariants'] if item.get('pageId') in selected]
            for child in value.values():
                prune(child)
        elif isinstance(value, list):
            for child in value:
                prune(child)
    prune(result['pages'])
    prune(result['components'])
    targets = [{'id': page['id'], 'name': page.get('name', page['id'])} for page in document['pages'] if page['id'] in missing_pages]
    return result, {'missing_pages': targets, 'dynamic_warning': has_script, 'paths': sorted(paths)}
