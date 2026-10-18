"""Stable content bindings and lightweight, non-destructive variant projections.

Variants contain content and layout deltas only. Assets, component identities,
HTML and script sources remain owned by the canonical document.
"""
from __future__ import annotations

import copy
import math
import re

_KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')
_LAYOUT = {'x', 'y', 'width', 'height', 'minWidth', 'maxWidth', 'minHeight', 'maxHeight',
           'fontSize', 'lineHeight', 'letterSpacing', 'textAlign', 'fontFamily', 'fontWeight',
           'padding', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'gap',
           'display', 'flexDirection', 'alignItems', 'justifyContent', 'direction'}


def _key(value):
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        raise ValueError('Binding and variant keys require 1 to 128 letters, digits, dots, colons, underscores or hyphens')
    return value


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.get('children', []))


def _nodes(document):
    for page in document['pages']:
        yield from _walk(page['nodes'])
    for component in document['components'].values():
        yield from _walk([component['node']])


def _value(document, kind, value):
    if not isinstance(value, str) or len(value) > 100000:
        raise ValueError('Binding values must be text of at most 100000 characters')
    if kind == 'image' and value not in document['assets']:
        raise ValueError('Image bindings must reference an existing shared asset ID')


def _apply_value(node, kind, value):
    props = node.setdefault('props', {})
    props['text' if kind == 'text' else 'assetId'] = value
    if kind == 'image':
        # An old URL must not take precedence over the selected shared asset.
        props.pop('src', None)


def validate_bindings(document):
    bindings, variants = document.get('bindings', {}), document.get('variants', {})
    if not isinstance(bindings, dict) or len(bindings) > 10000:
        raise ValueError('Bindings must be an object with at most 10000 records')
    if not isinstance(variants, dict) or len(variants) > 256:
        raise ValueError('Variants must be an object with at most 256 records')
    for key, record in bindings.items():
        _key(key)
        if not isinstance(record, dict) or set(record) - {'key', 'kind', 'value', 'revision'} or record.get('key') != key:
            raise ValueError('Binding requires a matching stable key')
        if record.get('kind') not in ('text', 'image'):
            raise ValueError('Binding kind must be text or image')
        revision = record.get('revision')
        if type(revision) is not int or not 1 <= revision <= 10**12:
            raise ValueError('Binding revision must be a positive bounded integer')
        _value(document, record['kind'], record.get('value'))
    nodes = {node['id']: node for node in _nodes(document)}
    pages = {page['id']: page for page in document['pages']}
    for node in nodes.values():
        key = node.get('props', {}).get('bindingKey')
        if key is not None:
            _key(key)
            if key not in bindings:
                raise ValueError('Element binding references a missing stable key')
            if bindings[key]['kind'] == 'image' and node['type'] not in ('image', 'element'):
                raise ValueError('Image bindings require image or element nodes')
            if bindings[key]['kind'] == 'text' and node['type'] not in ('text', 'button', 'element'):
                raise ValueError('Text bindings require text, button or element nodes')
            field = 'text' if bindings[key]['kind'] == 'text' else 'assetId'
            if node.get('props', {}).get(field) != bindings[key]['value']:
                raise ValueError('Bound element content must match its stable binding source; use binding.set or node.bind')
    for key, variant in variants.items():
        _key(key)
        if not isinstance(variant, dict) or variant.get('id') != key or set(variant) - {'id', 'name', 'locale', 'context', 'values', 'layout', 'pageLayout'}:
            raise ValueError('Variant requires a matching identity and supported fields')
        for field, limit in (('name', 200), ('locale', 64)):
            if not isinstance(variant.get(field, ''), str) or len(variant.get(field, '')) > limit:
                raise ValueError('Variant name or locale is too long')
        context = variant.get('context', {})
        if not isinstance(context, dict) or len(context) > 16:
            raise ValueError('Variant context requires at most 16 scalar fields')
        for field, value in context.items():
            _key(field)
            if not (value is None or isinstance(value, bool) or isinstance(value, str) and len(value) <= 200 or type(value) in (int, float) and math.isfinite(value) and abs(value) <= 10**15):
                raise ValueError('Variant context values must be bounded scalars')
        values = variant.get('values', {})
        if not isinstance(values, dict) or len(values) > 10000:
            raise ValueError('Variant values must be a bounded object')
        for binding_key, entry in values.items():
            if binding_key not in bindings or not isinstance(entry, dict) or set(entry) != {'value', 'sourceRevision'}:
                raise ValueError('Variant values require an existing binding, value and sourceRevision')
            source = bindings[binding_key]
            if type(entry['sourceRevision']) is not int or not 1 <= entry['sourceRevision'] <= source['revision']:
                raise ValueError('Variant sourceRevision must reference an existing source revision')
            _value(document, source['kind'], entry['value'])
        layout = variant.get('layout', {})
        if not isinstance(layout, dict) or len(layout) > 10000:
            raise ValueError('Variant layout must be a bounded object')
        for node_id, style in layout.items():
            if node_id not in nodes or not isinstance(style, dict) or set(style) - _LAYOUT:
                raise ValueError('Variant layout must reference existing nodes and supported style fields')
            for value in style.values():
                if type(value) in (int, float) and math.isfinite(value) and abs(value) <= 100000:
                    continue
                if isinstance(value, str) and len(value) <= 200 and not any(token in value.lower() for token in ('url(', 'expression(', ';', '<', '>', '\\')):
                    continue
                raise ValueError('Variant layout values must be bounded safe CSS scalars')
        page_layout = variant.get('pageLayout', {})
        if not isinstance(page_layout, dict) or len(page_layout) > len(pages):
            raise ValueError('Variant pageLayout must be a bounded object')
        for page_id, dimensions in page_layout.items():
            if page_id not in pages or not isinstance(dimensions, dict) or set(dimensions) - {'width', 'height'}:
                raise ValueError('Variant pageLayout requires existing pages and dimensions')
            if any(type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 32768 for value in dimensions.values()):
                raise ValueError('Variant page dimensions must be between 1 and 32768')


