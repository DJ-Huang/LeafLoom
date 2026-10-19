"""Regression tests for persistent Markdown annotations (fictional vault)."""
import sqlite3
import pytest
from vault_rag.annotations import Annotations
from vault_rag.local_state import LocalConfig, Files, ConflictError

@pytest.fixture
def fixture(tmp_path):
    root=tmp_path/"wiki";root.mkdir()
    (root/"note.md").write_text("# Title\n你好🚀 LeafLoom knowledge. Repeat, repeat.\n",encoding="utf-8")
    config=LocalConfig(tmp_path/"settings");config.save({"root":str(root)})
    files=Files(config)
    annotations=Annotations(config,files)
    files.annotation_changed=lambda action,**fields:getattr(annotations,action)(root=str(root),**fields)
    return root,files,annotations

def range_for(files,needle="LeafLoom"):
    note=files.read("note.md");text=note["text"]
    index=text.index(needle);start=len(text[:index].encode("utf-16-le"))//2
    end=start+len(needle.encode("utf-16-le"))//2
    return note["etag"],{"from":start,"to":end,"exact":needle,
        "prefix":text[max(0,index-20):index],"suffix":text[index+len(needle):index+len(needle)+20],"etag":note["etag"]}

def add(root,files,store,kind="comment",content="Please expand"):
    etag,anchor=range_for(files)
    return store.create(root=str(root),path="note.md",kind=kind,anchor=anchor,etag=etag,content=content)["id"]

def test_read_only_listing_does_not_create_database(fixture):
    root, files, store = fixture
    database = root / '.vault-rag' / 'annotations.sqlite'
    assert not database.exists()
    assert store.list(root=str(root), path='note.md') == {
        'annotations': [], 'document_id': None,
    }
    assert not database.exists()


def test_comments_replies_revisions_reopen(fixture):
    root,files,store=fixture
    assert store.list(root=str(root),path="note.md")["annotations"]==[]
    ident=add(root,files,store)
    a=store.list(root=str(root),path="note.md")["annotations"][0]
    assert a["anchor"]["exact"]=="LeafLoom"
    store.message(root=str(root),path="note.md",annotation_id=ident,content="Reply",parent_id=a["messages"][0]["id"])
    store.edit_message(root=str(root),path="note.md",annotation_id=ident,
        message_id=a["messages"][0]["id"],revision=1,content="Edited")
    with pytest.raises(ConflictError):
        store.edit_message(root=str(root),path="note.md",annotation_id=ident,
            message_id=a["messages"][0]["id"],revision=1,content="Stale")
    a=store.list(root=str(root),path="note.md")["annotations"][0]
    store.edit(root=str(root),path="note.md",annotation_id=ident,revision=a["revision"],status="resolved")
    a=Annotations(store.config,files).list(root=str(root),path="note.md")["annotations"][0]
    assert a["status"]=="resolved" and a["messages"][0]["content"]=="Edited"
    with pytest.raises(ConflictError):
        store.edit(root=str(root),path="note.md",annotation_id=ident,revision=1,status="open")

def test_highlight_page_comment_and_delete(fixture):
    root,files,store=fixture
    add(root,files,store,kind="highlight",content="")
    page=store.create(root=str(root),path="note.md",kind="comment",content="Page review")["id"]
    rows=store.list(root=str(root),path="note.md")["annotations"]
    assert rows[0]["type"]=="highlight" and rows[1]["anchor"] is None
    store.remove(root=str(root),path="note.md",annotation_id=page,revision=1)
    assert len(store.list(root=str(root),path="note.md")["annotations"])==1

def test_utf16_and_stale_content(fixture):
    root,files,store=fixture
    add(root,files,store,kind="highlight",content="")
    etag,anchor=range_for(files)
    invalid=dict(anchor, **{"from":anchor["from"]-1,"to":anchor["to"]-1})
    with pytest.raises(ConflictError):
        store.create(root=str(root),path="note.md",kind="highlight",anchor=invalid,etag=etag)
    (root/"note.md").write_text("Externally updated",encoding="utf-8")
    with pytest.raises(ConflictError):
        store.create(root=str(root),path="note.md",kind="highlight",anchor=anchor,etag=etag)

