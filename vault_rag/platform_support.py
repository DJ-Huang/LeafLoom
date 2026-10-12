"""Small, dependency-free platform boundary for paths, privacy and desktop UI."""
from __future__ import annotations

import ctypes
import os
import stat
import subprocess
import sys
from functools import lru_cache
from pathlib import Path, PureWindowsPath

_DLL_DIRECTORIES = []


def prepare_windows_runtime() -> None:
    """Expose the locked app-local MSVC DLLs, including uv's venv redirectors."""
    if not is_windows() or _DLL_DIRECTORIES:
        return
    for directory in (Path(sys.prefix) / 'Scripts', Path(sys.prefix)):
        if (directory / 'msvcp140.dll').is_file():
            # Retain the handles for process lifetime; closing one removes the path.
            _DLL_DIRECTORIES.append(os.add_dll_directory(str(directory)))


def is_windows() -> bool:
    return sys.platform == 'win32'


def state_directory() -> Path:
    override = os.environ.get('VAULT_RAG_HOME')
    if override:
        return Path(override).expanduser().resolve()
    if is_windows():
        local_appdata = os.environ.get('LOCALAPPDATA')
        return (Path(local_appdata) if local_appdata else Path.home() / 'AppData/Local') / 'VaultRag'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/VaultRag'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'VaultRag'


def hidden_process_options() -> dict:
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if is_windows() else {}


def powershell(script: str, *, timeout: float = 120) -> subprocess.CompletedProcess:
    import base64
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-STA', '-EncodedCommand', encoded],
        capture_output=True, text=True, encoding='utf-8', timeout=timeout,
        **hidden_process_options(),
    )


@lru_cache(maxsize=1)
def current_sid() -> str:
    result = powershell('[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); '
                        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value')
    if result.returncode or not result.stdout.strip().startswith('S-1-'):
        raise RuntimeError('无法读取当前 Windows 用户身份：' + result.stderr.strip())
    return result.stdout.strip()


@lru_cache(maxsize=16)
def protect_private_directory(directory: Path) -> None:
    """Protect app state only; never change the linked knowledge directory's ACL."""
    directory.mkdir(parents=True, exist_ok=True)
    if not is_windows():
        directory.chmod(0o700)
        return
    # Reapplying an unchanged inheritable ACL propagates through the large
    # runtime/model cache. Verify its exact protection before doing any write.
    path = str(directory).replace("'", "''")
    result = powershell(f"""$ErrorActionPreference='Stop'
try {{
    $acl=[IO.Directory]::GetAccessControl('{path}')
    $rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $valid=$acl.AreAccessRulesProtected -and $rules.Count -eq 2
    $seen=@()
    foreach ($rule in $rules) {{
        $valid=$valid -and $rule.AccessControlType -eq 'Allow' -and [int]$rule.FileSystemRights -eq 2032127 -and
            [int]$rule.InheritanceFlags -eq 3 -and [int]$rule.PropagationFlags -eq 0
        $seen += $rule.IdentityReference.Value
    }}
    if ($valid -and $seen -contains $sid -and $seen -contains 'S-1-5-18') {{ 'private' }}
}} catch {{ }}
""")
    if result.returncode == 0 and result.stdout.strip() == 'private':
        return
    # Replace inherited access with current-user and SYSTEM access. Children inherit it.
    sid = current_sid()
    result = subprocess.run(
        ['icacls.exe', str(directory), '/inheritance:r', '/grant:r',
         f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'],
        capture_output=True, **hidden_process_options(),
    )
    if result.returncode:
        raise RuntimeError('无法保护本地配置目录的 Windows 访问权限')


def private_file_mode(path: Path) -> None:
    if not is_windows():
        path.chmod(0o600)


def preserve_file_mode(handle, path: Path) -> None:
    if not is_windows() and path.exists():
        os.fchmod(handle.fileno(), stat.S_IMODE(path.stat().st_mode))


def is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    if is_windows():
        try:
            # Junctions use a mount-point reparse tag; cloud placeholders are not links.
            tag = getattr(path.lstat(), 'st_reparse_tag', 0)
            return tag in (0xA0000003, 0xA000000C)
        except FileNotFoundError:
            return False
    return False


def path_key(value: str) -> str:
    return value.casefold() if is_windows() else value


def validate_windows_parts(parts) -> None:
    for part in parts:
        if (PureWindowsPath(part).is_reserved() or part.endswith((' ', '.'))
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)):
            raise ValueError('Windows 文件名包含保留名称或无效字符')


def choose_directory() -> dict:
    if is_windows():
        result = powershell('''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Windows.Forms
$dialog=New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description='关联本地知识目录'
try {
    if ($dialog.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) {
        @{path=$dialog.SelectedPath} | ConvertTo-Json -Compress
    } else { @{cancelled=$true} | ConvertTo-Json -Compress }
} finally { $dialog.Dispose() }
''', timeout=120)
        if result.returncode:
            raise ValueError('目录选择失败：' + result.stderr.strip())
        import json
        return json.loads(result.stdout)
    if sys.platform == 'darwin':
        result = subprocess.run(
            ['/usr/bin/osascript', '-e', 'POSIX path of (choose folder with prompt "关联本地知识目录")'],
            capture_output=True, text=True, encoding='utf-8', timeout=120,
        )
        return {'path': result.stdout.strip()} if result.returncode == 0 else {'cancelled': True}
    raise ValueError('此系统请在输入框中填写目录的绝对路径')


def show_error(message: str) -> None:
    if is_windows():
        ctypes.windll.user32.MessageBoxW(None, message, '本地知识库', 0x10)
    elif sys.platform == 'darwin':
        import json
        subprocess.run(['/usr/bin/osascript', '-e',
                        'display alert "本地知识库暂时无法启动" message ' + json.dumps(message, ensure_ascii=False) + ' as critical'],
                       check=False)
    else:
        print(message, file=sys.stderr)
