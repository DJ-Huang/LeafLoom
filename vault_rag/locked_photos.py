"""Version 1 photo envelope shared with LeafLoom's locked_photos module."""
import base64
import binascii
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

KEY_FILE = 'role-photos.key'
CAPTION_FIELD = 'photo_caption_cipher'
CAPTION_MARKER = 'role-photo-captions-v1'
CAPTION_PENDING = 'role-photo-captions-migrating'
CAPTION_TITLE = '角色照片'
MIGRATING = 'role-photos.migrating'
MAX_IMAGE = 32 * 1024 * 1024
EXTENSION = '.llphoto'
ASSET = re.compile(r'[0-9a-f]{64}\.llphoto')
KEY_MAGIC = b'LLPK\x01'
PHOTO_MAGIC = b'LLPH\x01'
BACKUP_MAGIC = b'LLPB\x01'
CAPTION_MAGIC = b'LLPC\x01'
IDLE_SECONDS = 1800


class Locked(RuntimeError):
    pass


class Busy(RuntimeError):
    pass


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        pending = Path(out.name)
        try:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            out.close()
            pending.unlink(missing_ok=True)
            raise
    try:
        os.replace(pending, path)
        if os.name != 'nt':
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        pending.unlink(missing_ok=True)


def _derive(password, salt):
    if not isinstance(password, str) or not 1 <= len(password.encode()) <= 1024:
        raise ValueError('Invalid photo password')
    return Argon2id(salt=salt, length=32, iterations=3, lanes=4, memory_cost=65536).derive(password.encode())


def wrap_key(key, password):
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = KEY_MAGIC + salt
    return header + nonce + AESGCM(_derive(password, salt)).encrypt(nonce, key, header)


def unwrap_key(envelope, password):
    if len(envelope) != 81 or not envelope.startswith(KEY_MAGIC):
        raise ValueError('Invalid photo key envelope')
    prefix = len(KEY_MAGIC)
    header = envelope[:prefix + 16]
    nonce = envelope[len(header):len(header) + 12]
    try:
        return AESGCM(_derive(password, header[prefix:])).decrypt(nonce, envelope[len(header) + 12:], header)
    except InvalidTag as exc:
        raise Locked('Incorrect photo password') from exc


def _subkey(key, purpose):
    return hmac.digest(key, b'LeafLoom photo v1/' + purpose, 'sha256')


def asset_name(key, scope, data):
    return hmac.new(_subkey(key, b'id'), scope.encode() + b'\0' + hashlib.sha256(data).digest(),
                    'sha256').hexdigest() + EXTENSION


def _aad(magic, scope, name):
    return magic + b'\0' + scope.encode() + b'\0' + name.encode()


def seal(key, scope, name, data, *, backup=False):
    if not 0 < len(data) <= MAX_IMAGE:
        raise ValueError('Invalid photo payload size')
    magic = BACKUP_MAGIC if backup else PHOTO_MAGIC
    nonce = secrets.token_bytes(12)
    compressed = zlib.compress(data, level=3)
    payload = b'\x01' + compressed if len(compressed) < len(data) else b'\x00' + data
    return magic + nonce + AESGCM(_subkey(key, magic)).encrypt(nonce, payload, _aad(magic, scope, name))


def open_payload(key, scope, name, data, *, backup=False):
    magic = BACKUP_MAGIC if backup else PHOTO_MAGIC
    if not data.startswith(magic) or not 34 < len(data) <= MAX_IMAGE + 34:
        raise ValueError('Invalid encrypted photo')
    offset = len(magic)
    try:
        payload = AESGCM(_subkey(key, magic)).decrypt(data[offset:offset + 12], data[offset + 12:],
                                                   _aad(magic, scope, name))
        if payload[0] == 1:
            decoder = zlib.decompressobj()
            result = decoder.decompress(payload[1:], MAX_IMAGE + 1)
            if not decoder.eof or decoder.unused_data or len(result) > MAX_IMAGE:
                raise ValueError('Invalid compressed photo')
        elif payload[0] == 0:
            result = payload[1:]
        else:
            raise ValueError('Unsupported photo compression')
    except (InvalidTag, zlib.error) as exc:
        raise ValueError('Encrypted photo failed verification') from exc
    if not backup and not hmac.compare_digest(name, asset_name(key, scope, result)):
        raise ValueError('Encrypted photo identity mismatch')
    return result