def test_move_archive_recreate_restore(fixture):
    root,files,store=fixture
    key=add(root,files,store);doc_id=store.list(root=str(root),path="note.md")["document_id"]
    files.move("note.md","moved.md")
    assert store.list(root=str(root),path="moved.md")["document_id"]==doc_id
    trash=files.delete("moved.md")
    (root/"moved.md").write_text("Unrelated new note",encoding="utf-8")
    assert store.list(root=str(root),path="moved.md")["annotations"]==[]
    (root/"moved.md").unlink()
    files.restore("trash",trash["id"])
    assert store.list(root=str(root),path="moved.md")["annotations"][0]["id"]==key

def test_directory_move_and_root_scope(fixture):
    root,files,store=fixture
    (root/"dir").mkdir();(root/"dir"/"child.md").write_text("child",encoding="utf-8")
    store.create(root=str(root),path="dir/child.md",kind="comment",content="Page")
    files.move('dir','newdir')
    assert len(store.list(root=str(root),path="newdir/child.md")["annotations"])==1
    with pytest.raises(ConflictError):
        store.list(root=str(root/"other"),path="newdir/child.md")
    with pytest.raises(ValueError):
        store.list(root=str(root),path="../other.md")

def test_undo_move_restores_comments(fixture):
    root,files,store=fixture
    key=add(root,files,store)
    journal=files.move('note.md','moved.md')
    assert store.list(root=str(root),path='moved.md')['annotations'][0]['id']==key
    files.restore('operations',journal['operation_id'])
    assert store.list(root=str(root),path='note.md')['annotations'][0]['id']==key


def test_permanent_trash_clear_purges_annotation_data(fixture):
    root,files,store=fixture
    add(root,files,store)
    key=files.delete('note.md')['id']
    assert (root/'.vault-rag'/'annotations.sqlite').exists()
    files.clear_trash(expected_root=str(root))
    with sqlite3.connect(root/'.vault-rag'/'annotations.sqlite') as db:
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM annotations').fetchone()[0] == 0


def test_future_schema_rejected(fixture):
    root,files,store=fixture
    store.create(root=str(root),path="note.md",kind="comment",content="Page review")
    database=root/".vault-rag"/"annotations.sqlite"
    with sqlite3.connect(database) as conn:conn.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="更高版本"):
        store.list(root=str(root),path="note.md")


def test_annotation_history_round_trip_preserves_thread_and_source(fixture):
    root, files, store = fixture
    scope = dict(root=str(root), path='note.md')
    original = (root / 'note.md').read_bytes()
    operations = []
    created = store.create(**scope, kind='comment', content='First', author='Reviewer')
    operations.append(created['history_id'])
    ident = created['id']
    thread = lambda: store.list(**scope)['annotations'][0]
    initial = thread()
    operations.append(store.message(**scope, annotation_id=ident, content='Reply',
                                    parent_id=initial['messages'][0]['id'])['history_id'])
    operations.append(store.edit_message(**scope, annotation_id=ident,
        message_id=initial['messages'][0]['id'], revision=1, content='Edited')['history_id'])
    etag, anchor = range_for(files)
    operations.append(store.edit(**scope, annotation_id=ident, revision=thread()['revision'],
        status='resolved', color='blue', anchor_update=True, anchor=anchor, etag=etag)['history_id'])
    complete = thread()
    operations.append(store.remove(**scope, annotation_id=ident,
                                   revision=complete['revision'])['history_id'])
    assert store.list(**scope)['annotations'] == []
    # Undo delete, relink/status, edit, reply and creation, then redo in order.
    for history_id in reversed(operations):
        store.travel(**scope, history_id=history_id, direction='undo')
    assert store.list(**scope)['annotations'] == []
    for history_id in operations[:-1]:
        store.travel(**scope, history_id=history_id, direction='redo')
    restored = thread()
    assert restored['id'] == complete['id']
    assert restored['created_at'] == complete['created_at']
    assert restored['revision'] > complete['revision']
    assert restored['anchor'] == anchor
    assert restored['status'] == 'resolved' and restored['color'] == 'blue'
    for before, after in zip(complete['messages'], restored['messages']):
        for key in ('id', 'parent_id', 'annotation_id', 'content', 'author', 'created_at'):
            assert before[key] == after[key]
        assert after['revision'] > before['revision']
    # Repeated replay must rebase adjacent snapshots without reviving stale revisions.
    store.travel(**scope, history_id=operations[-1], direction='redo')
    store.travel(**scope, history_id=operations[-1], direction='undo')
    assert thread()['revision'] > restored['revision']
    assert (root / 'note.md').read_bytes() == original


