"""Versioned, authenticated database packages. The filename is the public label."""
from io import BytesIO
import json
import secrets
from zipfile import BadZipFile, ZipFile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from vault_rag import locked_photos
from vault_rag.local_state import relative

MAGIC = b'LLDB\x01'
KEY_SIZE = 81  # Version 1 key envelope used by locked_photos.wrap_key.
HEADER_SIZE = len(MAGIC) + KEY_SIZE
MAX_BYTES = 256 * 1024 * 1024
MANIFEST = '.database-manifest'


def encrypted(path):
    try:
        with path.open('rb') as stream:
            return stream.read(len(MAGIC)) == MAGIC
    except FileNotFoundError:
        return False


def header(path):
    with path.open('rb') as stream:
        data = stream.read(HEADER_SIZE)
    if len(data) != HEADER_SIZE or not data.startswith(MAGIC):
        raise ValueError('db.securityInvalid')
    return data


def new_key(password):
    if not isinstance(password, str) or len(password) < 12 or len(password.encode()) > 1024:
        raise ValueError('db.securityPassphraseLength')
    secret = AESGCM.generate_key(bit_length=256)
    return secret, MAGIC + locked_photos.wrap_key(secret, password)


def encode(secret, prefix, files, directories, version):
    if sum(len(content) for content, _, _ in files.values()) > MAX_BYTES:
        raise ValueError('db.securityTooLarge')
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        timestamps = {}
        for path, (content, modified, created) in files.items():
            archive.writestr(path, content)
            timestamps[path] = (modified, created)
        archive.writestr(MANIFEST, json.dumps({
            'timestamps': timestamps, 'directories': sorted(directories), 'version': version,
        }, ensure_ascii=False))
    if output.tell() > MAX_BYTES:
        raise ValueError('db.securityTooLarge')
    nonce = secrets.token_bytes(12)
    return prefix + nonce + AESGCM(secret).encrypt(nonce, output.getvalue(), prefix)


def decode(path, secret, prefix):
    with path.open('rb') as stream:
        actual = stream.read(HEADER_SIZE)
        blob = stream.read(MAX_BYTES + 29)
    if actual != prefix or len(blob) < 28 or len(blob) > MAX_BYTES + 28:
        raise ValueError('db.securityInvalid')
    try:
        plain = AESGCM(secret).decrypt(blob[:12], blob[12:], prefix)
        with ZipFile(BytesIO(plain)) as archive:
            entries = archive.infolist()
            if sum(entry.file_size for entry in entries) > MAX_BYTES:
                raise ValueError()
            manifest = json.loads(archive.read(MANIFEST))
            timestamps, directories = manifest['timestamps'], set(manifest['directories'])
            if (len(entries) != len(timestamps) + 1 or
                    any(relative(name) != name for name in set(timestamps) | directories)):
                raise ValueError()
            files = {name: (archive.read(name), modified, created)
                     for name, (modified, created) in timestamps.items()}
    except (InvalidTag, BadZipFile, KeyError, TypeError, ValueError, OSError) as exc:
        raise ValueError('db.securityInvalid') from exc
    return files, directories, manifest['version']
