"""Follow explicit local file moves without replacing annotation callbacks."""
from __future__ import annotations

import logging


class AttachmentMetadataHooks:
    def __init__(self, runtime, remote, previous):
        self.runtime = runtime
        self.remote = remote
        self.previous = previous

    def annotation_changed(self, action, **fields):
        if action != 'move':
            return self.previous(action, **fields)
        root = str(self.runtime.config.root)
        moves = {fields['source']: fields['destination']}
        try:
            result = self.previous(action, **fields)
        except BaseException:
            # The Files transaction has already completed. Preserve the original
            # annotation error while still following the file that was moved.
            try:
                self.remote.sync_local_paths(root, moves)
            except Exception:
                logging.getLogger(__name__).warning('Attachment metadata synchronization failed after a local move')
            raise
        self.remote.sync_local_paths(root, moves)
        return result

    def prepare_migration(self, job):
        """Freeze identities before changing files, for safe replay/rollback."""
        if job.get('kind') == 'trash' or 'local_metadata_moves' in job:
            return False
        moves = job.get('moves', [])
        identities = self.remote.snapshot_local_metadata(job['root'], [m['source'] for m in moves])
        job['local_metadata_moves'] = [dict(source=m['source'], destination=m['destination'],
                                          asset_id=identities[m['source']])
                                       for m in moves if m['source'] in identities]
        return True

    def sync_migration(self, job, *, reverse=False):
        # Older completed journals never recorded source identities. In
        # particular, do not infer ownership from a stale destination record.
        moves = job.get('local_metadata_moves', [])
        if reverse:
            moves = [dict(source=m['destination'], destination=m['source'], asset_id=m['asset_id'])
                     for m in moves]
        if moves:
            return self.remote.sync_local_paths(job['root'], moves)
        return {'updated': 0}


def install_attachment_metadata_hooks(runtime, remote):
    """Install once, after the application's existing annotation callback."""
    existing = getattr(runtime, 'attachment_metadata', None)
    if existing is not None:
        if existing.remote is not remote:
            raise ValueError('Attachment metadata hooks are already installed')
        return existing
    hooks = AttachmentMetadataHooks(runtime, remote, runtime.files.annotation_changed)
    runtime.files.annotation_changed = hooks.annotation_changed
    runtime.attachment_metadata = hooks
    return hooks
