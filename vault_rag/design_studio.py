"""Built-in Design Studio service for LeafLoom (Wiki + Figma-like HTML Design).

Manages design project discovery, in-vault project scaffolding, artboard management,
persistent Figma-style layer transforms, and design contract checking.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
from typing import Any

from vault_rag.local_state import ConflictError, PROTECTED, atomic_write, relative, under
from vault_rag.platform_support import is_link, path_key

ASSETS_DIR = Path(__file__).resolve().parent / 'design_assets' / 'layer_review'

PRESETS: dict[str, dict[str, Any]] = {
    'mobile-portrait': {
        'width': 720,
        'height': 1560,
        'orientation': '竖屏优先（720×1560），保留安全区与长屏适配',
        'platforms': ['Web', 'Mobile'],
    },
    'game-landscape': {
        'width': 1560,
        'height': 720,
        'orientation': '横屏优先（1560×720），左右安全区与中心舞台布局',
        'platforms': ['WebGL', 'PC', 'Mobile'],
    },
    'desktop-web': {
        'width': 1440,
        'height': 900,
        'orientation': '桌面宽屏优先（1440×900），支持响应式栅格与侧栏',
        'platforms': ['Web', 'Desktop'],
    },
    'custom': {
        'width': 720,
        'height': 1560,
        'orientation': '自定义画板基准尺寸',
        'platforms': ['Web'],
    },
}

SKIP_SCAN_DIRS = {
    path_key(x) for x in (
        *PROTECTED, 'Standards', 'Assets', 'Validation', 'ArtSource',
        'Library', 'Temp', 'Logs', 'Obj', 'Packages', 'Build', 'Builds',
        'download-data', 'exports', 'derived', 'originals',
    )
}


def _slug(text: str, fallback: str = 'project') -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_-]+', '-', text.strip().lower()).strip('-')
    if cleaned:
        return cleaned[:48]
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]
    return f'{fallback}-{digest}'


class DesignStudio:
    def __init__(self, config, runtime, websites):
        self.config = config
        self.runtime = runtime
        self.files = runtime.files
        self.websites = websites

    @property
    def workspace_revision(self) -> str:
        return self.config.data.get('revision', '')

    def _check_workspace(self, workspace_revision: str | None) -> None:
        if workspace_revision is not None and workspace_revision != self.workspace_revision:
            raise ConflictError('Workspace changed; read its current workspace_revision and retry')
        _ = self.config.root

    def _find_spec_file(self, project_dir: Path) -> Path | None:
        for candidate in (project_dir / 'Design' / 'project-spec.json', project_dir / 'project-spec.json'):
            if candidate.is_file() and not is_link(candidate):
                return candidate
        return None

    def _parse_screens_file(self, screen_path: Path) -> tuple[list[dict], list[dict], list[dict]]:
        if not screen_path.is_file():
            return [], [], []
        text = screen_path.read_text(encoding='utf-8')
        if screen_path.suffix.lower() == '.json':
            data = json.loads(text)
            screens = data.get('screens', [])
            variants = data.get('variants', [])
            boards = data.get('boards', screens + variants)
            return screens, variants, boards

        # Fast marker parser for LeafLoom-generated screens.js
        marker_match = re.search(r'/\*__LEAFLOOM_SCREENS_JSON__\*/\s*(\{.*?\})\s*/\*__END_LEAFLOOM_SCREENS_JSON__\*/', text, re.S)
        if marker_match:
            try:
                data = json.loads(marker_match.group(1))
                screens = data.get('screens', [])
                variants = data.get('variants', [])
                boards = data.get('boards', screens + variants)
                return screens, variants, boards
            except json.JSONDecodeError:
                pass

        import os
        ext_path = os.environ.get('PATH', '') + os.pathsep + '/opt/homebrew/bin' + os.pathsep + '/usr/local/bin'
        node = shutil.which('node', path=ext_path)
        if node:
            script = (
                "const m=require(process.argv[1]);"
                "process.stdout.write(JSON.stringify({screens:m.screens||[],variants:m.variants||[],boards:m.boards||[]}));"
            )
            try:
                res = subprocess.run([node, '-e', script, str(screen_path)], check=True, capture_output=True, text=True, timeout=10, env={**os.environ, 'PATH': ext_path})
                data = json.loads(res.stdout)
                screens = data.get('screens', [])
                variants = data.get('variants', [])
                boards = data.get('boards', screens + variants)
                return screens, variants, boards
            except Exception:
                pass
        return [], [], []

    def _read_transforms_file(self, project_dir: Path) -> dict[str, dict[str, Any]]:
        for candidate in (project_dir / 'Design' / 'layer-transforms.json', project_dir / 'layer-transforms.json'):
            if candidate.is_file() and not is_link(candidate):
                try:
                    raw = json.loads(candidate.read_text(encoding='utf-8'))
                    if isinstance(raw, dict) and isinstance(raw.get('boards'), dict):
                        return raw['boards']
                except Exception:
                    return {}
        return {}

    def _entry_for_project(self, project_dir: Path, root: Path) -> tuple[str, str]:
        candidates = [
            project_dir / 'Design' / 'UI' / 'Site' / 'ui-gallery.html',
            project_dir / 'Design' / 'index.html',
            project_dir / 'index.html',
        ]
        gallery = next((c for c in candidates if c.is_file() and not is_link(c)), candidates[-1])
        portal = next((c for c in (project_dir / 'Design' / 'index.html', project_dir / 'index.html', gallery) if c.is_file() and not is_link(c)), gallery)
        return gallery.relative_to(root).as_posix(), portal.relative_to(root).as_posix()

    def _project_summary(self, project_dir: Path, root: Path) -> dict[str, Any] | None:
        spec_file = self._find_spec_file(project_dir)
        if spec_file is None:
            return None
        try:
            spec = json.loads(spec_file.read_text(encoding='utf-8'))
        except Exception:
            return None
        if not isinstance(spec, dict) or not isinstance(spec.get('project'), dict):
            return None

        rel_dir = '' if project_dir == root else project_dir.relative_to(root).as_posix()
        proj_meta = spec['project']
        sources = proj_meta.get('sources') if isinstance(proj_meta.get('sources'), dict) else {}
        screens_rel = sources.get('screens', 'Design/UI/Site/screens.js')
        assets_rel = sources.get('assets', 'Design/Assets/manifest.json')
        screens_path = (project_dir / screens_rel).resolve()
        assets_path = (project_dir / assets_rel).resolve()

        screens, variants, boards = ([], [], [])
        if screens_path.is_relative_to(project_dir):
            screens, variants, boards = self._parse_screens_file(screens_path)

        asset_count = 0
        if assets_path.is_relative_to(project_dir) and assets_path.is_file():
            try:
                manifest = json.loads(assets_path.read_text(encoding='utf-8'))
                asset_count = len(manifest.get('assets', []))
            except Exception:
                asset_count = 0

        transforms_boards = self._read_transforms_file(project_dir)
        transformed_layers = sum(len(v) for v in transforms_boards.values() if isinstance(v, dict))

        gallery_entry, portal_entry = self._entry_for_project(project_dir, root)
        html_project = None
        if (root / gallery_entry).is_file():
            try:
                html_project = self.websites.register(str(root), rel_dir, gallery_entry, spa=False)
            except Exception:
                html_project = None

        first_board = boards[0] if boards else (screens[0] if screens else {})
        width = first_board.get('width', 720) if isinstance(first_board, dict) else 720
        height = first_board.get('height', 1560) if isinstance(first_board, dict) else 1560

        return {
            'id': str(proj_meta.get('id') or _slug(project_dir.name)),
            'name': str(proj_meta.get('name') or project_dir.name),
            'directory': rel_dir,
            'spec_path': spec_file.relative_to(root).as_posix(),
            'entry': gallery_entry,
            'portal_entry': portal_entry,
            'html_project_id': html_project['id'] if html_project else None,
            'standard_version': str(spec.get('standardVersion', '1.1.0')),
            'platforms': proj_meta.get('platforms', ['Web']),
            'orientation': str(proj_meta.get('orientation', '')),
            'width': width,
            'height': height,
            'screen_count': len(screens),
            'variant_count': len(variants),
            'board_count': len(boards),
            'asset_count': asset_count,
            'transformed_layer_count': transformed_layers,
            'screens': [
                {
                    'id': b.get('id'),
                    'name': b.get('name'),
                    'group': b.get('group', ''),
                    'width': b.get('width', width),
                    'height': b.get('height', height),
                    'base': b.get('base'),
                }
                for b in boards if isinstance(b, dict) and b.get('id')
            ],
        }

    def list_projects(self, folder: str = '', current_path: str = '') -> dict[str, Any]:
        root = self.config.root
        folder = relative(folder)
        current_path = relative(current_path)
        start_dir = self.config.path_for(folder) if folder else root
        if not start_dir.is_dir():
            raise ValueError('folder must be an existing directory')

        discovered: list[Path] = []
        stack: list[tuple[Path, int]] = [(start_dir, 0)]
        while stack:
            curr, depth = stack.pop()
            if self._find_spec_file(curr) is not None:
                discovered.append(curr)
                continue
            if depth >= 5:
                continue
            try:
                children = sorted(curr.iterdir(), key=lambda p: p.name.lower(), reverse=True)
            except OSError:
                continue
            for child in children:
                if child.name.startswith('.') or path_key(child.name) in SKIP_SCAN_DIRS:
                    continue
                if is_link(child) or not child.is_dir():
                    continue
                stack.append((child, depth + 1))

        projects = []
        for proj_dir in sorted(discovered, key=lambda p: p.relative_to(root).as_posix().lower()):
            summary = self._project_summary(proj_dir, root)
            if summary is not None:
                projects.append(summary)

        selected = None
        if current_path:
            matches = [
                p for p in projects
                if not p['directory'] or current_path == p['directory'] or current_path.startswith(p['directory'] + '/')
            ]
            if matches:
                selected = max(matches, key=lambda p: len(p['directory']))
        if selected is None and projects:
            selected = projects[0]

        return {
            'ok': True,
            'root': str(root),
            'projects': projects,
            'selected': selected,
            'workspace_revision': self.workspace_revision,
        }

    def get_project(self, directory: str, board_id: str | None = None) -> dict[str, Any]:
        root = self.config.root
        directory = relative(directory)
        proj_dir = self.config.path_for(directory) if directory else root
        if not proj_dir.is_dir():
            raise FileNotFoundError(f'Design project directory not found: {directory}')
        summary = self._project_summary(proj_dir, root)
        if summary is None:
            raise FileNotFoundError(f'No Design/project-spec.json found in {directory or "/"}')
        spec_file = self._find_spec_file(proj_dir)
        spec = json.loads(spec_file.read_text(encoding='utf-8')) if spec_file else {}
        transforms_boards = self._read_transforms_file(proj_dir)
        result = {
            'ok': True,
            **summary,
            'spec': spec,
            'transforms': transforms_boards,
            'workspace_revision': self.workspace_revision,
        }
        if board_id is not None:
            result['board_id'] = board_id
            result['board_transforms'] = transforms_boards.get(board_id, {})
        return result

    def get_transforms(self, directory: str, board_id: str = '') -> dict[str, Any]:
        root = self.config.root
        directory = relative(directory)
        proj_dir = self.config.path_for(directory) if directory else root
        if not proj_dir.is_dir():
            raise FileNotFoundError(f'Design project directory not found: {directory}')
        boards = self._read_transforms_file(proj_dir)
        return {
            'ok': True,
            'directory': directory,
            'board_id': board_id or None,
            'transforms': boards.get(board_id, {}) if board_id else boards,
            'all_boards': boards,
            'workspace_revision': self.workspace_revision,
        }

    def save_transforms(
        self,
        directory: str,
        board_id: str,
        transforms: dict[str, Any],
        *,
        workspace_revision: str | None = None,
        merge: bool = False,
    ) -> dict[str, Any]:
        with self.config.lock, self.files.lock:
            self._check_workspace(workspace_revision)
            root = self.config.root
            directory = relative(directory)
            proj_dir = self.config.path_for(directory, writable=True) if directory else root
            if not proj_dir.is_dir():
                raise FileNotFoundError(f'Design project directory not found: {directory}')
            if not isinstance(board_id, str) or not board_id.strip():
                raise ValueError('board_id is required')
            if not isinstance(transforms, dict):
                raise ValueError('transforms must be an object mapping layer IDs to transform properties')

            design_dir = proj_dir / 'Design' if (proj_dir / 'Design').is_dir() else proj_dir
            transforms_path = design_dir / 'layer-transforms.json'
            rel_transforms = transforms_path.relative_to(root).as_posix()
            self.config.path_for(rel_transforms, writable=True)

            existing_doc: dict[str, Any] = {'schemaVersion': 1, 'updatedAt': '', 'boards': {}}
            if transforms_path.is_file():
                self.files._history(transforms_path)
                try:
                    loaded = json.loads(transforms_path.read_text(encoding='utf-8'))
                    if isinstance(loaded, dict):
                        existing_doc.update(loaded)
                        if not isinstance(existing_doc.get('boards'), dict):
                            existing_doc['boards'] = {}
                except Exception:
                    existing_doc = {'schemaVersion': 1, 'boards': {}}

            current_board = dict(existing_doc['boards'].get(board_id, {})) if merge else {}
            for layer_id, patch in transforms.items():
                if not isinstance(layer_id, str) or not layer_id:
                    continue
                if patch is None or patch == {}:
                    current_board.pop(layer_id, None)
                    continue
                if not isinstance(patch, dict):
                    raise ValueError(f'Transform for layer {layer_id} must be an object or null')
                merged_layer = dict(current_board.get(layer_id, {})) if merge else {}
                for k in ('tx', 'ty', 'x', 'y', 'width', 'height', 'scaleX', 'scaleY', 'rotate', 'flipX', 'flipY', 'opacity', 'zIndex', 'text', 'hidden', 'locked'):
                    if k in patch:
                        if patch[k] is None:
                            merged_layer.pop(k, None)
                        else:
                            merged_layer[k] = patch[k]
                if merged_layer:
                    current_board[layer_id] = merged_layer
                else:
                    current_board.pop(layer_id, None)

            if current_board:
                existing_doc['boards'][board_id] = current_board
            else:
                existing_doc['boards'].pop(board_id, None)
            existing_doc['updatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

            serialized = json.dumps(existing_doc, ensure_ascii=False, indent=2) + '\n'
            atomic_write(transforms_path, serialized.encode('utf-8'))

            changed_paths = [rel_transforms]
            site_dir = design_dir / 'UI' / 'Site'
            if site_dir.is_dir():
                data_js = site_dir / 'layer-transforms-data.js'
                rel_js = data_js.relative_to(root).as_posix()
                self.config.path_for(rel_js, writable=True)
                js_payload = 'window.DESIGN_LAYER_TRANSFORMS = ' + json.dumps(existing_doc['boards'], ensure_ascii=False, separators=(',', ':')) + ';\n'
                atomic_write(data_js, js_payload.encode('utf-8'))
                changed_paths.append(rel_js)

            self.files.changed(*changed_paths)
            self.runtime.events.publish({
                'type': 'files',
                'paths': changed_paths,
                'design_transforms': {
                    'directory': directory,
                    'board_id': board_id,
                    'transforms': current_board,
                },
            })
            return {
                'ok': True,
                'saved': True,
                'directory': directory,
                'board_id': board_id,
                'path': rel_transforms,
                'transforms': current_board,
                'layer_count': len(current_board),
                'workspace_revision': self.workspace_revision,
            }

    def create_project(
        self,
        directory: str,
        name: str,
        *,
        workspace_revision: str | None = None,
        project_id: str | None = None,
        preset: str = 'mobile-portrait',
        width: int | None = None,
        height: int | None = None,
        orientation: str = '',
        platforms: list[str] | None = None,
        initial_screens: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self.config.lock, self.files.lock:
            self._check_workspace(workspace_revision)
            root = self.config.root
            directory = relative(directory)
            if not directory:
                raise ValueError('请选择或输入知识库内的项目子目录名称')
            name = (name or '').strip() or PurePosixPath(directory).name
            proj_dir = self.config.path_for(directory, writable=True)
            if self._find_spec_file(proj_dir) is not None:
                raise ValueError(f'该目录已存在设计项目：{directory}')

            preset_cfg = PRESETS.get(preset, PRESETS['mobile-portrait'])
            w = int(width or preset_cfg['width'])
            h = int(height or preset_cfg['height'])
            if not (120 <= w <= 7680 and 120 <= h <= 7680):
                raise ValueError('画板宽高须在 120 到 7680 像素之间')
            orient = orientation.strip() or preset_cfg['orientation']
            plats = [str(p).strip() for p in (platforms or preset_cfg['platforms']) if str(p).strip()] or ['Web']
            pid = _slug(project_id or name, fallback='design')

            screens_input = initial_screens or [
                {'id': 'home', 'name': '首页概览', 'group': '核心流程', 'caption': '品牌主视觉、核心价值卡片与主操作入口'},
                {'id': 'workspace', 'name': '主工作区', 'group': '核心流程', 'caption': '核心交互面板、状态栏、内容区与底部操作栏'},
                {'id': 'settings', 'name': '设置与弹层', 'group': '系统弹层', 'caption': '参数开关、偏好配置与说明弹窗'},
            ]
            screens_list = []
            for idx, item in enumerate(screens_input, start=1):
                sid = _slug(str(item.get('id') or f'screen-{idx}'), fallback=f'screen-{idx}')
                sname = str(item.get('name') or sid).strip()
                sgroup = str(item.get('group') or '核心页面').strip()
                scaption = str(item.get('caption') or f'{sname}设计与组件分层').strip()
                sw = int(item.get('width') or w)
                sh = int(item.get('height') or h)
                screens_list.append({
                    'id': sid,
                    'number': f'{idx:02d}',
                    'name': sname,
                    'group': sgroup,
                    'kind': sid,
                    'width': sw,
                    'height': sh,
                    'caption': scaption,
                    'states': item.get('states') or ['默认态', '选中/交互态'],
                    'notes': item.get('notes') or [
                        f'画板基准尺寸 {sw}×{sh}，所有标题、按钮与状态文案均与底板独立分层。',
                        '支持在图层审阅模式下直接拖拽调整位置、8点缩放、旋转与导出切片。',
                    ],
                })

            self._scaffold_project_files(proj_dir, root, directory, pid, name, w, h, orient, plats, screens_list)
            summary = self._project_summary(proj_dir, root)
            self.files.changed(directory)
            self.runtime.events.publish({'type': 'files', 'paths': [directory]})
            return {
                'ok': True,
                'created': True,
                'project': summary,
                'workspace_revision': self.workspace_revision,
            }

    def _scaffold_project_files(
        self,
        proj_dir: Path,
        root: Path,
        rel_dir: str,
        pid: str,
        name: str,
        width: int,
        height: int,
        orientation: str,
        platforms: list[str],
        screens_list: list[dict[str, Any]],
    ) -> None:
        design_dir = proj_dir / 'Design'
        site_dir = design_dir / 'UI' / 'Site'
        assets_dir = design_dir / 'Assets'
        gen_assets_dir = assets_dir / 'Generated'
        standards_dir = design_dir / 'Standards' / '1.1.0'
        tools_dir = standards_dir / 'tools' / 'layer_review'

        for d in (site_dir, gen_assets_dir, tools_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Copy built-in Figma layer review engine
        for fname in ('layer_review.js', 'layer_review.css'):
            src = ASSETS_DIR / fname
            if src.is_file():
                atomic_write(tools_dir / fname, src.read_bytes())

        # Determine standardRef: if ../../_规范/1.1.0/README.md exists inside vault, use it; otherwise use local mirror
        shared_std = (design_dir / '../../_规范/1.1.0/README.md').resolve()
        if shared_std.is_file() and shared_std.is_relative_to(root):
            standard_ref = '../../_规范/1.1.0/README.md'
        else:
            standard_ref = 'Standards/1.1.0/README.md'
        atomic_write(
            standards_dir / 'README.md',
            f'# 设计与落地标准 1.1.0（项目内建镜像）\n\n本项目（{name}）采用 1.1.0 分层画板与组件交接规范。\n'.encode('utf-8'),
        )

        # Generate initial vector assets so manifest.json has real SHA-256 files
        logo_svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="80" viewBox="0 0 240 80">'
            f'<rect x="4" y="4" width="232" height="72" rx="20" fill="#4c7c60"/>'
            f'<circle cx="44" cy="40" r="18" fill="#f7f2e7"/>'
            f'<path d="M36 40l6 6 12-12" stroke="#4c7c60" stroke-width="3.5" fill="none" stroke-linecap="round"/>'
            f'<text x="76" y="47" fill="#ffffff" font-family="system-ui, sans-serif" font-size="22" font-weight="700">{name[:8]}</text>'
            f'</svg>\n'
        ).encode('utf-8')
        hero_svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">'
            f'<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0%" stop-color="#e3efe6"/><stop offset="100%" stop-color="#f7efe0"/></linearGradient></defs>'
            f'<rect width="640" height="360" rx="28" fill="url(#bg)" stroke="#c7d6cb" stroke-width="2"/>'
            f'<circle cx="500" cy="110" r="64" fill="#d3e5d7" opacity="0.7"/>'
            f'<rect x="48" y="56" width="320" height="248" rx="20" fill="#ffffff" opacity="0.88"/>'
            f'<rect x="76" y="88" width="180" height="22" rx="8" fill="#4c7c60" opacity="0.85"/>'
            f'<rect x="76" y="126" width="240" height="14" rx="6" fill="#8ca696" opacity="0.5"/>'
            f'<rect x="76" y="152" width="200" height="14" rx="6" fill="#8ca696" opacity="0.35"/>'
            f'<rect x="76" y="224" width="136" height="44" rx="12" fill="#4c7c60"/>'
            f'</svg>\n'
        ).encode('utf-8')
        logo_path = gen_assets_dir / 'brand-logo.svg'
        hero_path = gen_assets_dir / 'hero-illustration.svg'
        atomic_write(logo_path, logo_svg)
        atomic_write(hero_path, hero_svg)
        logo_sha = hashlib.sha256(logo_svg).hexdigest()
        hero_sha = hashlib.sha256(hero_svg).hexdigest()

        manifest = {
            'schemaVersion': 1,
            'project': pid,
            'assets': [
                {
                    'id': 'brand-logo',
                    'name': f'{name} 品牌标识',
                    'category': 'brand',
                    'kind': 'vector',
                    'path': 'Generated/brand-logo.svg',
                    'vectorPath': 'Design/Assets/Generated/brand-logo.svg',
                    'width': 240,
                    'height': 80,
                    'alpha': True,
                    'sha256': logo_sha,
                    'source': 'LeafLoom Design Studio 初始矢量标识',
                },
                {
                    'id': 'hero-illustration',
                    'name': f'{name} 主视觉插画板',
                    'category': 'scene',
                    'kind': 'vector',
                    'path': 'Generated/hero-illustration.svg',
                    'vectorPath': 'Design/Assets/Generated/hero-illustration.svg',
                    'width': 640,
                    'height': 360,
                    'alpha': True,
                    'sha256': hero_sha,
                    'source': 'LeafLoom Design Studio 初始主视觉组件',
                },
            ],
            'pages': [],
        }
        atomic_write(assets_dir / 'manifest.json', (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))

        # Build project-spec.json
        screen_contracts = {}
        for s in screens_list:
            screen_contracts[s['id']] = {
                'designStatus': 'draft',
                'implementationStatus': 'pending',
                'validationStatus': 'pending',
                'recipeCoverage': 'partial',
                'summary': s['caption'],
                'conditions': ['从顶栏或导航进入该画板'],
                'layout': [f"基准画板 {s['width']}×{s['height']}，组件分层独立定位"],
                'components': ['top-nav', 'hero-card', 'action-dock'],
                'assetIds': ['brand-logo', 'hero-illustration'],
                'actions': [
                    {'label': '主按钮操作', 'intent': '跳转到关联画板或触发状态切换', 'stateEffect': '更新画板预览状态'},
                ],
                'dataBindings': [
                    {'label': '页面标题', 'source': 'Design/UI/Site/screens.js', 'format': '文本', 'example': s['name']},
                ],
            }

        spec = {
            'schemaVersion': 1,
            'standardVersion': '1.1.0',
            'standardRef': standard_ref,
            'project': {
                'id': pid,
                'name': name,
                'platforms': platforms,
                'orientation': orientation,
                'designScope': '维护可分层审阅与类 Figma 拖拽调整的 HTML 设计画板、组件规格与素材清单，支持 AI/MCP 协同编辑。',
                'sources': {
                    'screens': 'Design/UI/Site/screens.js',
                    'artboards': 'Design/UI/Site/artboards.js',
                    'styles': 'Design/UI/Site/artboards.css',
                    'assets': 'Design/Assets/manifest.json',
                    'layerReviewAdapter': 'Design/UI/Site/layer-review-adapter.js',
                    'layerTransforms': 'Design/layer-transforms.json',
                },
            },
            'layout': {
                'coordinates': '左上角原点，x 向右、y 向下；单位为画板像素',
                'safeArea': '画板四周预留安全边距，核心交互控件居中或停靠安全区',
                'scale': orientation,
            },
            'components': {
                'top-nav': {
                    'description': '顶部导航栏与状态信息',
                    'source': 'Design/UI/Site/artboards.js#renderTopNav',
                    'assetIds': ['brand-logo'],
                },
                'hero-card': {
                    'description': '主视觉展示卡片与核心内容区',
                    'source': 'Design/UI/Site/artboards.js#renderHeroCard',
                    'assetIds': ['hero-illustration'],
                },
                'action-dock': {
                    'description': '底部或主操作按钮组',
                    'source': 'Design/UI/Site/artboards.js#renderActionDock',
                    'assetIds': [],
                },
            },
            'screenContracts': screen_contracts,
            'assetDefaults': {
                'sourceConfirmation': 'recorded',
                'licenseStatus': 'confirmed',
            },
            'assetOverrides': {},
            'assetGroups': [
                {
                    'id': 'core-ui',
                    'name': '核心界面素材',
                    'assetIds': ['brand-logo', 'hero-illustration'],
                }
            ],
            'implementationTasks': [
                {
                    'id': 'TASK-01',
                    'label': f'完成 {name} 核心画板设计与组件微调',
                    'status': 'pending',
                    'screens': [s['id'] for s in screens_list],
                    'assetIds': ['brand-logo', 'hero-illustration'],
                    'detail': '在 LeafLoom 设计工作台中调整各画板图层位置与尺寸，确认交互状态。',
                    'acceptance': '所有画板图层清晰可操作，契约检查通过。',
                    'dependencies': [],
                }
            ],
        }
        atomic_write(design_dir / 'project-spec.json', (json.dumps(spec, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))

        # Write layer-transforms.json and layer-transforms-data.js
        transforms_doc = {'schemaVersion': 1, 'projectId': pid, 'updatedAt': '', 'boards': {}}
        atomic_write(design_dir / 'layer-transforms.json', (json.dumps(transforms_doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        atomic_write(site_dir / 'layer-transforms-data.js', b'window.DESIGN_LAYER_TRANSFORMS = {};\n')

        # Write screens.js and custom-screens.js
        self._write_screens_js(site_dir / 'screens.js', screens_list, [])
        atomic_write(site_dir / 'custom-screens.js', b'window.CUSTOM_ARTBOARDS = window.CUSTOM_ARTBOARDS || {};\n')

        # Write artboards.css, artboards.js, layer-review-adapter.js, screen.html, ui-gallery.html, site.js, site.css
        self._write_site_runtime_files(proj_dir, design_dir, site_dir, pid, name, width, height, orientation, platforms)

        # Write Wiki README.md in project root
        readme_md = (
            f'# {name}\n\n'
            f'- **项目标识**：`{pid}`\n'
            f'- **画板规格**：`{width} × {height}`（{orientation}）\n'
            f'- **设计入口**：[打开设计门户](Design/index.html) · [打开画板工作台](Design/UI/Site/ui-gallery.html)\n'
            f'- **结构化规格**：[Design/project-spec.json](Design/project-spec.json)\n'
            f'- **图层变换记录**：[Design/layer-transforms.json](Design/layer-transforms.json)\n\n'
            f'## 画板列表\n\n'
            + '\n'.join(f"- **{s['name']}** (`{s['id']}`)：{s['caption']}" for s in screens_list)
            + '\n'
        )
        atomic_write(proj_dir / 'README.md', readme_md.encode('utf-8'))

    def _write_screens_js(self, path: Path, screens: list[dict], variants: list[dict]) -> None:
        boards = screens + variants
        payload = json.dumps({'screens': screens, 'variants': variants, 'boards': boards}, ensure_ascii=False, indent=2)
        js = (
            '/* Auto-maintained by LeafLoom Design Studio */\n'
            f'const __data = /*__LEAFLOOM_SCREENS_JSON__*/ {payload} /*__END_LEAFLOOM_SCREENS_JSON__*/;\n'
            'const screens = __data.screens;\n'
            'const variants = __data.variants;\n'
            'const boards = __data.boards;\n'
            'function resolveBoardId(id) {\n'
            '  if (boards.some(b => b.id === id)) return id;\n'
            '  return (screens[0] && screens[0].id) || "home";\n'
            '}\n'
            'if (typeof window !== "undefined") {\n'
            '  window.screens = screens; window.variants = variants; window.boards = boards; window.resolveBoardId = resolveBoardId;\n'
            '}\n'
            'if (typeof module !== "undefined" && module.exports) {\n'
            '  module.exports = { screens, variants, boards, resolveBoardId };\n'
            '}\n'
        )
        atomic_write(path, js.encode('utf-8'))

    def _write_site_runtime_files(
        self,
        proj_dir: Path,
        design_dir: Path,
        site_dir: Path,
        pid: str,
        name: str,
        width: int,
        height: int,
        orientation: str,
        platforms: list[str],
    ) -> None:
        artboards_css = """/* Layered Artboard Styles */
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: transparent; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #2b332d; }
.artboard { position: relative; overflow: hidden; background: linear-gradient(165deg, #f8f5ec 0%, #e7efe9 100%); display: flex; flex-direction: column; justify-content: space-between; padding: 36px 32px; user-select: none; }
.ds-bg-decor { position: absolute; inset: 0; pointer-events: none; background: radial-gradient(circle at 85% 12%, #cfe2d4 0%, transparent 45%); }
.ds-top-nav { position: relative; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 20px; border-radius: 20px; background: rgba(255, 255, 255, 0.86); border: 1px solid #d5dfd7; box-shadow: 0 8px 24px rgba(45, 68, 54, 0.06); }
.ds-brand { display: flex; align-items: center; gap: 12px; }
.ds-brand img { height: 42px; width: auto; display: block; }
.ds-badge { padding: 6px 14px; border-radius: 999px; background: #e3efe6; color: #355e44; font-size: 13px; font-weight: 600; }
.ds-main-stage { position: relative; z-index: 2; flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 24px; margin: 24px 0; }
.ds-hero-card { padding: 28px; border-radius: 28px; background: rgba(255, 255, 255, 0.92); border: 1px solid #d4dfd7; box-shadow: 0 16px 36px rgba(45, 68, 54, 0.08); display: flex; flex-direction: column; gap: 16px; }
.ds-hero-visual { width: 100%; border-radius: 18px; overflow: hidden; display: flex; justify-content: center; background: #f2f6f3; }
.ds-hero-visual img { max-width: 100%; height: auto; display: block; }
.ds-title { margin: 0; font-size: 32px; line-height: 1.25; color: #1f2922; }
.ds-subtitle { margin: 0; font-size: 16px; line-height: 1.6; color: #5b695f; }
.ds-feature-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.ds-feature-card { padding: 20px; border-radius: 20px; background: rgba(255, 255, 255, 0.85); border: 1px solid #dce5de; display: flex; flex-direction: column; gap: 8px; }
.ds-feature-card strong { font-size: 17px; color: #2b3c31; }
.ds-feature-card span { font-size: 13px; color: #67756b; }
.ds-action-dock { position: relative; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 22px; border-radius: 24px; background: rgba(255, 255, 255, 0.92); border: 1px solid #d4dfd7; box-shadow: 0 10px 28px rgba(45, 68, 54, 0.08); }
.ds-btn { appearance: none; border: 1px solid #c3d2c7; background: #f5f8f6; color: #2d4234; padding: 14px 24px; border-radius: 16px; font-size: 16px; font-weight: 600; cursor: pointer; flex: 1; text-align: center; }
.ds-btn.primary { background: #4c7c60; border-color: #3d664e; color: #ffffff; }
"""
        atomic_write(site_dir / 'artboards.css', artboards_css.encode('utf-8'))

        artboards_js = """/* Layered Artboard Renderer */
const params = new URLSearchParams(location.search);
const requestedId = params.get('id') || (screens[0] && screens[0].id) || 'home';
const id = resolveBoardId(requestedId);
const s = boards.find(b => b.id === id) || screens[0];
const root = document.querySelector('#artboard');
root.style.width = (s.width || 720) + 'px';
root.style.height = (s.height || 1560) + 'px';
root.className = 'artboard ' + (s.kind || s.id);
document.title = s.name + ' · 设计画板';

function renderDefaultBoard(board) {
  const nextBoard = boards.find(b => b.id !== board.id) || board;
  return `
    <div class="ds-bg-decor" data-layer-id="${board.id}/bg-decor" data-layer-name="背景装饰层" data-layer-type="background"></div>
    <header class="ds-top-nav" data-layer-id="${board.id}/top-nav" data-layer-name="顶部导航栏" data-layer-type="group">
      <div class="ds-brand" data-layer-id="${board.id}/brand-group" data-layer-name="品牌标识组" data-layer-type="group">
        <img src="../../Assets/Generated/brand-logo.svg" alt="品牌标识" data-layer-id="${board.id}/brand-logo" data-layer-name="品牌 Logo" data-layer-type="image" data-asset-id="brand-logo" data-download-url="../../Assets/Generated/brand-logo.svg">
      </div>
      <span class="ds-badge" data-layer-id="${board.id}/group-badge" data-layer-name="画板分组标签" data-layer-type="text">${board.group || '核心页面'} · #${board.number || '01'}</span>
    </header>
    <section class="ds-main-stage" data-layer-id="${board.id}/main-stage" data-layer-name="核心内容舞台" data-layer-type="group">
      <article class="ds-hero-card" data-layer-id="${board.id}/hero-card" data-layer-name="主视觉卡片" data-layer-type="group">
        <div class="ds-hero-visual" data-layer-id="${board.id}/hero-visual" data-layer-name="主视觉插画容器" data-layer-type="group">
          <img src="../../Assets/Generated/hero-illustration.svg" alt="${board.name}" data-layer-id="${board.id}/hero-image" data-layer-name="主视觉插画" data-layer-type="image" data-asset-id="hero-illustration" data-download-url="../../Assets/Generated/hero-illustration.svg">
        </div>
        <h1 class="ds-title" data-layer-id="${board.id}/title" data-layer-name="画板主标题" data-layer-type="text">${board.name}</h1>
        <p class="ds-subtitle" data-layer-id="${board.id}/subtitle" data-layer-name="画板副标题与说明" data-layer-type="text">${board.caption || ''}</p>
      </article>
      <div class="ds-feature-grid" data-layer-id="${board.id}/feature-grid" data-layer-name="功能模块网格" data-layer-type="group">
        <div class="ds-feature-card" data-layer-id="${board.id}/card-1" data-layer-name="状态卡片 A" data-layer-type="group">
          <strong data-layer-id="${board.id}/card-1-title" data-layer-name="卡片 A 标题" data-layer-type="text">${(board.states && board.states[0]) || '默认状态'}</strong>
          <span data-layer-id="${board.id}/card-1-desc" data-layer-name="卡片 A 描述" data-layer-type="text">支持画布直接拖拽移动、8点控制柄缩放与旋转</span>
        </div>
        <div class="ds-feature-card" data-layer-id="${board.id}/card-2" data-layer-name="状态卡片 B" data-layer-type="group">
          <strong data-layer-id="${board.id}/card-2-title" data-layer-name="卡片 B 标题" data-layer-type="text">${(board.states && board.states[1]) || 'AI / MCP 协同'}</strong>
          <span data-layer-id="${board.id}/card-2-desc" data-layer-name="卡片 B 描述" data-layer-type="text">支持将图层添加到 AI 对话或通过 MCP 批量调整</span>
        </div>
      </div>
    </section>
    <footer class="ds-action-dock" data-layer-id="${board.id}/action-dock" data-layer-name="底部操作栏" data-layer-type="group">
      <button class="ds-btn primary" data-target="${nextBoard.id}" data-layer-id="${board.id}/primary-btn" data-layer-name="主操作按钮" data-layer-type="button">
        <span data-layer-id="${board.id}/primary-btn-label" data-layer-name="主按钮文案" data-layer-type="text">前往：${nextBoard.name}</span>
      </button>
      <button class="ds-btn" data-target="home" data-layer-id="${board.id}/secondary-btn" data-layer-name="次操作按钮" data-layer-type="button">
        <span data-layer-id="${board.id}/secondary-btn-label" data-layer-name="次按钮文案" data-layer-type="text">返回首页</span>
      </button>
    </footer>
  `;
}

if (window.CUSTOM_ARTBOARDS && typeof window.CUSTOM_ARTBOARDS[s.id] === 'string') {
  root.innerHTML = window.CUSTOM_ARTBOARDS[s.id];
} else {
  root.innerHTML = renderDefaultBoard(s);
}

if (params.get('mode') !== 'review') {
  root.addEventListener('click', event => {
    const btn = event.target.closest('[data-target]');
    if (!btn) return;
    const target = resolveBoardId(btn.dataset.target);
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: 'ds-navigate-board', id: target }, '*');
    } else {
      location.search = '?id=' + encodeURIComponent(target);
    }
  });
}
"""
        atomic_write(site_dir / 'artboards.js', artboards_js.encode('utf-8'))

        adapter_js = """/* Layer Review & Figma Transform Adapter */
(() => {
  'use strict';
  if (!window.GameDesignLayers || !root) return;

  const layers = [];
  const seen = new Set();

  function collectLayers() {
    const annotated = [...root.querySelectorAll('[data-layer-id]')];
    if (annotated.length > 0) {
      annotated.forEach(el => {
        const id = el.dataset.layerId;
        if (!id || seen.has(id)) return;
        seen.add(id);
        const parentEl = el.parentElement ? el.parentElement.closest('[data-layer-id]') : null;
        layers.push({
          id,
          parentId: parentEl ? parentEl.dataset.layerId : null,
          name: el.dataset.layerName || el.getAttribute('aria-label') || el.textContent.trim().slice(0, 24) || id,
          type: el.dataset.layerType || (el.children.length ? 'group' : 'text'),
          element: el,
          assetId: el.dataset.assetId || '',
          downloadUrl: el.dataset.downloadUrl || (el.tagName === 'IMG' ? el.getAttribute('src') : ''),
          sourceRef: 'Design/UI/Site/artboards.js',
        });
      });
      return;
    }

    // Automatic semantic fallback for custom HTML snippets without data-layer-id
    let counter = 0;
    function walk(node, parentId) {
      [...node.children].forEach(el => {
        const lid = el.id ? `${s.id}/${el.id}` : `${s.id}/node-${++counter}`;
        const isGroup = el.children.length > 0 && !['BUTTON', 'H1', 'H2', 'H3', 'P', 'SPAN', 'SVG'].includes(el.tagName);
        const type = el.tagName === 'IMG' ? 'image' : el.tagName === 'SVG' ? 'svg' : el.tagName === 'BUTTON' ? 'button' : isGroup ? 'group' : 'text';
        layers.push({
          id: lid,
          parentId,
          name: el.getAttribute('aria-label') || el.className || el.tagName.toLowerCase(),
          type,
          element: el,
          downloadUrl: el.tagName === 'IMG' ? el.getAttribute('src') : '',
          sourceRef: 'Design/UI/Site/custom-screens.js',
        });
        if (isGroup) walk(el, lid);
      });
    }
    walk(root, null);
  }

  collectLayers();
  const savedForBoard = (window.DESIGN_LAYER_TRANSFORMS && window.DESIGN_LAYER_TRANSFORMS[s.id]) || {};

  if (params.get('mode') === 'review') {
    window.COZY_LAYER_REVIEW = window.GameDesignLayers.mountCanvas({
      root,
      boardId: s.id,
      session: params.get('reviewSession') || s.id,
      layers,
      initialTransforms: savedForBoard,
    });
  } else {
    window.GameDesignLayers.applySavedTransforms(root, layers, savedForBoard);
  }
})();
"""
        atomic_write(site_dir / 'layer-review-adapter.js', adapter_js.encode('utf-8'))

        screen_html = (
            f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{name} · 页面设计画板</title>'
            f'<link rel="stylesheet" href="artboards.css">'
            f'<link rel="stylesheet" href="../../Standards/1.1.0/tools/layer_review/layer_review.css">'
            f'</head><body><main id="artboard"></main>'
            f'<script src="screens.js"></script>'
            f'<script src="custom-screens.js"></script>'
            f'<script src="layer-transforms-data.js"></script>'
            f'<script src="artboards.js"></script>'
            f'<script src="../../Standards/1.1.0/tools/layer_review/layer_review.js"></script>'
            f'<script src="layer-review-adapter.js"></script>'
            f'</body></html>\n'
        )
        atomic_write(site_dir / 'screen.html', screen_html.encode('utf-8'))

        site_css = """/* Gallery & Layer Workbench Shell */
* { box-sizing: border-box; }
body { margin: 0; background: #f4EFE6; color: #3a3228; font: 14px/1.5 system-ui, -apple-system, sans-serif; }
.gallery-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 16px 24px; background: #fffdf8; border-bottom: 1px solid #dfd6c5; }
.gallery-header h1 { margin: 0; font-size: 20px; }
.gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 18px; padding: 24px; }
.design-card { appearance: none; text-align: left; border: 1px solid #dcd2c0; border-radius: 16px; background: #fffdf9; padding: 18px; cursor: pointer; display: flex; flex-direction: column; gap: 8px; transition: transform .15s, box-shadow .15s; }
.design-card:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(60, 48, 32, 0.08); border-color: #9ab3a1; }
.design-card h3 { margin: 0; font-size: 17px; color: #2b352e; }
.design-card p { margin: 0; color: #6e6253; font-size: 13px; }
.design-card .card-tag { align-self: flex-start; padding: 3px 9px; border-radius: 999px; background: #e5efe7; color: #396046; font-size: 11px; font-weight: 600; }
dialog#viewer { width: 100vw; height: 100vh; max-width: 100vw; max-height: 100vh; margin: 0; padding: 0; border: 0; background: #ebe4d6; }
.viewer-shell { display: flex; flex-direction: column; width: 100%; height: 100%; }
.viewer-topbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 10px 18px; background: #fffdf8; border-bottom: 1px solid #dcd2c0; }
.viewer-tabs, .viewer-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.viewer-topbar button { appearance: none; padding: 6px 12px; border: 1px solid #cfc4b0; border-radius: 8px; background: #f8f3e8; color: #3a3228; font: inherit; cursor: pointer; }
.viewer-topbar button[aria-pressed="true"], .viewer-topbar button.active { background: #4c7c60; border-color: #3d664e; color: #fff; font-weight: 600; }
.viewer-workspace { flex: 1; min-height: 0; display: grid; grid-template-columns: 260px minmax(320px, 1fr) 320px; }
.viewer-panel { overflow: auto; background: #fffdf8; border-right: 1px solid #dfd6c5; }
.viewer-panel.right { border-right: 0; border-left: 1px solid #dfd6c5; }
.viewer-panel-title { margin: 0; padding: 12px 14px 4px; font-size: 13px; font-weight: 700; color: #6c5e4c; }
.viewer-stage { position: relative; overflow: hidden; display: flex; align-items: center; justify-content: center; background: #e5dec9; }
#viewer-prototype { position: absolute; left: 50%; top: 50%; border: 0; border-radius: 20px; box-shadow: 0 16px 42px rgba(45, 36, 24, 0.18); background: #fff; transform-origin: center center; }
"""
        atomic_write(site_dir / 'site.css', site_css.encode('utf-8'))

        site_js = """/* Gallery & Workbench Controller */
const grid = document.querySelector('#gallery-grid');
const dialog = document.querySelector('#viewer');
const boardSelect = document.querySelector('#board-switcher');
let active = screens[0], viewerMode = 'review', reviewPanel = null, reviewSerial = 0;

function renderGallery() {
  grid.innerHTML = boards.map(b => `
    <button class="design-card" data-open="${b.id}">
      <span class="card-tag">${b.group || '核心页面'} · ${b.width || 720}×${b.height || 1560}</span>
      <h3>${b.name}</h3>
      <p>${b.caption || ''}</p>
    </button>
  `).join('');
  if (boardSelect) {
    boardSelect.innerHTML = boards.map(b => `<option value="${b.id}">${b.name} (${b.id})</option>`).join('');
  }
}

function fitPrototype() {
  if (!dialog.open) return;
  const stage = document.querySelector('.viewer-stage');
  const frame = document.querySelector('#viewer-prototype');
  const w = active.width || 720, h = active.height || 1560;
  const scale = Math.max(0.1, Math.min((stage.clientWidth - 48) / w, (stage.clientHeight - 48) / h));
  frame.style.width = w + 'px';
  frame.style.height = h + 'px';
  frame.style.transform = `translate(${-w / 2}px, ${-h / 2}px) scale(${scale})`;
}

function updatePrototype() {
  if (reviewPanel) { reviewPanel.destroy(); reviewPanel = null; }
  const frame = document.querySelector('#viewer-prototype');
  document.querySelectorAll('[data-review-mode]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.reviewMode === viewerMode)));
  const query = new URLSearchParams({ id: active.id });
  if (viewerMode === 'review') {
    const session = active.id + '-' + (++reviewSerial);
    query.set('mode', 'review');
    query.set('reviewSession', session);
    reviewPanel = GameDesignLayers.mountPanel({
      tree: document.querySelector('#layer-tree'),
      inspector: document.querySelector('#layer-inspector'),
      frame,
      boardId: active.id,
      session,
    });
  } else {
    document.querySelector('#layer-tree').textContent = '切回图层设计模式后查看与编辑图层树。';
    document.querySelector('#layer-inspector').textContent = '当前为交互演示模式，点击画板内按钮可测试页面跳转。';
  }
  frame.src = 'screen.html?' + query.toString();
  fitPrototype();
  requestAnimationFrame(fitPrototype);
}

function openBoard(id, updateHash = true) {
  active = boards.find(b => b.id === resolveBoardId(id)) || screens[0];
  if (boardSelect) boardSelect.value = active.id;
  document.querySelector('#viewer-title').textContent = active.name + ' (' + (active.width || 720) + '×' + (active.height || 1560) + ')';
  if (!dialog.open) dialog.showModal();
  updatePrototype();
  if (updateHash && location.hash !== '#screen=' + active.id) {
    history.replaceState(null, '', '#screen=' + active.id);
  }
}

document.addEventListener('click', e => {
  const opener = e.target.closest('[data-open]');
  if (opener) openBoard(opener.dataset.open);
});
if (boardSelect) {
  boardSelect.addEventListener('change', () => openBoard(boardSelect.value));
}
document.querySelectorAll('[data-review-mode]').forEach(b => {
  b.addEventListener('click', () => { viewerMode = b.dataset.reviewMode; updatePrototype(); });
});
document.querySelector('#review-reset').addEventListener('click', () => reviewPanel && reviewPanel.reset());
document.querySelector('#viewer-close').addEventListener('click', () => dialog.close());
window.addEventListener('resize', fitPrototype);
window.addEventListener('message', event => {
  if (event.data && event.data.type === 'ds-navigate-board' && event.data.id) {
    openBoard(event.data.id);
  }
  if (event.data && event.data.type === 'leafloom-design-reload-transforms' && reviewPanel) {
    if (!event.data.boardId || event.data.boardId === active.id) {
      reviewPanel.importTransforms(event.data.transforms || {});
    }
  }
});

renderGallery();
const hashMatch = location.hash.match(/^#screen=(.+)$/);
openBoard(hashMatch ? decodeURIComponent(hashMatch[1]) : screens[0].id, false);
"""
        atomic_write(site_dir / 'site.js', site_js.encode('utf-8'))

        ui_gallery_html = (
            f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{name} · 设计画板工作台</title>'
            f'<link rel="stylesheet" href="../../Standards/1.1.0/tools/layer_review/layer_review.css">'
            f'<link rel="stylesheet" href="site.css">'
            f'</head><body>'
            f'<header class="gallery-header"><h1>{name} · 画板总览</h1><span>点击任一画板进入类 Figma 图层编辑</span></header>'
            f'<main id="gallery-grid" class="gallery-grid"></main>'
            f'<dialog id="viewer"><div class="viewer-shell">'
            f'<header class="viewer-topbar">'
            f'<div class="viewer-tabs">'
            f'<strong id="viewer-title">{name}</strong>'
            f'<select id="board-switcher" aria-label="切换画板"></select>'
            f'</div>'
            f'<div class="viewer-actions">'
            f'<button type="button" data-review-mode="review" aria-pressed="true">图层设计 (Figma 模式)</button>'
            f'<button type="button" data-review-mode="prototype" aria-pressed="false">交互演示</button>'
            f'<button type="button" id="review-reset">重置本画板</button>'
            f'<button type="button" id="viewer-close">画板墙</button>'
            f'</div>'
            f'</header>'
            f'<div class="viewer-workspace">'
            f'<aside id="viewer-layer-panel" class="viewer-panel"><h2 class="viewer-panel-title">组件与图层树</h2><div id="layer-tree"></div></aside>'
            f'<section class="viewer-stage"><iframe id="viewer-prototype" title="画板画布"></iframe></section>'
            f'<aside id="viewer-property-panel" class="viewer-panel right"><h2 class="viewer-panel-title">属性、对齐与导出</h2><div id="layer-inspector"></div></aside>'
            f'</div></div></dialog>'
            f'<script src="screens.js"></script>'
            f'<script src="../../Standards/1.1.0/tools/layer_review/layer_review.js"></script>'
            f'<script src="site.js"></script>'
            f'</body></html>\n'
        )
        atomic_write(site_dir / 'ui-gallery.html', ui_gallery_html.encode('utf-8'))

        design_index_html = (
            f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{name} · 设计门户</title>'
            f'<style>html,body,iframe{{width:100%;height:100%;margin:0;border:0;display:block}}</style>'
            f'</head><body><iframe id="ui-frame" src="UI/Site/ui-gallery.html" title="{name} 设计工作台"></iframe></body></html>\n'
        )
        atomic_write(design_dir / 'index.html', design_index_html.encode('utf-8'))

        root_index_html = (
            f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{name}</title>'
            f'<style>html,body,iframe{{width:100%;height:100%;margin:0;border:0;display:block}}</style>'
            f'</head><body><iframe src="Design/UI/Site/ui-gallery.html" title="{name} 设计工作台"></iframe></body></html>\n'
        )
        atomic_write(proj_dir / 'index.html', root_index_html.encode('utf-8'))

    def upsert_screen(
        self,
        directory: str,
        screen_id: str,
        name: str,
        *,
        workspace_revision: str | None = None,
        group: str = '核心页面',
        caption: str = '',
        width: int | None = None,
        height: int | None = None,
        html: str | None = None,
        css: str | None = None,
    ) -> dict[str, Any]:
        with self.config.lock, self.files.lock:
            self._check_workspace(workspace_revision)
            root = self.config.root
            directory = relative(directory)
            proj_dir = self.config.path_for(directory, writable=True) if directory else root
            spec_file = self._find_spec_file(proj_dir)
            if spec_file is None:
                raise FileNotFoundError(f'No Design/project-spec.json found in {directory}')

            sid = _slug(screen_id or name, fallback='screen')
            sname = (name or sid).strip()
            spec = json.loads(spec_file.read_text(encoding='utf-8'))
            sources = spec.get('project', {}).get('sources', {})
            screens_rel = sources.get('screens', 'Design/UI/Site/screens.js')
            screens_path = (proj_dir / screens_rel).resolve()
            if not screens_path.is_relative_to(proj_dir):
                raise ValueError('Invalid screens source path')

            screens, variants, boards = self._parse_screens_file(screens_path)
            default_w = (screens[0].get('width') if screens else 720) or 720
            default_h = (screens[0].get('height') if screens else 1560) or 1560
            w = int(width or default_w)
            h = int(height or default_h)

            existing = next((s for s in screens if s.get('id') == sid), None)
            if existing is not None:
                existing['name'] = sname
                existing['group'] = group or existing.get('group', '核心页面')
                existing['caption'] = caption or existing.get('caption', '')
                existing['width'] = w
                existing['height'] = h
            else:
                screens.append({
                    'id': sid,
                    'number': f'{len(screens) + 1:02d}',
                    'name': sname,
                    'group': group or '核心页面',
                    'kind': sid,
                    'width': w,
                    'height': h,
                    'caption': caption or f'{sname}设计与组件分层',
                    'states': ['默认态', '选中态'],
                    'notes': [f'画板尺寸 {w}×{h}，支持类 Figma 图层编辑与 AI 协同。'],
                })

            changed_paths = []
            if screens_path.is_file():
                self.files._history(screens_path)
            if screens_path.suffix.lower() == '.json':
                atomic_write(screens_path, (json.dumps({'screens': screens, 'variants': variants, 'boards': screens + variants}, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            else:
                self._write_screens_js(screens_path, screens, variants)
            changed_paths.append(screens_path.relative_to(root).as_posix())

            # Update project-spec.json screenContracts
            self.files._history(spec_file)
            contracts = spec.setdefault('screenContracts', {})
            if sid not in contracts:
                contracts[sid] = {
                    'designStatus': 'draft',
                    'implementationStatus': 'pending',
                    'validationStatus': 'pending',
                    'recipeCoverage': 'partial',
                    'summary': caption or f'{sname}设计与组件分层',
                    'conditions': ['从画板切换器或导航进入'],
                    'layout': [f'基准画板 {w}×{h}'],
                    'components': [],
                    'assetIds': [],
                    'actions': [],
                    'dataBindings': [],
                }
            else:
                contracts[sid]['summary'] = caption or contracts[sid].get('summary', sname)
            atomic_write(spec_file, (json.dumps(spec, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            changed_paths.append(spec_file.relative_to(root).as_posix())

            site_dir = screens_path.parent
            if html is not None:
                custom_js_path = site_dir / 'custom-screens.js'
                custom_map = {}
                if custom_js_path.is_file():
                    self.files._history(custom_js_path)
                    m = re.search(r'window\.CUSTOM_ARTBOARDS\s*=\s*(\{.*\})\s*;', custom_js_path.read_text(encoding='utf-8'), re.S)
                    if m:
                        try:
                            custom_map = json.loads(m.group(1))
                        except Exception:
                            custom_map = {}
                custom_map[sid] = html
                atomic_write(
                    custom_js_path,
                    ('window.CUSTOM_ARTBOARDS = ' + json.dumps(custom_map, ensure_ascii=False, indent=2) + ';\n').encode('utf-8'),
                )
                changed_paths.append(custom_js_path.relative_to(root).as_posix())

            if css is not None and css.strip():
                css_path = site_dir / 'artboards.css'
                if css_path.is_file():
                    self.files._history(css_path)
                    old_css = css_path.read_text(encoding='utf-8')
                else:
                    old_css = ''
                marker_start = f'/* screen:{sid}:start */'
                marker_end = f'/* screen:{sid}:end */'
                block = f'{marker_start}\n{css.strip()}\n{marker_end}'
                if marker_start in old_css and marker_end in old_css:
                    pattern = re.compile(re.escape(marker_start) + r'.*?' + re.escape(marker_end), re.S)
                    new_css = pattern.sub(block, old_css)
                else:
                    new_css = old_css.rstrip() + '\n\n' + block + '\n'
                atomic_write(css_path, new_css.encode('utf-8'))
                changed_paths.append(css_path.relative_to(root).as_posix())

            self.files.changed(*changed_paths)
            self.runtime.events.publish({'type': 'files', 'paths': changed_paths})
            return {
                'ok': True,
                'directory': directory,
                'screen_id': sid,
                'project': self._project_summary(proj_dir, root),
                'workspace_revision': self.workspace_revision,
            }

    def check_project(self, directory: str) -> dict[str, Any]:
        root = self.config.root
        directory = relative(directory)
        proj_dir = self.config.path_for(directory) if directory else root
        spec_file = self._find_spec_file(proj_dir)
        if spec_file is None:
            return {'ok': False, 'directory': directory, 'errors': ['Missing Design/project-spec.json'], 'warnings': []}

        errors: list[str] = []
        warnings: list[str] = []
        try:
            spec = json.loads(spec_file.read_text(encoding='utf-8'))
        except Exception as exc:
            return {'ok': False, 'directory': directory, 'errors': [f'Invalid project-spec.json: {exc}'], 'warnings': []}

        # If the project references a standard with check_design.py in the vault, run it first
        std_ref = str(spec.get('standardRef', '')).split('#', 1)[0]
        if std_ref:
            std_path = (spec_file.parent / std_ref).resolve()
            checker = std_path.parent / 'tools' / 'check_design.py'
            if checker.is_file() and checker.is_relative_to(root):
                try:
                    import os, sys
                    ext_path = os.environ.get('PATH', '') + os.pathsep + '/opt/homebrew/bin' + os.pathsep + '/usr/local/bin'
                    res = subprocess.run(
                        [sys.executable, str(checker), '--project', str(proj_dir)],
                        capture_output=True, text=True, timeout=20,
                        env={**os.environ, 'PATH': ext_path},
                    )
                    out = json.loads(res.stdout)
                    if out.get('ok'):
                        return {
                            'ok': True,
                            'directory': directory,
                            'summary': out,
                            'errors': [],
                            'warnings': out.get('warnings', []),
                            'workspace_revision': self.workspace_revision,
                        }
                    errors.append(str(out.get('error') or 'External contract check failed'))
                except Exception:
                    pass

        # Built-in contract verification
        proj = spec.get('project') if isinstance(spec.get('project'), dict) else {}
        sources = proj.get('sources') if isinstance(proj.get('sources'), dict) else {}
        screens_rel = sources.get('screens', 'Design/UI/Site/screens.js')
        assets_rel = sources.get('assets', 'Design/Assets/manifest.json')
        screens_path = (proj_dir / screens_rel).resolve()
        assets_path = (proj_dir / assets_rel).resolve()

        screens, variants, boards = self._parse_screens_file(screens_path) if screens_path.is_file() else ([], [], [])
        if not boards:
            errors.append(f'No screens or boards found in {screens_rel}')

        contracts = spec.get('screenContracts') if isinstance(spec.get('screenContracts'), dict) else {}
        board_ids = {b.get('id') for b in boards if isinstance(b, dict) and b.get('id')}
        for bid in sorted(board_ids):
            if bid not in contracts:
                warnings.append(f'Board {bid} is missing an entry in screenContracts')

        asset_count = 0
        if assets_path.is_file():
            try:
                manifest = json.loads(assets_path.read_text(encoding='utf-8'))
                for asset in manifest.get('assets', []):
                    asset_count += 1
                    apath = assets_path.parent / asset.get('path', '')
                    if not apath.is_file():
                        errors.append(f"Missing asset file: {asset.get('path')}")
                    elif asset.get('sha256'):
                        actual = hashlib.sha256(apath.read_bytes()).hexdigest()
                        if actual != asset['sha256']:
                            errors.append(f"SHA-256 mismatch for asset {asset.get('id')}: {asset.get('path')}")
            except Exception as exc:
                errors.append(f'Invalid asset manifest: {exc}')
        else:
            warnings.append(f'Asset manifest not found at {assets_rel}')

        transforms = self._read_transforms_file(proj_dir)
        return {
            'ok': len(errors) == 0,
            'directory': directory,
            'summary': {
                'project': proj.get('name') or proj_dir.name,
                'standardVersion': spec.get('standardVersion', '1.1.0'),
                'screens': len(screens),
                'variants': len(variants),
                'boards': len(boards),
                'assets': asset_count,
                'transformedBoards': len(transforms),
            },
            'errors': errors,
            'warnings': warnings,
            'workspace_revision': self.workspace_revision,
        }
