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
    store.list(root=str(root),path="note.md")
    database=root/".vault-rag"/"annotations.sqlite"
    with sqlite3.connect(database) as conn:conn.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="更高版本"):
        store.list(root=str(root),path="note.md")