def binding_status(document, variant_id):
    variant = document.get('variants', {}).get(variant_id)
    if variant is None:
        raise ValueError('Unknown variant')
    values = variant.get('values', {})
    return {'missing': [key for key in document.get('bindings', {}) if key not in values],
            'stale': [key for key, entry in values.items() if entry['sourceRevision'] != document['bindings'][key]['revision']]}


def resolve_document(document, variant_id=None):
    """Return a detached rendering projection; never save this over the source."""
    result = copy.deepcopy(document)
    variant = {}
    if variant_id is not None:
        if variant_id not in document.get('variants', {}):
            raise ValueError('Unknown variant')
        variant = document['variants'][variant_id]
    for node in _nodes(result):
        key = node.get('props', {}).get('bindingKey')
        if key is not None:
            source = document['bindings'][key]
            value = variant.get('values', {}).get(key, {}).get('value', source['value'])
            _apply_value(node, source['kind'], value)
        style = variant.get('layout', {}).get(node['id'])
        if style:
            node.setdefault('style', {}).update(copy.deepcopy(style))
    for page in result['pages']:
        page.update(copy.deepcopy(variant.get('pageLayout', {}).get(page['id'], {})))
    return result


def resolve_page(document, page_id, variant_id=None):
    for page in resolve_document(document, variant_id)['pages']:
        if page['id'] == page_id:
            return page
    raise ValueError('Unknown page')


