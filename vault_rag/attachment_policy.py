"""Workspace-local attachment types, independent of filename/link discovery."""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath


# Migration retains its narrower safety rules even when users add file types.
MIGRATION_EXTENSIONS = frozenset({
    '.png','.jpg','.jpeg','.gif','.webp','.avif','.bmp','.ico','.tif','.tiff',
    '.pdf','.mp3','.m4a','.wav','.ogg','.flac','.aac','.mp4','.mov','.webm','.m4v','.avi',
    '.doc','.docx','.xls','.xlsx','.ppt','.pptx','.odt','.ods','.odp',
    '.zip','.7z','.rar','.tar','.gz','.bz2','.epub','.woff','.woff2','.ttf','.otf',
})
DEFAULT_EXTENSIONS = tuple(sorted(MIGRATION_EXTENSIONS | {'.svg', '.unitypackage'}))


def normalize_extensions(value):
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError('Invalid attachment file types')
    result = set()
    for extension in value:
        if not isinstance(extension, str):
            raise ValueError('Invalid attachment file types')
        extension = extension.strip().lower()
        if not extension.startswith('.'):
            extension = '.' + extension
        if len(extension) > 64 or not re.fullmatch(r'\.[a-z0-9_+\-]+(?:\.[a-z0-9_+\-]+)*', extension):
            raise ValueError('Enter filename extensions without wildcards or paths')
        result.add(extension)
    return sorted(result)


def extensions_for(files):
    """Read through the protected state path without requiring a server/manifest."""
    root = str(files.config.root)
    path = files.state_path('remote-attachments', 'settings.json')
    if path.is_file():
        settings = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(settings, dict) or settings.get('root') != root:
            raise ValueError('Attachment storage settings belong to another folder')
    else:
        settings = files.config.data.get('remote_attachments', {})
        if settings.get('root') != root:
            settings = {}
    return tuple(normalize_extensions(settings.get('allowed_extensions', list(DEFAULT_EXTENSIONS))))


def allows(path, extensions):
    return PurePosixPath(path).name.lower().endswith(tuple(extensions))


class AttachmentTypeError(ValueError):
    pass


def require_allowed(files, path):
    if not allows(path, extensions_for(files)):
        raise AttachmentTypeError('This file type is not allowed for attachments; update Attachment file types in Settings')


def register_policy(db, extensions):
    db.create_function('attachment_allowed', 1, lambda path: int(allows(path, extensions)), deterministic=True)
