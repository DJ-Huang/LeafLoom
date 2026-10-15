"""Installed desktop discovery and transactional migration of our legacy agents."""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time
import uuid

def atomic_write(path, data):
    # Launcher discovery must work before third-party dependencies are installed.
    from vault_rag.local_state import atomic_write as write
    write(path, data)


def installed_app(directory: Path):
    try:
        value = json.loads((directory / 'desktop-install.json').read_text(encoding='utf-8'))
        executable = Path(value['executable'])
        if value.get('schema') == 1 and executable.is_absolute() and executable.is_file():
            return executable
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def forward(action, directory):
    """Return False for source-only installations. Never start a second backend."""
    executable = installed_app(directory)
    if executable is None:
        return False
    from vault_rag.platform_support import hidden_process_options
    args = [str(executable)] + (['--quit'] if action == 'stop' else [])
    subprocess.Popen(args, env=dict(os.environ, VAULT_RAG_HOME=str(directory)),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **hidden_process_options())
    return True


class LegacyMigration:
    """Persist rollback BEFORE disabling agents; only known, owned agents qualify."""
    def __init__(self, config):
        self.config = config
        self.receipt = config.directory / 'desktop-migration.json'
        self.data = None
        self.committed = False

    def save(self):
        atomic_write(self.receipt, json.dumps(self.data, ensure_ascii=False, indent=2).encode())

    def begin(self):
        if self.receipt.exists():
            old = json.loads(self.receipt.read_text(encoding='utf-8'))
            if old.get('state') == 'committed':
                self.data = old
                self.committed = True
                return old.get('autostart', False)
            self.data = old
            if old.get('state') != 'rolled-back':
                self.rollback()
        self.data = {'schema': 1, 'state': 'pending', 'autostart': False, 'agents': []}
        backup = self.config.directory / 'legacy-backups' / uuid.uuid4().hex
        backup.mkdir(parents=True)
        try:
            if sys.platform == 'win32':
                self._windows(backup)
            elif sys.platform == 'darwin':
                self._macos(backup)
            self.save()
            return self.data['autostart']
        except Exception:
            self.rollback()
            raise

    def _windows(self, backup):
        from vault_rag import windows_service as service
        from vault_rag.platform_support import current_sid
        import xml.etree.ElementTree as ET
        ns = {'t': service.NS}
        for role in ('service', 'tray'):
            name = service.task_name(self.config, role)
            result = service.scheduler('/Query', '/TN', name, '/XML', check=False)
            if result.returncode:
                if service.installed(self.config, role):
                    raise RuntimeError('Cannot export legacy task: ' + name)
                continue
            # schtasks writes a BOM on some Windows versions and OEM text on others.
            xml = result.stdout
            if not xml.startswith((b'\xff\xfe', b'\xfe\xff')):
                decoded = xml.decode('utf-8-sig', errors='strict').lstrip()
                # schtasks can declare UTF-16 while emitting UTF-8 to a pipe.
                # Normalize the declaration too, so the rollback XML is valid.
                decoded = re.sub(r'(encoding\s*=\s*[\"\'])utf-16([\"\'])', r'\1UTF-8\2', decoded, count=1, flags=re.IGNORECASE)
                xml = decoded.encode('utf-8')
            tree = ET.fromstring(xml)
            owner = tree.findtext('.//t:Principal/t:UserId', namespaces=ns)
            if owner != current_sid():
                raise RuntimeError('Legacy task belongs to another user: ' + name)
            path = backup / (role + '.xml')
            atomic_write(path, xml)
            active = service.task_active(self.config, role)
            enabled = tree.findtext('.//t:LogonTrigger/t:Enabled', 'true', ns) == 'true' and tree.findtext('.//t:Settings/t:Enabled', 'true', ns) == 'true'
            if role == 'service':
                self.data['autostart'] = enabled
            self.data['agents'].append({'kind': 'windows', 'role': role, 'backup': str(path), 'active': active})
        self.save()
        for agent in self.data['agents']:
            name = service.task_name(self.config, agent['role'])
            service.scheduler('/Change', '/TN', name, '/Disable')
        # Export both first. Stopping a legacy tray also stops its service.
        for agent in reversed(self.data['agents']):
            service.wait_stopped(self.config, agent['role'])

    def _macos(self, backup):
        for label in ('com.djhuang.vault-rag', 'com.djhuang.vault-rag.menubar'):
            path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
            if not path.exists():
                continue
            content = path.read_bytes()
            value = plistlib.loads(content)
            home = value.get('EnvironmentVariables', {}).get('VAULT_RAG_HOME')
            if not home or Path(home).resolve() != self.config.directory:
                continue
            target = f'gui/{os.getuid()}/{label}'
            active = subprocess.run(['launchctl', 'print', target], capture_output=True).returncode == 0
            saved = backup / (label + '.plist')
            atomic_write(saved, content)
            self.data['agents'].append({'kind': 'macos', 'label': label, 'backup': str(saved), 'active': active})
            if label == 'com.djhuang.vault-rag':
                self.data['autostart'] = bool(value.get('RunAtLoad', False))
        self.save()
        for agent in self.data['agents']:
            label = agent['label']
            path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
            value = plistlib.loads(self._backup(agent).read_bytes())
            value['RunAtLoad'] = False
            value['KeepAlive'] = False
            atomic_write(path, plistlib.dumps(value))
            subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], capture_output=True)
        if any(a['label'].endswith('.menubar') for a in self.data['agents']):
            atomic_write(self.config.directory / 'menubar.stop', b'1')
            lock = self.config.directory / 'menubar.lock'
            deadline = time.monotonic() + 15
            while lock.exists() and time.monotonic() < deadline:
                time.sleep(.1)
            if lock.exists():
                raise RuntimeError('Legacy menu has not stopped; migration cancelled')

    def _backup(self, agent):
        path = Path(agent['backup']).resolve()
        root = (self.config.directory / 'legacy-backups').resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError('Invalid legacy backup path')
        return path

    def commit(self):
        if self.data:
            self.data['state'] = 'committed'
            self.save()
        self.committed = True

    def rollback(self):
        if not self.data or self.committed:
            return
        errors = []
        for agent in self.data.get('agents', []):
            try:
                saved = self._backup(agent)
                if agent['kind'] == 'windows' and sys.platform == 'win32':
                    from vault_rag import windows_service as service
                    role = agent['role']
                    if role not in ('service', 'tray'):
                        raise ValueError('Invalid legacy role')
                    name = service.task_name(self.config, role)
                    service.scheduler('/Create', '/TN', name, '/XML', str(saved), '/F')
                    if agent['active']:
                        service.scheduler('/Run', '/TN', name)
                elif agent['kind'] == 'macos' and sys.platform == 'darwin':
                    label = agent['label']
                    if label not in ('com.djhuang.vault-rag', 'com.djhuang.vault-rag.menubar'):
                        raise ValueError('Invalid legacy label')
                    path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
                    atomic_write(path, saved.read_bytes())
                    if agent['active']:
                        target = f'gui/{os.getuid()}/{label}'
                        subprocess.run(['launchctl', 'bootout', target], capture_output=True)
                        subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)], check=True)
                else:
                    raise ValueError('Legacy backup platform mismatch')
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError('Legacy rollback failed: ' + '; '.join(errors))
        self.data['state'] = 'rolled-back'
        self.save()
