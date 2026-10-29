"""Private worker-only metadata vector cache. Never loaded by the HTTP process."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3


def execute(config, model, value):
    import numpy as np
    directory = Path(value['directory'])
    expected = config.root / '.vault-rag' / 'asset-search'
    if directory != expected or directory.resolve()!=expected.absolute() or directory.is_symlink():
        raise ValueError('Invalid asset vector directory')
    if not model.ready or model.fingerprint != value['fingerprint']:
        raise ValueError('Asset model is not prepared')
    directory.mkdir(parents=True,exist_ok=True)
    database = directory/'vectors.sqlite'
    for suffix in ('','-wal','-shm','-journal'):
        if (directory/('vectors.sqlite'+suffix)).is_symlink():
            raise ValueError('Linked vector database is not allowed')
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE IF NOT EXISTS vectors(fingerprint TEXT,hash TEXT,vector BLOB,PRIMARY KEY(fingerprint,hash))')
        if value['operation']=='asset_build':
            entries = value['entries']
            if len(entries)>8:
                raise ValueError('Asset batch exceeds limit')
            pending = []
            for entry in entries:
                calculated = hashlib.sha256(json.dumps(entry['text'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                if calculated != entry['hash']:
                    raise ValueError('Invalid asset text hash')
                if not db.execute('SELECT 1 FROM vectors WHERE fingerprint=? AND hash=?',(model.fingerprint,entry['hash'])).fetchone():
                    pending.append(entry)
            if pending:
                vectors = model.encode([e['text'] for e in pending])
                db.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',
                    [(model.fingerprint,e['hash'],np.asarray(v,dtype=np.float32).tobytes()) for e,v in zip(pending,vectors)])
            return {'completed':len(entries)}
        manifest = json.loads((directory/'current.json').read_text())
        if manifest['fingerprint']!=model.fingerprint:
            raise ValueError('Asset index model changed')
        published = {(e['id'],e['hash']) for e in manifest['entries']}
        entries = [e for e in value['entries'] if (e['id'],e['hash']) in published]
        query = np.asarray(model.encode([value['query']])[0],dtype=np.float32)
        hits = []
        for entry in entries:
            row = db.execute('SELECT vector FROM vectors WHERE fingerprint=? AND hash=?',(model.fingerprint,entry['hash'])).fetchone()
            if row:
                vector = np.frombuffer(row[0],dtype=np.float32)
                similarity = float(np.dot(query,vector)/max(1e-12,np.linalg.norm(query)*np.linalg.norm(vector)))
                hits.append({'id':entry['id'],'similarity':similarity})
        return sorted(hits,key=lambda h:(-h['similarity'],h['id']))[:50]
