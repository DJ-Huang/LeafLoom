"""Vault-level profiles for protected images and captions in database record folders."""
from dataclasses import dataclass
import json

from . import locked_photos as crypto


SETTINGS = 'protected-media.json'
KEY_FILE = 'protected-media.key'
LEGACY_SCOPES = 'role-photos.scopes.json'
ASSET_DIR = '_encrypted-photos'


def relative(value, *, root_allowed=False):
    if value == '' and root_allowed:
        return ''
    if not isinstance(value, str) or not value or any(c in value for c in ('\\', ':', '\x00')):
        raise ValueError('Invalid gallery path')
    if any(not part or part.startswith('.') for part in value.split('/')):
        raise ValueError('Invalid gallery path')
    return value


def parent(value):
    return relative(value).rpartition('/')[0]


def child(folder, name):
    return f'{folder}/{name}' if folder else name


@dataclass(frozen=True)
class Gallery:
    folder: str
    assets: str
    captions: bool
    legacy: bool = False

def galleries(root):
    state = root / '.vault-rag'
    previous = state / LEGACY_SCOPES
    settings = state / SETTINGS
    if previous.is_symlink() or settings.is_symlink():
        raise ValueError('Protected media settings cannot be links')
    result = {}
    if previous.is_file():
        scopes = json.loads(previous.read_bytes())
        if not isinstance(scopes, list):
            raise ValueError('Invalid legacy gallery settings')
        has_captions = (state / crypto.CAPTION_MARKER).is_file()
        for name in scopes:
            folder = relative(name, root_allowed=True)
            result[folder] = Gallery(folder, child(folder, '图片'), has_captions, legacy=True)
    if settings.is_file():
        value = json.loads(settings.read_bytes())
        if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('galleries'), list):
            raise ValueError('Invalid protected media settings')
        for row in value['galleries']:
            if not isinstance(row, dict) or set(row) != {'folder', 'captions'} or type(row['captions']) is not bool:
                raise ValueError('Invalid protected gallery settings')
            folder = relative(row['folder'], root_allowed=True)
            if folder in result:
                raise ValueError('Protected gallery folder is already configured')
            result[folder] = Gallery(folder, child(folder, ASSET_DIR), row['captions'])
    if set(result) & {g.assets for g in result.values()}:
        raise ValueError('Protected media folder also contains gallery records')
    return result


def envelope_path(storage):
    legacy, current = storage / crypto.KEY_FILE, storage / KEY_FILE
    if legacy.is_symlink() or current.is_symlink():
        raise ValueError('Protected media key cannot be a link')
    if legacy.is_file():
        if current.is_file() and current.read_bytes() != legacy.read_bytes():
            raise ValueError('Protected media key files do not match')
        return legacy
    return current


def add_gallery(root, folder, captions):
    folder = relative(folder, root_allowed=True)
    current = galleries(root)
    if folder in current:
        return current[folder]
    profile = Gallery(folder, child(folder, ASSET_DIR), captions)
    if profile.assets in current or folder in {g.assets for g in current.values()}:
        raise ValueError('Protected media folder overlaps another gallery')
    records = [{'folder': g.folder, 'captions': g.captions} for g in current.values() if not g.legacy]
    records.append({'folder': profile.folder, 'captions': profile.captions})
    crypto.atomic_bytes(root / '.vault-rag' / SETTINGS, json.dumps({'version': 1, 'galleries': records},
                        ensure_ascii=False).encode())
    return profile


def asset_gallery(root, path):
    folder = parent(path)
    return next((g for g in galleries(root).values() if g.assets == folder), None)