def test_annotation_history_conflict_and_identity_boundaries(fixture):
    root, files, store = fixture
    scope = dict(root=str(root), path='note.md')
    created = store.create(**scope, kind='comment', content='Review')
    message = store.list(**scope)['annotations'][0]['messages'][0]
    # Another service/MCP edit must block undo of the original creation.
    other = Annotations(store.config, files)
    edited = other.edit_message(**scope, annotation_id=created['id'],
        message_id=message['id'], revision=message['revision'], content='External edit')
    with pytest.raises(ConflictError):
        store.travel(**scope, history_id=created['history_id'], direction='undo')
    assert store.list(**scope)['annotations'][0]['messages'][0]['content'] == 'External edit'
    store.travel(**scope, history_id=edited['history_id'], direction='undo')
    store.travel(**scope, history_id=created['history_id'], direction='undo')
    with pytest.raises(ConflictError):
        store.travel(**scope, history_id=created['history_id'], direction='undo')
    (root / 'other.md').write_text('Unrelated', encoding='utf-8')
    with pytest.raises(ConflictError):
        store.travel(root=str(root), path='other.md', history_id=created['history_id'], direction='redo')
    with pytest.raises(ConflictError):
        store.travel(root=str(root / 'wrong'), path='note.md', history_id=created['history_id'], direction='redo')
    files.delete('note.md')
    (root / 'note.md').write_text('New identity', encoding='utf-8')
    with pytest.raises(ConflictError):
        store.travel(**scope, history_id=created['history_id'], direction='redo')


def test_highlight_history_and_v1_upgrade(fixture):
    root, files, store = fixture
    scope = dict(root=str(root), path='note.md')
    etag, anchor = range_for(files)
    created = store.create(**scope, kind='highlight', anchor=anchor, etag=etag)
    database = root / '.vault-rag' / 'annotations.sqlite'
    # Model the schema before history support, preserving existing annotations.
    with sqlite3.connect(database) as db:
        db.execute('DROP TABLE annotation_history')
        db.execute('PRAGMA user_version=1')
    before = store.list(**scope)['annotations'][0]
    edited = store.edit(**scope, annotation_id=created['id'], revision=before['revision'], color='pink')
    store.travel(**scope, history_id=edited['history_id'], direction='undo')
    assert store.list(**scope)['annotations'][0]['color'] == 'yellow'
    store.travel(**scope, history_id=edited['history_id'], direction='redo')
    assert store.list(**scope)['annotations'][0]['color'] == 'pink'
    with sqlite3.connect(database) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2


def test_annotation_history_browser_api_and_csrf(fixture):
    from starlette.testclient import TestClient
    from vault_rag.knowledge import Runtime
    from vault_rag.web_server import create_app
    root, files, store = fixture
    runtime = Runtime(store.config)
    app = create_app(store.config, runtime, start_background=False)
    try:
        with TestClient(app, base_url='http://127.0.0.1:18080') as client:
            token = (store.config.directory / 'auth-token').read_text().strip()
            client.cookies.set('vault_session', token)
            csrf = {'X-Vault-CSRF': app.state.csrf}
            body = dict(root=str(root), path='note.md')
            response = client.post('/api/annotations', headers=csrf,
                json=dict(body, type='comment', content='Browser comment'))
            assert response.status_code == 200, response.text
            change = dict(body, history_id=response.json()['history_id'], direction='undo')
            assert client.post('/api/annotations/history', json=change).status_code == 403
            assert client.post('/api/annotations/history', headers=csrf, json=change).status_code == 200
            assert store.list(**body)['annotations'] == []
            change['direction'] = 'redo'
            assert client.post('/api/annotations/history', headers=csrf, json=change).status_code == 200
            assert store.list(**body)['annotations'][0]['messages'][0]['content'] == 'Browser comment'
            assert client.post('/api/annotations/history', headers=csrf, json=change).status_code == 409
    finally:
        runtime.stop()
