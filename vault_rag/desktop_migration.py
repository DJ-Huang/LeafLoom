"""Take over only verified current-user legacy registrations; preserve rollback files."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import plistlib
import re
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from vault_rag.local_state import atomic_write

LABELS = ('com.djhuang.vault-rag', 'com.djhuang.vault-rag.menubar')


def same_home(value, config):
    return bool(value) and os.path.normcase(str(Path(value).expanduser().resolve())) == os.path.normcase(str(config.directory))


def mac_registrations(config):
    result = []
    for label in LABELS:
        path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
        if not path.exists():
            continue
        data = plistlib.loads(path.read_bytes())
        home = data.get('EnvironmentVariables', {}).get('VAULT_RAG_HOME') or data.get('VaultRagState')
        if data.get('Label') != label or not same_home(home, config):
            raise RuntimeError('旧启动项属于其他配置目录，未修改：' + str(path))
        result.append({'name': label, 'path': str(path), 'bytes': path.read_bytes(),
                       'enabled': bool(data.get('RunAtLoad', False))})
    return result


def windows_registrations(config):
    from vault_rag.windows_service import scheduler, task_name, NS
    from vault_rag.platform_support import current_sid
    result = []
    for role in ('service', 'tray'):
        name = task_name(config, role)
        response = scheduler('/Query', '/TN', name, '/XML', check=False)
        if response.returncode:
            continue
        xml = response.stdout.decode('mbcs')
        root = ET.fromstring(xml)
        arguments = root.findtext(f'.//{{{NS}}}Exec/{{{NS}}}Arguments', '')
        sid = root.findtext(f'.//{{{NS}}}Principal/{{{NS}}}UserId', '')
        if '-EncodedCommand ' in arguments:
            script = base64.b64decode(arguments.rsplit(' ', 1)[-1]).decode('utf-16-le')
            match = re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", script)
            if not match:
                raise RuntimeError('不能确认旧计划任务归属：' + name)
            arguments = json.loads(base64.b64decode(match[1]))['args']
        suffix = '--home ' + subprocess.list2cmdline([str(config.directory)])
        if sid != current_sid() or not arguments.endswith(suffix) or ('-m vault_rag.windows_entry ' + role) not in arguments:
            raise RuntimeError('旧计划任务归属不匹配，未修改：' + name)
        enabled = root.findtext(f'.//{{{NS}}}LogonTrigger/{{{NS}}}Enabled', 'false') == 'true'
        result.append({'name': name, 'role': role,
                       'bytes': ET.tostring(root, encoding='utf-16', xml_declaration=True), 'enabled': enabled})
    return result


def registrations(config):
    if sys.platform == 'darwin':
        return mac_registrations(config)
    if sys.platform == 'win32':
        return windows_registrations(config)
    return []


def inspect_legacy(config):
    entries = registrations(config)
    return {'legacy': bool(entries), 'autostart': any(entry['enabled'] for entry in entries),
            'registrations': [entry['name'] for entry in entries]}


def port_open(config):
    with socket.socket() as connection:
        connection.settimeout(.3)
        return connection.connect_ex(('127.0.0.1', config.data.get('port', 18080))) == 0


def launchctl(*arguments, check=True):
    response = subprocess.run(['launchctl', *arguments], capture_output=True, text=True)
    if check and response.returncode:
        raise RuntimeError('旧启动项操作失败：' + response.stderr.strip())
    return response


def migrate_legacy(config):
    entries = registrations(config)
    if not entries:
        return {'migrated': False, 'autostart': False}
    from vault_rag.service_control import health
    state = health(config)
    if state not in ('ready', 'stopped'):
        raise RuntimeError('无法验证旧服务身份，未修改启动项；请检查端口和日志')
    backup = config.directory / 'backups' / ('desktop-migration-' + uuid.uuid4().hex)
    backup.mkdir(parents=True)
    for index, entry in enumerate(entries):
        entry['backup'] = str(backup / (str(index) + ('.plist' if sys.platform == 'darwin' else '.xml')))
        atomic_write(Path(entry['backup']), entry['bytes'])
    atomic_write(backup / 'manifest.json', json.dumps({
        'home': str(config.directory), 'platform': sys.platform,
        'entries': [{k: v for k, v in entry.items() if k != 'bytes'} for entry in entries],
    }, ensure_ascii=False, indent=2).encode())
    try:
        if sys.platform == 'darwin':
            for entry in reversed(entries):
                target = f'gui/{os.getuid()}/{entry["name"]}'
                launchctl('bootout', target, check=False)
                if launchctl('print', target, check=False).returncode == 0:
                    raise RuntimeError('旧启动项未停止：' + entry['name'])
        else:
            from vault_rag.windows_native import signal_stop
            from vault_rag.windows_service import wait_stopped, scheduler
            for entry in reversed(entries):
                signal_stop(config.directory, entry['role'])
                wait_stopped(config, entry['role'], timeout=60)
                scheduler('/Delete', '/TN', entry['name'], '/F')
        deadline = time.monotonic() + 60
        while port_open(config):
            if time.monotonic() >= deadline:
                raise RuntimeError('旧服务尚未正常停止；未强制终止')
            time.sleep(.25)
        if sys.platform == 'darwin':
            for entry in entries:
                Path(entry['path']).unlink()
        return {'migrated': True, 'autostart': any(entry['enabled'] for entry in entries), 'backup': str(backup)}
    except Exception as error:
        # Re-register the original definitions. Never erase user configuration or tokens.
        failures = []
        for entry in entries:
            try:
                if sys.platform == 'darwin':
                    atomic_write(Path(entry['path']), entry['bytes'])
                    target = f'gui/{os.getuid()}/{entry["name"]}'
                    if launchctl('print', target, check=False).returncode:
                        launchctl('bootstrap', f'gui/{os.getuid()}', entry['path'])
                else:
                    scheduler('/Create', '/TN', entry['name'], '/XML', entry['backup'], '/F')
            except Exception as restore_error:
                failures.append(str(restore_error))
        raise RuntimeError(f'迁移未完成：{error}。原启动项备份：{backup}。' +
                           ('恢复失败：' + '; '.join(failures) if failures else '已恢复原启动项。')) from error
