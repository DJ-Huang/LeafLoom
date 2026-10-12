"""Current-user interactive scheduled tasks for the server and the tray."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from vault_rag.platform_support import current_sid, hidden_process_options, powershell

NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
ET.register_namespace('', NS)


def task_name(config, role):
    key = hashlib.sha256((current_sid() + '|' + os.path.normcase(str(config.directory))).encode()).hexdigest()[:16]
    return f'VaultRag-{key}-{role}'


def task_xml(config, role: str, *, enabled=True) -> bytes:
    root = ET.Element(f'{{{NS}}}Task', version='1.2')
    def add(parent, tag, text=None, **attrs):
        child = ET.SubElement(parent, f'{{{NS}}}{tag}', attrs)
        child.text = text
        return child
    sid = current_sid()
    trigger = add(add(root, 'Triggers'), 'LogonTrigger')
    add(trigger, 'Enabled', str(enabled).lower()); add(trigger, 'UserId', sid)
    principal = add(add(root, 'Principals'), 'Principal', id='CurrentUser')
    add(principal, 'UserId', sid); add(principal, 'LogonType', 'InteractiveToken')
    add(principal, 'RunLevel', 'LeastPrivilege')
    settings = add(root, 'Settings')
    for key, value in {'MultipleInstancesPolicy':'IgnoreNew', 'DisallowStartIfOnBatteries':'false',
                       'StopIfGoingOnBatteries':'false', 'AllowHardTerminate':'false',
                       'StartWhenAvailable':'true', 'RunOnlyIfNetworkAvailable':'false',
                       'Enabled':'true', 'ExecutionTimeLimit':'PT0S'}.items():
        add(settings, key, value)
    idle = add(settings, 'IdleSettings'); add(idle, 'StopOnIdleEnd', 'false'); add(idle, 'RestartOnIdle', 'false')
    if role == 'service':
        retry = add(settings, 'RestartOnFailure')
        add(retry, 'Interval', 'PT1M'); add(retry, 'Count', '3')
    action = add(add(root, 'Actions', Context='CurrentUser'), 'Exec')
    # Keep the venv path: resolving a launcher symlink can select the base Python.
    python = Path(sys.executable).absolute()
    pythonw = python.with_name('pythonw.exe')
    args = ['-X', 'utf8', '-m', 'vault_rag.windows_entry', role, '--home', str(config.directory)]
    repo = Path(__file__).resolve().parents[1]
    if pythonw.exists():
        command, arguments = str(pythonw), subprocess.list2cmdline(args)
    else:
        # uv distributions without pythonw still run invisibly, with their exit code
        # propagated to Task Scheduler for RestartOnFailure.
        spec = json.dumps({'python':str(python), 'args':subprocess.list2cmdline(args), 'cwd':str(repo)})
        payload = base64.b64encode(spec.encode('utf-8')).decode()
        script = f'''$ErrorActionPreference='Stop'; $s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}'))|ConvertFrom-Json;
$p=New-Object Diagnostics.ProcessStartInfo; $p.FileName=$s.python; $p.Arguments=$s.args; $p.WorkingDirectory=$s.cwd;
$p.UseShellExecute=$false; $p.CreateNoWindow=$true; $process=[Diagnostics.Process]::Start($p); $process.WaitForExit(); exit $process.ExitCode'''
        encoded = base64.b64encode(script.encode('utf-16-le')).decode()
        command = 'powershell.exe'
        arguments = subprocess.list2cmdline(['-NoProfile','-NonInteractive','-WindowStyle','Hidden','-EncodedCommand',encoded])
    add(action, 'Command', command); add(action, 'Arguments', arguments); add(action, 'WorkingDirectory', str(repo))
    return ET.tostring(root, encoding='utf-16', xml_declaration=True)


def scheduler(*args, check=True):
    result = subprocess.run(['schtasks.exe', *args], capture_output=True, **hidden_process_options())
    if check and result.returncode:
        raise RuntimeError('Windows 计划任务操作失败；请检查当前用户的计划任务权限。\n' +
                           (result.stderr or result.stdout).decode('mbcs', errors='replace'))
    return result


def installed(config, role='service') -> bool:
    return scheduler('/Query', '/TN', task_name(config, role), '/XML', check=False).returncode == 0


def autostart_enabled(config) -> bool:
    file = config.directory / 'windows-service.json'
    return json.loads(file.read_text(encoding='utf-8')).get('autostart', True) if file.exists() else True


def register(config, *, autostart=None):
    from vault_rag.local_state import atomic_write
    enabled = autostart_enabled(config) if autostart is None else autostart
    for role in ('service', 'tray'):
        path = config.directory / f'{role}-task.xml'
        atomic_write(path, task_xml(config, role, enabled=enabled))
        try:
            scheduler('/Create', '/TN', task_name(config, role), '/XML', str(path), '/F')
        finally:
            path.unlink(missing_ok=True)
    atomic_write(config.directory / 'windows-service.json', json.dumps({'autostart':enabled}, indent=2).encode())


def wait_stopped(config, role='service', timeout=60):
    from vault_rag.windows_native import running, signal_stop
    live = running(config.directory, role)
    if not live and not task_active(config, role):
        return
    # Cover both a scheduled process that has not yet created its mutex and a
    # stopped server whose task is still completing (IgnoreNew would lose restart).
    deadline = time.monotonic() + timeout
    while True:
        if live:
            signal_stop(config.directory, role)
        elif not task_active(config, role):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f'服务未能在 {timeout} 秒内正常退出；请查看日志，未强制结束进程')
        time.sleep(.2)
        live = running(config.directory, role)


def task_active(config, role='service') -> bool:
    # Numeric task states avoid interpreting localized schtasks output.
    name = task_name(config, role)
    result = powershell(f"""$ErrorActionPreference='Stop'