def binding_command(document, command):
    """Mutate only the caller's transaction copy; its normal validator/undo owns commit."""
    kind = command.get('type')
    if kind not in {'binding.set', 'binding.delete', 'node.bind', 'variant.set', 'variant.delete', 'variant.value.set'}:
        return False
    bindings = document.setdefault('bindings', {})
    variants = document.setdefault('variants', {})
    if kind == 'binding.set':
        key = _key(command.get('key'))
        old = bindings.get(key)
        value_kind = command.get('kind', old.get('kind') if old else None)
        if old and old['kind'] != value_kind:
            raise ValueError('A stable binding cannot change kind')
        value = command.get('value')
        revision = old['revision'] if old else 1
        if old and old['value'] != value:
            revision += 1
        bindings[key] = {'key': key, 'kind': value_kind, 'value': value, 'revision': revision}
        for node in _nodes(document):
            if node.get('props', {}).get('bindingKey') == key:
                _apply_value(node, value_kind, value)
    elif kind == 'binding.delete':
        key = _key(command.get('key'))
        if key not in bindings:
            raise ValueError('Unknown binding')
        if any(node.get('props', {}).get('bindingKey') == key for node in _nodes(document)) or any(key in variant.get('values', {}) for variant in variants.values()):
            raise ValueError('Unbind elements and remove variant values before deleting this binding')
        del bindings[key]
    elif kind == 'node.bind':
        page = next((page for page in document['pages'] if page['id'] == command.get('page_id')), None)
        component = None
        if page is None and str(command.get('page_id', '')).startswith('component:'):
            component = document['components'].get(command['page_id'][10:])
            page = {'nodes': [component['node']]} if component else None
        node = next((node for node in _walk(page['nodes']) if node['id'] == command.get('node_id')), None) if page else None
        if node is None:
            raise ValueError('Unknown binding target node')
        key = command.get('key')
        if key is None:
            node.setdefault('props', {}).pop('bindingKey', None)
        else:
            _key(key)
            if key not in bindings:
                raise ValueError('Unknown binding')
            node.setdefault('props', {})['bindingKey'] = key
            _apply_value(node, bindings[key]['kind'], bindings[key]['value'])
        if component is not None:
            component['version'] = component.get('version', 0) + 1
    elif kind == 'variant.set':
        patch = command.get('variant')
        if not isinstance(patch, dict):
            raise ValueError('variant must be an object')
        key = _key(patch.get('id'))
        variants[key] = {**variants.get(key, {'id': key, 'name': key, 'locale': '', 'context': {}, 'values': {}, 'layout': {}, 'pageLayout': {}}), **copy.deepcopy(patch)}
    elif kind == 'variant.delete':
        key = _key(command.get('id'))
        if key not in variants:
            raise ValueError('Unknown variant')
        del variants[key]
    elif kind == 'variant.value.set':
        key, variant_id = _key(command.get('key')), _key(command.get('id'))
        if key not in bindings or variant_id not in variants:
            raise ValueError('Unknown binding or variant')
        values = variants[variant_id].setdefault('values', {})
        if command.get('value') is None:
            values.pop(key, None)
        else:
            values[key] = {'value': command['value'], 'sourceRevision': command.get('source_revision', bindings[key]['revision'])}
    return True


def prune_deleted_layouts(before, after):
    """Remove only overrides whose original target was intentionally deleted."""
    removed_nodes = {node['id'] for node in _nodes(before)} - {node['id'] for node in _nodes(after)}
    removed_pages = {page['id'] for page in before['pages']} - {page['id'] for page in after['pages']}
    for variant in after.get('variants', {}).values():
        for key in removed_nodes:
            variant.get('layout', {}).pop(key, None)
        for key in removed_pages:
            variant.get('pageLayout', {}).pop(key, None)


def duplicate_layouts(document, mapping):
    for variant in document.get('variants', {}).values():
        for field in ('layout', 'pageLayout'):
            overrides = variant.get(field, {})
            for old, new in mapping.items():
                if old in overrides:
                    overrides[new] = {**copy.deepcopy(overrides[old]), **overrides.get(new, {})}


def image_binding_references(document):
    for key, binding in document.get('bindings', {}).items():
        if binding['kind'] == 'image':
            yield binding['value'], key, None
            for variant_id, variant in document.get('variants', {}).items():
                if key in variant.get('values', {}):
                    yield variant['values'][key]['value'], key, variant_id


def replace_binding_asset(document, old_id, new_id):
    for key, binding in document.get('bindings', {}).items():
        if binding['kind'] != 'image':
            continue
        old_revision = binding['revision']
        if binding['value'] == old_id:
            binding_command(document, {'type': 'binding.set', 'key': key, 'value': new_id})
        for variant in document.get('variants', {}).values():
            entry = variant.get('values', {}).get(key)
            if entry and entry['value'] == old_id:
                entry['value'] = new_id
                if entry['sourceRevision'] == old_revision:
                    entry['sourceRevision'] = document['bindings'][key]['revision']
