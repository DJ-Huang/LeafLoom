"""Recoverable, optional catalog metadata; no note parsing during restore."""
from __future__ import annotations
import json, sqlite3, time
from contextlib import closing

def connect(root):
    path=root/'.vault-rag/catalog.sqlite'
    path.parent.mkdir(exist_ok=True)
    db=sqlite3.connect(path,timeout=5)
    if db.execute('PRAGMA user_version').fetchone()[0]>2:
        db.close();raise ValueError('Catalog cache was created by a newer version')
    if db.execute('PRAGMA user_version').fetchone()[0]<2:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='files'").fetchone():
            with closing(sqlite3.connect(path.with_name('catalog-before-v2-'+str(time.time_ns())+'.sqlite'))) as backup:
                db.backup(backup)
        db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,title TEXT,metadata TEXT,sha256 TEXT,mtime REAL)')
        db.execute('CREATE TABLE IF NOT EXISTS cached_entries(path TEXT PRIMARY KEY,data TEXT,content TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS directories(path TEXT PRIMARY KEY)')
        db.execute('PRAGMA user_version=2');db.commit()
    return db

def restore(root):
    if not (root/'.vault-rag/catalog.sqlite').is_file():return {},{''}
    with closing(connect(root)) as db:
        entries={}
        for path,raw in db.execute('SELECT path,data FROM cached_entries'):
            entry=json.loads(raw);entry['_stat']=tuple(entry['_stat'])
            entry.update(text='',body='',_hydrated=False)
            entries[path]=entry
        # Old cache contains useful paths/aliases but lacks exact stamps/body.
        for path,title,metadata,sha,mtime in db.execute('SELECT * FROM files'):
            if path in entries:continue
            folder,_,name=path.rpartition('/')
            entries[path]={'path':path,'title':title,'metadata':json.loads(metadata),'sha256':sha,'text':'','body':'',
                '_stat':(-1,-1),'_parsed':False,'_hydrated':False,
                'file':{'path':path,'name':name.rsplit('.',1)[0],'folder':folder,'ext':name.rsplit('.',1)[-1],
                    'tags':[],'size':0,'mtime':mtime,'ctime':mtime,'modified':mtime,'basename':name.rsplit('.',1)[0],
                    'link':{'path':path,'label':title},'inlinks':[],'outlinks':[]}}
        dirs={x[0] for x in db.execute('SELECT path FROM directories')}|{''}
        for path in entries:
            parent=path.rpartition('/')[0]
            while parent:dirs.add(parent);parent=parent.rpartition('/')[0]
        return entries,dirs

def content(root,path,stamp):
    if not (root/'.vault-rag/catalog.sqlite').is_file():return None
    with closing(sqlite3.connect(root/'.vault-rag/catalog.sqlite',timeout=5)) as db:
        row=db.execute('SELECT data,content FROM cached_entries WHERE path=?',(path,)).fetchone()
        if row and row[1] and tuple(json.loads(row[0])['_stat'])==stamp:return json.loads(row[1])

def persist(root,entries,changed,reset,old,directories):
    with closing(connect(root)) as db:
        stale=({r[0] for r in db.execute('SELECT path FROM files')} if reset else set(old))-set(entries)
        for table in ('files','cached_entries'):db.executemany('DELETE FROM '+table+' WHERE path=?',[(p,) for p in stale])
        for path in (set(entries) if reset else changed):
            entry=entries.get(path)
            if entry is None:continue
            db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)',(path,entry['title'],json.dumps(entry['metadata'],ensure_ascii=False,default=str),entry['sha256'],entry['file']['mtime']))
            data={k:v for k,v in entry.items() if k not in ('text','body','_hydrated')}
            body=json.dumps({'text':entry['text'],'body':entry['body']},ensure_ascii=False) if entry.get('_hydrated') else None
            db.execute('INSERT INTO cached_entries VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET data=excluded.data, content=CASE WHEN excluded.content IS NOT NULL THEN excluded.content WHEN json_extract(cached_entries.data,\'$._stat\')=json_extract(excluded.data,\'$._stat\') THEN cached_entries.content ELSE NULL END',(path,json.dumps(data,ensure_ascii=False,default=str),body))
        db.execute('DELETE FROM directories');db.executemany('INSERT INTO directories VALUES(?)',[(p,) for p in directories]);db.commit()
