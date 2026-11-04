"""Explicit metadata-only setup/rebuild jobs; source files are never modified."""
import json
import sqlite3
import threading
import time
import uuid
from contextlib import closing

from vault_rag.attachment_policy import DEFAULT_EXTENSIONS, extensions_for, register_policy
from vault_rag.local_state import ConflictError, atomic_write
from vault_rag.platform_support import private_file_mode


class AttachmentIndexJobs:
    def __init__(self, runtime):
        self.runtime = runtime
        self.index = runtime.files.attachments
        self.lock = threading.RLock()
        self.thread = None
        self.cancel = threading.Event()
        self.job = None

    def _guard(self, root):
        if root and root != str(self.runtime.config.root):
            raise ConflictError('Connected folder changed')

    def _save(self, files, job):
        path = files.state_path('attachment-index-job.json')
        path.parent.mkdir(exist_ok=True)
        atomic_write(path, json.dumps(job).encode())
        private_file_mode(path)

    def status(self, root=''):
        self._guard(root)
        files = self.index._snapshot()
        root = str(files.config.root)
        result = dict(state='uninitialized', schema_version=None, current_version=1, usable=False)
        path = files.state_path('attachments.sqlite')
        try:
            if path.exists():
                for suffix in ('-journal', '-wal', '-shm'):
                    files.state_path('attachments.sqlite' + suffix)
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                    register_policy(db, extensions_for(files))
                    version = db.execute('PRAGMA user_version').fetchone()[0]
                    result['schema_version'] = version
                    if version > 1:
                        result.update(state='unsupported', error='Attachment index requires a newer LeafLoom; database preserved')
                    elif version == 0:
                        result['state'] = 'needs_upgrade'
                    else:
                        row = db.execute('SELECT scanned_at FROM state WHERE root=?', (root,)).fetchone()
                        if row:
                            result.update(state='ready', usable=True, last_scanned_at=row[0],
                                          files=db.execute('SELECT count(*) FROM assets WHERE attachment_allowed(path)=1').fetchone()[0])
        except (OSError, ValueError, sqlite3.Error) as error:
            result.update(state='failed', error=str(error))
        if result['state'] == 'unsupported':
            return self._workspace_status(result, root)
        with self.lock:
            job = self.job if self.job and self.job['root'] == root else None
            if job is None:
                record = files.state_path('attachment-index-job.json')
                if record.exists():
                    try:
                        candidate = json.loads(record.read_text())
                        if candidate.get('root') == root:
                            job = candidate
                    except (OSError, ValueError):
                        pass
            if job:
                state = job['state']
                if state == 'building' and not (self.thread and self.thread.is_alive() and self.job is job):
                    state = 'interrupted'
                # A later unified setup may have rebuilt this cache without
                # starting a separate maintenance job. Do not resurrect its old error.
                if state != 'building' and result['usable'] and result.get('last_scanned_at',0) > job.get('started_at',float('inf')):
                    state = 'ready'
                if state != 'ready':
                    result['state'] = state
                result.update(job_id=job['id'], progress={'done': job.get('done', 0)})
                if state != 'ready' and job.get('error'):
                    result['error'] = job['error']
        self._guard(root)
        return self._workspace_status(result, root)

    def _workspace_status(self, local, root):
        """Upload destination never hides an already configured catalog."""
        remote = getattr(self.runtime, 'remote_attachments', None)
        settings = remote._settings(root) if remote else {'allowed_extensions': list(extensions_for(self.index._snapshot()))}
        default = settings.get('default_source', 'local')
        result = {**local, 'local_index': dict(local), 'storage_mode': 'local' if default == 'local' else 'server',
                  'default_storage_id': default, 'allowed_extensions': settings.get('allowed_extensions', list(DEFAULT_EXTENSIONS))}
        if settings.get('sources'):
            result['usable'] = True
            if not local['usable'] and local['state'] != 'building':
                result['state'] = 'ready'
                result.pop('error', None)
        return result

    def start(self, root, *, guard=None):
        self._guard(root)
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ConflictError('Attachment index build already running')
            self.runtime.files.ensure_mutable()
            if self.status(root)['local_index']['state'] == 'unsupported':
                raise ValueError('Attachment index requires a newer LeafLoom; database preserved')
            files = self.index._snapshot()
            job = dict(id=uuid.uuid4().hex, root=str(files.config.root), state='building', done=0,
                       started_at=time.time())
            self.cancel = threading.Event()
            self.job = job
            self._save(files, job)
            self.thread = threading.Thread(target=self._worker, args=(files, job, self.cancel, guard), daemon=True)
            self.thread.start()
        return self.status(root)

    def _worker(self, files, job, cancel, guard=None):
        try:
            def progress(done):
                if guard is not None:guard()
                self._guard(job['root'])
                with self.lock:
                    job['done'] = done
                    self._save(files, job)
            # Bind root before refresh snapshots it, and serialize with lazy lookup.
            with self.index.lock:
                if guard is not None:guard()
                self._guard(job['root'])
                self.index.refresh(cancel=cancel, progress=progress)
            job['state'] = 'ready'
        except InterruptedError as error:
            job.update(state='cancelled', error=str(error))
        except Exception as error:
            job.update(state='failed', error=str(error))
        finally:
            with self.lock:
                self._save(files, job)

    def stop(self):
        self.cancel.set()
        if self.thread:
            self.thread.join(timeout=2)

    def cancel_job(self, root):
        self._guard(root)
        self.cancel.set()
        return self.status(root)
