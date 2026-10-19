"""User-owned annotations, independent from Markdown and rebuildable indexes."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from vault_rag.local_state import ConflictError, relative, under

ALLOWED_TYPES = {"highlight", "comment"}
COLORS = {"yellow", "blue", "green", "pink", "purple"}
MAX_QUOTE = 12000
MAX_MESSAGE = 20000
MAX_ANNOTATIONS = 5000


class Annotations:
    """A durable per-vault database. Reads never load annotation text into RAG."""

    def __init__(self, config, files):
        self.config, self.files = config, files
        self.lock = threading.RLock()

    def _validate_root(self, root):
        actual = str(self.config.root)
        if root != actual:
            raise ConflictError("关联目录已切换，请重新打开笔记")
        return actual

    def _validate_note(self, root, path):
        self._validate_root(root)
        rel = relative(path)
        note = self.config.path_for(rel)
        if note.suffix.lower() not in (".md", ".txt"):
            raise ValueError("当前仅支持 Markdown 和纯文本标注")
        if not note.is_file():
            raise FileNotFoundError(rel)
        return rel

    @contextmanager
    def _database(self, root):
        self._validate_root(root)
        path = self.files.state_path("annotations.sqlite")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and (not path.is_file() or path.is_symlink()):
            raise ValueError("标注数据库路径不安全")
        db = sqlite3.connect(path, timeout=8)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=8000")
            current = db.execute("PRAGMA user_version").fetchone()[0]
            if current > 2:
                raise ValueError("标注数据库来自更高版本，拒绝覆盖")
            if current == 0:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    trash_key TEXT,
                    created_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS annotation_active_path
                    ON documents(path) WHERE trash_key IS NULL;
                CREATE TABLE IF NOT EXISTS annotations (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id),
                    kind TEXT NOT NULL CHECK(kind IN ('highlight','comment')),
                    anchor_json TEXT,
                    color TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('open','resolved')),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS annotation_document ON annotations(document_id,created_at);
                CREATE TABLE IF NOT EXISTS annotation_messages (
                    id TEXT PRIMARY KEY,
                    annotation_id TEXT NOT NULL REFERENCES annotations(id) ON DELETE CASCADE,
                    parent_id TEXT REFERENCES annotation_messages(id),
                    author TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS annotation_message_thread
                    ON annotation_messages(annotation_id,created_at);
                PRAGMA user_version=1;
                """)
            if current < 2:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS annotation_history (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    annotation_id TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    undone INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS annotation_history_document
                    ON annotation_history(document_id,created_at);
                PRAGMA user_version=2;
                """)
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _document(db, path, create=False):
        row = db.execute("SELECT id FROM documents WHERE path=? AND trash_key IS NULL", (path,)).fetchone()
        if row or not create:
            return row["id"] if row else None
        key = uuid.uuid4().hex
        db.execute("INSERT INTO documents(id,path,created_at) VALUES(?,?,?)", (key, path, time.time()))
        return key

    @staticmethod
    def _annotation(db, document_id, annotation_id):
        row = db.execute(
            "SELECT * FROM annotations WHERE id=? AND document_id=?",
            (annotation_id, document_id),
        ).fetchone()
        if row is None:
            raise ValueError("找不到该标注或评论")
        return row

    @staticmethod
    def _version(row, expected):
        if type(expected) is not int or expected != row["revision"]:
            raise ConflictError("标注已经被修改，请刷新评论后重试")

    @staticmethod
    def _snapshot(db, annotation_id):
        row = db.execute("SELECT * FROM annotations WHERE id=?", (annotation_id,)).fetchone()
        if row is None:
            return "null"
        value = dict(row)
        value["messages"] = [dict(message) for message in db.execute(
            "SELECT * FROM annotation_messages WHERE annotation_id=? ORDER BY created_at,id",
            (annotation_id,))]
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _record(self, db, doc_id, annotation_id, before):
        after = self._snapshot(db, annotation_id)
        key = uuid.uuid4().hex
        db.execute("""INSERT INTO annotation_history
            (id,document_id,annotation_id,before_json,after_json,created_at) VALUES(?,?,?,?,?,?)
        """, (key, doc_id, annotation_id, before, after, time.time()))
        # Match the editor's bounded history; these snapshots are user data, not an index.
        db.execute("""DELETE FROM annotation_history WHERE id IN (
            SELECT id FROM annotation_history WHERE document_id=? ORDER BY created_at DESC,id DESC
            LIMIT -1 OFFSET 200)
        """, (doc_id,))
        return key

    def travel(self, *, root, path, history_id, direction):
        """Replay only server-owned snapshots, with full-thread conflict checks."""
        if direction not in ("undo", "redo"):
            raise ValueError("无效的撤销或重做操作")
        with self.config.lock, self.lock:
            path = self._validate_note(root, path)
            with self._database(root) as db:
                db.execute("BEGIN IMMEDIATE")
                doc_id = self._document(db, path)
                entry = db.execute("SELECT * FROM annotation_history WHERE id=? AND document_id=?",
                                   (history_id, doc_id)).fetchone()
                if entry is None:
                    raise ConflictError("标注撤销记录已失效，请重新打开笔记")
                undo = direction == "undo"
                expected, target = (entry["after_json"], entry["before_json"]) if undo else (entry["before_json"], entry["after_json"])
                if bool(entry["undone"]) == undo or self._snapshot(db, entry["annotation_id"]) != expected:
                    raise ConflictError("标注已经被修改，无法撤销或重做；请刷新评论后重试")
                current, replacement = json.loads(expected), json.loads(target)
                db.execute("DELETE FROM annotations WHERE id=?", (entry["annotation_id"],))
                if replacement is not None:
                    count = db.execute("SELECT COUNT(*) FROM annotations WHERE document_id=?", (doc_id,)).fetchone()[0]
                    if count >= MAX_ANNOTATIONS:
                        raise ValueError("单篇文档的标注数量已达到上限")
                    replacement["revision"] = max(replacement["revision"], (current or {}).get("revision", 0)) + 1
                    replacement["updated_at"] = time.time()
                    columns = [key for key in replacement if key != "messages"]
                    db.execute(f"INSERT INTO annotations({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                               [replacement[key] for key in columns])
                    current_messages = {m["id"]: m for m in (current or {}).get("messages", [])}
                    # Parents may share timestamps; insert parents before their replies.
                    pending = list(replacement["messages"])
                    inserted = set()
                    while pending:
                        ready = [message for message in pending if not message["parent_id"] or message["parent_id"] in inserted]
                        if not ready:
                            raise ValueError("评论回复关系无效")
                        for message in ready:
                            message["revision"] = max(message["revision"], current_messages.get(message["id"], {}).get("revision", 0)) + 1
                            message["updated_at"] = replacement["updated_at"]
                            columns = list(message)
                            db.execute(f"INSERT INTO annotation_messages({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                                       [message[key] for key in columns])
                            inserted.add(message["id"])
                            pending.remove(message)
                restored = self._snapshot(db, entry["annotation_id"])
                # Adjacent operations reference the same state. Rebase those exact
                # snapshots so repeated undo/redo keeps monotonically newer revisions.
                for column in ("before_json", "after_json"):
                    db.execute(f"UPDATE annotation_history SET {column}=? WHERE document_id=? AND annotation_id=? AND {column}=?",
                               (restored, doc_id, entry["annotation_id"], target))
                db.execute("UPDATE annotation_history SET undone=? WHERE id=?", (int(undo), history_id))
                return {"ok": True}

    def _anchor(self, path, root, anchor, etag):
        if anchor is None:
            return None
        if not isinstance(anchor, dict):
            raise ValueError("无效的文本锚点")
        start, end = anchor.get("from"), anchor.get("to")
        exact, prefix, suffix = anchor.get("exact"), anchor.get("prefix"), anchor.get("suffix")
        if (type(start) is not int or type(end) is not int or
            not isinstance(exact, str) or not isinstance(prefix, str) or
            not isinstance(suffix, str) or len(exact) > MAX_QUOTE or not exact or
            len(prefix) > 100 or len(suffix) > 100):
            raise ValueError("无效的选区与上下文")
        note = self.files.read(path)
        if note["root"] != root or etag != note["etag"]:
            raise ConflictError("正文已修改，请保存或刷新笔记后重新标注")
        # Browser/Tiptap offsets count UTF-16 code units, not Python code points.
        utf16 = note["text"].encode("utf-16-le")
        if start < 0 or end > len(utf16) // 2 or start >= end:
            raise ValueError("选区越出正文")
        try:
            selected = utf16[start*2:end*2].decode("utf-16-le")
        except UnicodeDecodeError:
            raise ValueError("选区不能截断 Unicode 字符") from None
        if selected != exact:
            raise ConflictError("文字位置已变化，请重新选择")
        return json.dumps({
            "from": start, "to": end, "exact": exact, "prefix": prefix, "suffix": suffix,
            "etag": etag,
        }, ensure_ascii=False)

    def list(self, *, root, path):
        with self.config.lock, self.lock:
            path = self._validate_note(root, path)
            database = self.files.state_path('annotations.sqlite')
            # Reads should work without initializing a database in a read-only vault.
            if not database.exists() and not database.is_symlink():
                return {'annotations': [], 'document_id': None}
            with self._database(root) as db:
                doc_id = self._document(db, path)
                if not doc_id:
                    return {"annotations": [], "document_id": None}
                records = db.execute(
                    "SELECT * FROM annotations WHERE document_id=? ORDER BY created_at,id LIMIT ?",
                    (doc_id, MAX_ANNOTATIONS + 1),
                ).fetchall()
                if len(records) > MAX_ANNOTATIONS:
                    raise ValueError("单篇文档的标注数量过多")
                annotations = []
                for row in records:
                    data = dict(row)
                    data["type"] = data.pop("kind")
                    data["anchor"] = json.loads(data.pop("anchor_json")) if data["anchor_json"] else None
                    data["messages"] = []
                    annotations.append(data)
                by_id = {row["id"]: row for row in annotations}
                for row in db.execute("""
                    SELECT m.* FROM annotation_messages m
                    JOIN annotations a ON a.id=m.annotation_id
                    WHERE a.document_id=? ORDER BY m.created_at,m.id
                """, (doc_id,)):
                    by_id[row["annotation_id"]]["messages"].append(dict(row))
                return {"document_id": doc_id, "annotations": annotations}

    def create(self, *, root, path, kind, anchor=None, etag=None,
               color="yellow", content="", author="Local user"):
        with self.config.lock, self.lock:
            path = self._validate_note(root, path)
            if kind not in ALLOWED_TYPES or color not in COLORS:
                raise ValueError("不支持的标注类型或颜色")
            if anchor is None and kind != "comment":
                raise ValueError("高亮必须选择文本")
            if not isinstance(content, str) or len(content) > MAX_MESSAGE:
                raise ValueError("评论长度超出限制")
            if kind == "comment" and not content.strip():
                raise ValueError("评论内容不能为空")
            if not isinstance(author, str) or not 1 <= len(author) <= 120:
                raise ValueError("评论作者无效")
            anchor_json = self._anchor(path, root, anchor, etag)
            with self._database(root) as db:
                db.execute("BEGIN IMMEDIATE")
                doc_id = self._document(db, path, create=True)
                count = db.execute("SELECT COUNT(*) FROM annotations WHERE document_id=?", (doc_id,)).fetchone()[0]
                if count >= MAX_ANNOTATIONS:
                    raise ValueError("单篇文档的标注数量已达到上限")
                key, now = uuid.uuid4().hex, time.time()
                db.execute("""
                    INSERT INTO annotations(id,document_id,kind,anchor_json,color,status,created_at,updated_at)
                    VALUES(?,?,?,?,?,'open',?,?)
                """, (key, doc_id, kind, anchor_json, color, now, now))
                if content.strip():
                    db.execute("""
                        INSERT INTO annotation_messages(id,annotation_id,parent_id,author,content,created_at,updated_at)
                        VALUES(?,?,NULL,?,?,?,?)
                    """, (uuid.uuid4().hex, key, author, content.strip(), now, now))
                return {"id": key, "history_id": self._record(db, doc_id, key, "null")}

    def edit(self, *, root, path, annotation_id, revision, status=None,
             color=None, anchor_update=False, anchor=None, etag=None):
        with self.config.lock, self.lock:
            path = self._validate_note(root, path)
            with self._database(root) as db:
                db.execute("BEGIN IMMEDIATE")
                doc_id = self._document(db, path)
                row = self._annotation(db, doc_id, annotation_id)
                self._version(row, revision)
                before = self._snapshot(db, annotation_id)
                if status is not None and status not in ("open", "resolved"):
                    raise ValueError("评论状态无效")
                if color is not None and color not in COLORS:
                    raise ValueError("标注颜色无效")
                anchor_json = (self._anchor(path, root, anchor, etag)
                               if anchor_update else row["anchor_json"])
                db.execute("""
                    UPDATE annotations SET status=?,color=?,anchor_json=?,updated_at=?,revision=revision+1
                    WHERE id=?
                """, (status or row["status"], color or row["color"],
                      anchor_json, time.time(), annotation_id))
                return {"ok": True, "history_id": self._record(db, doc_id, annotation_id, before)}

    def remove(self, *, root, path, annotation_id, revision):
        with self.config.lock, self.lock:
            path = self._validate_note(root, path)
            with self._database(root) as db:
                db.execute("BEGIN IMMEDIATE")
                doc_id = self._document(db, path)
                row = self._annotation(db, doc_id, annotation_id)
                self._version(row, revision)
                before = self._snapshot(db, annotation_id)
                db.execute("DELETE FROM annotations WHERE id=?", (annotation_id,))
                return {"ok": True, "history_id": self._record(db, doc_id, annotation_id, before)}

    def message(self, *, root, path, annotation_id, content, author="Local user",
                parent_id=None):
        with self.config.lock, self.lock:
            path = self._validate_note(root, path)
            if not isinstance(content, str) or not content.strip() or len(content) > MAX_MESSAGE:
                raise ValueError("评论内容不能为空或超出限制")
            if not isinstance(author, str) or not 1 <= len(author) <= 120:
                raise ValueError("评论作者无效")
            with self._database(root) as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._annotation(db, self._document(db, path), annotation_id)
                before = self._snapshot(db, annotation_id)
                if row["kind"] != "comment":
                    raise ValueError("只有评论线程可以回复")
                if parent_id and not db.execute(
                    "SELECT 1 FROM annotation_messages WHERE id=? AND annotation_id=?",
                    (parent_id, annotation_id),
                ).fetchone():
                    raise ValueError("回复目标不存在")
                key, now = uuid.uuid4().hex, time.time()
                db.execute("""
                    INSERT INTO annotation_messages(id,annotation_id,parent_id,author,content,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?)
                """, (key, annotation_id, parent_id, author, content.strip(), now, now))
                db.execute("UPDATE annotations SET updated_at=?,revision=revision+1 WHERE id=?",
                           (now, annotation_id))
                return {"id": key, "history_id": self._record(db, row["document_id"], annotation_id, before)}

    def edit_message(self, *, root, path, annotation_id, message_id, revision, content):
        with self.config.lock, self.lock:
            path = self._validate_note(root, path)
            if not isinstance(content, str) or not content.strip() or len(content) > MAX_MESSAGE:
                raise ValueError("评论内容不能为空或超出限制")
            with self._database(root) as db:
                db.execute("BEGIN IMMEDIATE")
                annotation = self._annotation(db, self._document(db, path), annotation_id)
                before = self._snapshot(db, annotation_id)
                row = db.execute(
                    "SELECT * FROM annotation_messages WHERE id=? AND annotation_id=?",
                    (message_id, annotation_id),
                ).fetchone()
                if row is None:
                    raise ValueError("评论消息不存在")
                self._version(row, revision)
                db.execute("""
                    UPDATE annotation_messages SET content=?,revision=revision+1,updated_at=? WHERE id=?
                """, (content.strip(), time.time(), message_id))
                db.execute("UPDATE annotations SET updated_at=?,revision=revision+1 WHERE id=?",
                           (time.time(), annotation_id))
                return {"ok": True, "history_id": self._record(db, annotation["document_id"], annotation_id, before)}

    def archive(self, *, root, path, trash_key):
        """Keep deleted note comments out of new files created at the same path."""
        if not re.fullmatch("[a-f0-9]{32}", trash_key):
            raise ValueError("无效的回收记录")
        with self.config.lock, self.lock, self._database(root) as db:
            path = relative(path)
            db.execute("""
                UPDATE documents SET trash_key=? WHERE trash_key IS NULL
                AND (path=? OR substr(path,1,?)=?)
            """, (trash_key, path, len(path)+1, path+"/"))

    def restore(self, *, root, trash_key):
        with self.config.lock, self.lock, self._database(root) as db:
            rows = db.execute("SELECT id,path FROM documents WHERE trash_key=?", (trash_key,)).fetchall()
            for row in rows:
                if self._document(db, row["path"]):
                    raise ConflictError("恢复评论时发现目标路径已存在其他文档")
            db.execute("UPDATE documents SET trash_key=NULL WHERE trash_key=?", (trash_key,))

    def purge_trash(self, *, root):
        """Permanently remove comments belonging to trash after an explicit trash clear."""
        with self.config.lock, self.lock, self._database(root) as db:
            db.execute('DELETE FROM annotations WHERE document_id IN '
                       '(SELECT id FROM documents WHERE trash_key IS NOT NULL)')
            db.execute('DELETE FROM documents WHERE trash_key IS NOT NULL')

    def move(self, *, root, source, destination):
        """Prefix-safe path update for both a note and a directory of notes."""
        with self.config.lock, self.lock, self._database(root) as db:
            source, destination = relative(source), relative(destination)
            rows = db.execute("""
                SELECT id,path FROM documents WHERE trash_key IS NULL
                AND (path=? OR substr(path,1,?)=?)
            """, (source, len(source)+1, source+"/")).fetchall()
            for row in rows:
                suffix = row["path"][len(source):]
                new_path = destination + suffix
                if self._document(db, new_path):
                    raise ConflictError("目标路径已存在其他标注记录")
                db.execute("UPDATE documents SET path=? WHERE id=?", (new_path, row["id"]))
            return {"moved": len(rows)}