def read_encrypted(path):
    if path.is_symlink():
        raise ValueError('Encrypted photos cannot use symbolic links')
    with path.open('rb') as stream:
        data = stream.read(MAX_IMAGE + 35)
    if len(data) > MAX_IMAGE + 34:
        raise ValueError('Encrypted photo is too large')
    return data


def seal_caption(key, scope, ident, text):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 160 or '\x00' in text:
        raise ValueError('Invalid photo caption')
    nonce = secrets.token_bytes(12)
    plain = text.strip().encode()
    data = CAPTION_MAGIC + nonce + AESGCM(_subkey(key, b'caption')).encrypt(
        nonce, plain, _aad(CAPTION_MAGIC, scope, ident))
    return base64.urlsafe_b64encode(data).decode('ascii')


def caption_payload(value):
    if not isinstance(value, str) or len(value) > 1024:
        raise ValueError('Invalid encrypted caption')
    try:
        data = base64.b64decode(value, altchars=b'-_', validate=True)
    except binascii.Error as exc:
        raise ValueError('Invalid encrypted caption') from exc
    if not data.startswith(CAPTION_MAGIC) or not 33 < len(data) <= 673:
        raise ValueError('Invalid encrypted caption')
    return data


def open_caption(key, scope, ident, value):
    data = caption_payload(value)
    try:
        offset = len(CAPTION_MAGIC)
        text = AESGCM(_subkey(key, b'caption')).decrypt(
            data[offset:offset + 12], data[offset + 12:], _aad(CAPTION_MAGIC, scope, ident)).decode()
    except (UnicodeError, InvalidTag) as exc:
        raise ValueError('Invalid encrypted caption') from exc
    if not 1 <= len(text) <= 160 or '\x00' in text:
        raise ValueError('Invalid photo caption')
    return text


class Sessions:
    """Unlock tokens are scoped to a workspace and live only in this process."""
    def __init__(self):
        self.sessions = {}
        self.lock = threading.RLock()
        self.deriving = threading.Lock()
        self.readers = threading.BoundedSemaphore(3)
        self.last_failure = 0.0
        self.timer = None

    def _prune(self):
        now = time.monotonic()
        for token in list(self.sessions):
            if self.sessions[token][2] <= now:
                del self.sessions[token]

    def _expire(self):
        with self.lock:
            self.timer = None
            self._prune()
            self._schedule()

    def _schedule(self):
        if self.timer is None and self.sessions:
            delay = min(entry[2] for entry in self.sessions.values()) - time.monotonic()
            self.timer = threading.Timer(max(0, delay), self._expire)
            self.timer.daemon = True
            self.timer.start()

    def unlock(self, workspace, envelope, password):
        if not self.deriving.acquire(blocking=False):
            raise Busy('Photo unlock is busy')
        try:
            if time.monotonic() - self.last_failure < 1:
                raise Busy('Retry photo unlock in a moment')
            try:
                key = unwrap_key(envelope, password)
            except Locked:
                self.last_failure = time.monotonic()
                raise
        finally:
            self.deriving.release()
        with self.lock:
            self._prune()
            if len(self.sessions) >= 64:
                raise Busy('Too many photo sessions')
            token = secrets.token_urlsafe(32)
            self.sessions[token] = (workspace, key, time.monotonic() + IDLE_SECONDS)
            self._schedule()
            return token

    def key(self, workspace, token=None, *, background=False, touch=True):
        with self.lock:
            self._prune()
            if background:
                for owner, key, _ in self.sessions.values():
                    if owner == workspace:
                        return key
            elif token in self.sessions:
                owner, key, expiry = self.sessions[token]
                if owner == workspace:
                    if touch:
                        self.sessions[token] = (owner, key, time.monotonic() + IDLE_SECONDS)
                    return key
        raise Locked('Unlock photos to continue')

    def revoke(self, token):
        with self.lock:
            self.sessions.pop(token, None)

    def clear(self):
        with self.lock:
            self.sessions.clear()
