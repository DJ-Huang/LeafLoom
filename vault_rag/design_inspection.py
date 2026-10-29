"""Small, paginated MCP views of a saved design; never used as writable source."""
from __future__ import annotations

import copy
import json
from typing import Literal


DesignSection = Literal['pages', 'nodes', 'assets', 'components', 'styles', 'scripts']
SECTIONS = ('pages', 'nodes', 'assets', 'components', 'styles', 'scripts')
SUMMARY_CHARS = 12000


def _label(value, limit=160):
    if isinstance(value, str):
        return value[:limit]
    return value if value is None or isinstance(value, (int, float, bool)) else None


def _flatten(nodes):
    pending = [(node, None) for node in reversed(nodes)]
    while pending:
        node, parent = pending.pop()
        yield node, parent
        pending.extend((child, node['id']) for child in reversed(node.get('children', [])))


def _page_summary(page, count):
    return {key: _label(page[key]) for key in ('name', 'group', 'width', 'height') if key in page} | {'id': page['id'], 'node_count': count}


class DesignInspection:
    """Revision-local indexes live with the existing bounded parsed-document cache."""

    def __init__(self, document):
        self.document = document
        self.pages = {page['id']: page for page in document['pages']}
        self.nodes = {}
        self.counts = {}

    def _page_nodes(self, page_id):
        if page_id not in self.pages:
            raise ValueError(f'Unknown page: {page_id}')
        if page_id not in self.nodes:
            self.nodes[page_id] = list(_flatten(self.pages[page_id]['nodes']))
            self.counts[page_id] = len(self.nodes[page_id])
        return self.nodes[page_id]

    def _count(self, page):
        if page['id'] not in self.counts:
            self.counts[page['id']] = sum(1 for _ in _flatten(page['nodes']))
        return self.counts[page['id']]

    def _summary(self, section, entry):
        if section == 'pages':
            return _page_summary(entry, self._count(entry))
        if section == 'nodes':
            node, parent = entry
            result = {key: _label(node[key]) for key in ('name', 'type') if key in node} | {'id': node['id']}
            result.update(parent_id=parent, child_count=len(node.get('children', [])))
            props = node.get('props', {})
            if isinstance(props.get('text'), str):
                result.update(text=props['text'][:160], text_truncated=len(props['text']) > 160)
            for key in ('assetId', 'componentId', 'pageId'):
                if key in props:
                    result[key] = props[key]
            result['has_source'] = bool(node.get('script') or props.get('html') or props.get('css'))
            return result
        key, value = entry
        result = {'id': key}
        if isinstance(value, dict):
            result.update({field: _label(value[field], 320 if field == 'path' else 160)
                           for field in ('name', 'path', 'mime', 'version', 'kind') if field in value})
        return result

    def read(self, *, section='pages', page_id=None, node_id=None, item_id=None,
             offset=0, limit=20, full=False):
        if section not in SECTIONS:
            raise ValueError('Unknown design section')
        if page_id is not None and section == 'pages' and not full:
            section = 'nodes'
        if node_id is not None:
            if page_id is None or section not in ('pages', 'nodes'):
                raise ValueError('node_id requires page_id and the nodes section')
            section = 'nodes'
        if page_id is not None and section not in ('pages', 'nodes'):
            raise ValueError('page_id is only valid for pages or nodes')
        if item_id is not None and section in ('pages', 'nodes'):
            raise ValueError('item_id requires a resource section')
        if full and section == 'nodes' and node_id is None:
            raise ValueError('Full nodes reads require node_id; use full=true with page_id to read a complete page')
        if section == 'nodes':
            if page_id is None:
                raise ValueError('The nodes section requires page_id')
            entries = self._page_nodes(page_id)
            if node_id is not None:
                entries = [entry for entry in entries if entry[0]['id'] == node_id]
                if not entries:
                    raise ValueError(f'Unknown element: {node_id}')
        elif section == 'pages':
            if page_id is not None and page_id not in self.pages:
                raise ValueError(f'Unknown page: {page_id}')
            entries = [self.pages[page_id]] if page_id is not None else list(self.pages.values())
        else:
            table = self.document[section]
            if item_id is not None and item_id not in table:
                raise ValueError(f'Unknown {section} item: {item_id}')
            entries = [(item_id, table[item_id])] if item_id is not None else list(table.items())
        offset, limit = max(0, int(offset)), max(1, min(100, int(limit)))
        rows, size = [], 0
        for entry in entries[offset:offset + limit]:
            if full:
                value = copy.deepcopy(entry[0] if section == 'nodes' else entry if section == 'pages' else entry[1])
            else:
                value = self._summary(section, entry)
                length = len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
                if rows and size + length > SUMMARY_CHARS:
                    break
                size += length
            rows.append(value)
        next_offset = offset + len(rows)
        result = {'section': section, 'partial': True, 'full': full, 'total': len(entries),
                  'offset': offset, 'limit': limit, 'next_offset': next_offset if next_offset < len(entries) else None}
        if section == 'pages' and not full:
            result['manifest'] = {key: self.document[key] for key in ('schemaVersion', 'id', 'name')}
            result['manifest'].update(name=_label(self.document['name']), pages=rows,
                counts={key: len(self.document[key]) for key in ('pages', 'assets', 'components', 'styles', 'scripts')})
        else:
            result[section] = rows
            if page_id is not None:
                result['page'] = _page_summary(self.pages[page_id], self._count(self.pages[page_id]))
        return result
