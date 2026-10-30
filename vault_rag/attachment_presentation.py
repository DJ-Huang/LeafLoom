"""Metadata-only projection shared by the attachment UI and MCP listing."""
import json
import threading
from pathlib import PurePosixPath
from vault_rag.attachment_groups import digest, matches


class AttachmentPresentation:
    def __init__(self, groups, library):
        self.groups, self.library = groups, library
        self.lock = threading.RLock()
        self.cache = None

    def metadata(self, root):
        import time
        with self.lock:
            if self.cache and self.cache[0] == root and time.monotonic() - self.cache[1] < 5:
                return self.cache[2]
            result = {}
            try:
                products = self.library._items(root)
            except (FileNotFoundError, ValueError):
                products = []
            for product in products:
                official, personal = product.get('official', {}), product.get('personal', {})
                categories = official.get('categories_zh') or official.get('categories') or []
                tags = list(dict.fromkeys((personal.get('tags') or []) + (official.get('keywords_zh') or []) + (official.get('keywords') or [])))
                inherited = {'description': personal.get('description') or official.get('summary_zh') or official.get('description') or official.get('source_excerpt') or '',
                             'category': personal.get('category') or (categories[0] if categories else ''), 'tags': tags}
                for file in product.get('files', []):
                    result[file['asset_id']] = {**inherited, 'cover_id': product.get('product_id') if official.get('cover_source_url') else '',
                        'official': {**official, 'title': official.get('title') or product.get('title', '')}}
            self.cache = (root, time.monotonic(), result)
            return result

    def enrich(self, root, item):
        inherited = self.metadata(root).get(item.get('asset_id'), {})
        own = {key: item.get(key, [] if key == 'tags' else '') for key in ('description', 'category', 'tags')}
        return {**item, 'personal_metadata': own,
                'description': own['description'] or inherited.get('description', ''),
                'category': own['category'] or inherited.get('category', ''),
                'tags': list(dict.fromkeys(own['tags'] + inherited.get('tags', []))),
                'cover_id': inherited.get('cover_id', ''), 'official_metadata': inherited.get('official', {})}

    def prepare(self, db, root, group_id):
        groups, device = self.groups.snapshot(root)
        group = next((g for g in groups if g['id'] == group_id), None)
        if group_id and not group: raise FileNotFoundError('Attachment group not found')
        metadata = self.metadata(root)
        db.execute('CREATE TEMP TABLE attachment_enrichment(asset_id TEXT PRIMARY KEY,description TEXT,category TEXT,tags TEXT,cover_id TEXT)')
        db.executemany('INSERT INTO attachment_enrichment VALUES(?,?,?,?,?)',
                       [(key, value['description'], value['category'], json.dumps(value['tags']), value.get('cover_id', '')) for key, value in metadata.items()])
        settings = self.library.settings(root)
        sources = {s['id']: s for s in self.groups.remote._settings(root)['sources']}
        # Resolve local identities that have been redirected by verified migration.
        redirected = {}
        for value in groups:
            for member in value['included'] + value['excluded']:
                if member['scope'] != 'local:' + device: continue
                try:
                    with self.groups.remote._db(root) as manifest:
                        current = self.groups.remote._resolve(manifest, asset_id=member['asset_id'])
                    redirected[current['id']] = member
                except (FileNotFoundError, ValueError): pass
        def identity(storage, path, physical, asset_id):
            if asset_id in redirected: return redirected[asset_id]
            import uuid
            if storage == 'local':
                scope, locator = 'local:' + device, asset_id or path
            else:
                scope = 'primary' if storage == settings['storage_id'] else 'storage:' + storage
                locator = sources.get(storage, {}).get('remote_root', '') + '/' + physical
            return {'uid': uuid.uuid5(uuid.NAMESPACE_URL, 'leafloom-attachment:' + scope + ':' + locator).hex,
                    'scope': scope, 'path': physical or path, 'asset_id': asset_id}
        def member(storage, path, physical, name, tags, category, asset_id):
            if not group: return 1
            return int(matches(group, {'storage_id': storage, 'source': 'local' if storage == 'local' else 'remote',
                'path': path, 'remote_path': physical, 'name': name, 'tags': json.loads(tags), 'category': category},
                identity(storage, path, physical, asset_id)))
        db.create_function('attachment_group_matches', 7, member)
        db.create_function('attachment_uid', 4, lambda *args: identity(*args)['uid'])
        db.commit()
        return digest([group['revision'] if group else '', metadata])

    @staticmethod
    def cte(base):
        base = base.replace('catalog AS (', 'raw_catalog AS (', 1)
        return base + ''', catalog AS (
            SELECT r.path,r.name,r.name_key,r.size,r.mtime_ns,r.mime,r.asset_id,r.storage_id,r.remote_path,r.state,
                COALESCE(NULLIF(r.description,''),e.description,'') AS description,
                COALESCE(NULLIF(r.category,''),e.category,'') AS category,
                (SELECT json_group_array(value) FROM (SELECT DISTINCT value FROM json_each(r.tags)
                    UNION SELECT value FROM json_each(COALESCE(e.tags,'[]')))) AS tags,
                r.metadata_revision,r.cache_state,COALESCE(e.cover_id,'') AS cover_id,
                attachment_uid(r.storage_id,r.path,r.remote_path,r.asset_id) AS attachment_uid
            FROM raw_catalog r LEFT JOIN attachment_enrichment e ON e.asset_id=r.asset_id
        ) '''