$task=Get-ScheduledTask -TaskName '{name}' -TaskPath '\\' -ErrorAction SilentlyContinue
if ($null -eq $task) {{ 0 }} else {{ [int]$task.State }}
""", timeout=5)
    if result.returncode:
        raise RuntimeError('无法确认 Windows 后台任务是否已退出：' + result.stderr.strip())
    return result.stdout.strip() in ('2','4')  # queued or running


def start_tray(config):
    from vault_rag.windows_native import running
    if not installed(config, 'tray'):
        register(config)
    if not running(config.directory, 'tray') and not task_active(config, 'tray'):
        scheduler('/Run', '/TN', task_name(config, 'tray'))


def control(action, config):
    from vault_rag.service_control import health, ensure_ready
    from vault_rag.windows_native import running
    if action == 'install':
        register(config); control('start', config); start_tray(config)
    elif action == 'start':
        if not installed(config):
            register(config)
        state = health(config)
        if state == 'other':
            raise RuntimeError('配置端口已被其他程序占用，请修改端口或关闭占用程序')
        if state != 'ready' and not running(config.directory) and not task_active(config):
            scheduler('/Run', '/TN', task_name(config, 'service'))
        ensure_ready(config)
    elif action == 'stop':
        wait_stopped(config)
    elif action == 'restart':
        wait_stopped(config); control('start', config)
    elif action == 'status':
        print(json.dumps({'installed':installed(config), 'running':running(config.directory),
                          'health':health(config), 'autostart':autostart_enabled(config)}, ensure_ascii=False))
    elif action in ('enable-autostart', 'disable-autostart'):
        register(config, autostart=action == 'enable-autostart')
    elif action == 'uninstall':
        wait_stopped(config); wait_stopped(config, 'tray')
        for role in ('service', 'tray'):
            if installed(config, role):scheduler('/Delete', '/TN', task_name(config, role), '/F')
        (config.directory / 'windows-service.json').unlink(missing_ok=True)
    else:
        raise ValueError('未知服务管理操作：' + action)
