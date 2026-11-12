"""Directory discovery preferences do not grant or revoke byte access."""
SCAN_INTERVAL = 2 * 60 * 60
STARTUP_GRACE = 60
MAX_DIRECTORY_INTERVAL = 7 * 24 * 60 * 60
MAX_METADATA_INTERVAL = 6 * 60 * 60


def idle_interval(previous=SCAN_INTERVAL, *, changed=False, maximum=MAX_METADATA_INTERVAL):
    return SCAN_INTERVAL if changed else min(maximum, max(SCAN_INTERVAL, previous) * 2)


def retry_interval(failures):
    return min(60 * 60, 60 * 2 ** min(max(0, failures - 1), 6))


def normalize_scan_roots(value):
    from vault_rag.remote_webdav import remote_path
    if not isinstance(value, list) or len(value) > 32 or any(not isinstance(p, str) for p in value):
        raise ValueError('Enter up to 32 server scan directories')
    roots = sorted({remote_path(p.strip()) for p in value if p.strip()}) or ['']
    if any(p.count('/') >= 32 for p in roots):raise ValueError('Invalid remote attachment path')
    return [p for p in roots if not any(p != parent and (not parent or p.startswith(parent + '/')) for parent in roots)]


def in_scan_scope(path, roots):
    return any(not root or path == root or path.startswith(root + '/') for root in roots)


def register_scan_scope(db, sources):
    scopes = {s['id']: s.get('scan_roots', ['']) for s in sources}
    db.create_function('attachment_scan_scope', 2,
        lambda source, path: int(source == 'local' or in_scan_scope(path, scopes.get(source, ['']))), deterministic=True)
