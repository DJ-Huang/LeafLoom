"""One-off: move HTML/Design assets out of the central attachment folder.

Default is dry-run. Use --apply to write. Close LeafLoom before --apply.

Examples:
  python scripts/localize_html_attachments.py
  python scripts/localize_html_attachments.py --root D:\\DJKnowledge --apply
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vault_rag.attachment_references import discover_project_dependencies, plan_references
from vault_rag.html_projects import HtmlProjects
from vault_rag.local_state import Files, LocalConfig, atomic_write, relative, under
from vault_rag.platform_support import move_exclusive, path_key, state_directory


SCAN = {'.html', '.htm', '.css', '.svg'}


def unique_destination(files: Files, dest: str, reserved: set[str], seed: str) -> str:
    if path_key(dest) not in reserved and not files.config.path_for(dest).exists():
        return dest
    original = PurePosixPath(dest)
    tag = hashlib.sha256(seed.encode()).hexdigest()[:12]
    n = 0
    while True:
        name = original.stem + '--' + tag + ('-' + str(n) if n else '') + original.suffix
        dest = str(original.with_name(name))
        n += 1
        if path_key(dest) not in reserved and not files.config.path_for(dest).exists():
            return dest


def under_directory(paths: set[str], directory: str) -> list[str]:
    return sorted(p for p in paths if p == directory or under(p, directory))


def plan(config: LocalConfig, websites: HtmlProjects) -> dict:
    files = Files(config)
    root = str(config.root)
    folder = relative(config.data.get('attachment_folder', '_attachments'))
    folder_key = path_key(folder)
    print('  walking vault…', flush=True)
    paths = {p.relative_to(config.root).as_posix() for p in files.walk(strict=True)}
    print(f'  {len(paths)} files, {sum(1 for p in websites.projects if p.get("vault")==root)} projects', flush=True)
    projects = [dict(p) for p in websites.projects if p.get('vault') == root]
    reserved = {path_key(p) for p in paths}
    moves: list[dict] = []
    registry: list[dict] = []
    blockers: list[dict] = []
    moved: set[str] = set()

    for project in projects:
        directory = relative(project.get('directory') or '')
        if not directory or directory in {'.', ''}:
            continue
        if path_key(directory) != folder_key and not under(directory, folder):
            continue
        name = PurePosixPath(directory).name or 'project'
        dest_root = 'Web/' + name
        if path_key(dest_root) in reserved or files.config.path_for(dest_root).exists():
            tag = hashlib.sha256(directory.encode()).hexdigest()[:8]
            n = 0
            while True:
                candidate = 'Web/' + name + ('--' + tag if n == 0 else '--' + tag + '-' + str(n))
                if path_key(candidate) not in reserved and not files.config.path_for(candidate).exists():
                    dest_root = candidate
                    break
                n += 1
        reserved.add(path_key(dest_root))
        entry = relative(project.get('entry') or '')
        new_entry = entry
        if entry == directory or under(entry, directory):
            suffix = entry[len(directory):].lstrip('/') if entry != directory else ''
            new_entry = '/'.join(p for p in (dest_root, suffix) if p)
        project_moves = 0
        for path in under_directory(paths, directory):
            if path in moved:
                continue
            source = files.config.path_for(path)
            if not source.is_file():
                continue
            rel = path[len(directory):].lstrip('/')
            dest = '/'.join(p for p in (dest_root, rel) if p)
            dest = unique_destination(files, dest, reserved, path)
            reserved.add(path_key(dest))
            moved.add(path)
            moves.append({'source': path, 'destination': dest, 'kind': 'project'})
            project_moves += 1
        if not project_moves:
            print(f'  skip missing project tree: {directory}', flush=True)
            continue
        registry.append({
            'id': project['id'], 'previous_directory': directory, 'directory': dest_root,
            'previous_entry': entry, 'entry': new_entry, 'spa': bool(project.get('spa')),
        })

    owners: dict[str, list[dict]] = {}
    attachment_paths = {p for p in paths if p == folder or under(p, folder)}
    for project in projects:
        directory = relative(project.get('directory') or '')
        if not directory or directory in {'.', ''}:
            continue
        planned = next((u for u in registry if u['id'] == project['id']), None)
        project_dir = planned['directory'] if planned else directory
        # Only inspect static markup for central deps. Full project JS/JSON trees
        # are too large for a one-off tool; scripted refs show up as blockers below.
        scoped = set(attachment_paths)
        scoped.update(p for p in under_directory(paths, directory) if Path(p).suffix.lower() in SCAN)
        print(f'  scanning deps: {directory} ({len(scoped)} paths)', flush=True)
        deps = discover_project_dependencies(files, scoped, {directory}, reference_sources=())
        blockers.extend(deps['blockers'])
        for path in deps['protected']:
            if path == directory or under(path, directory):
                continue
            if path_key(path) == folder_key or not under(path, folder):
                continue
            if path in moved:
                continue
            owners.setdefault(path, []).append({'project_id': project['id'], 'directory': project_dir})

    for path, claims in sorted(owners.items()):
        if len(claims) > 1:
            blockers.append({'path': path, 'reason': 'Shared HTML project dependency requires manual placement'})
            continue
        claim = claims[0]
        if not files.config.path_for(path).is_file():
            continue
        dest = '/'.join((claim['directory'], 'assets', PurePosixPath(path).name))
        dest = unique_destination(files, dest, reserved, path)
        reserved.add(path_key(dest))
        moved.add(path)
        moves.append({'source': path, 'destination': dest, 'kind': 'dependency', 'project_id': claim['project_id']})

    mapping = {m['source']: m['destination'] for m in moves}
    project_scan = set()
    for project in projects:
        directory = relative(project.get('directory') or '')
        if not directory or directory in {'.', ''}:
            continue
        for path in under_directory(paths, directory):
            if Path(path).suffix.lower() in SCAN:
                project_scan.add(path)
    project_scan |= {m['source'] for m in moves if Path(m['source']).suffix.lower() in SCAN}
    refs = plan_references(files, mapping, paths, scan_paths=project_scan)
    blockers.extend(refs['blockers'])
    return {
        'root': root,
        'folder': folder,
        'moves': moves,
        'registry': registry,
        'edits': refs['edits'],
        'blockers': blockers,
        'references': refs.get('references', 0),
    }


def apply_plan(config: LocalConfig, websites: HtmlProjects, planned: dict) -> None:
    files = Files(config)
    for move in planned['moves']:
        source = files.config.path_for(move['source'], writable=True)
        dest = files.config.path_for(move['destination'], writable=True)
        if not source.is_file():
            raise FileNotFoundError('Missing source: ' + move['source'])
        if dest.exists():
            raise FileExistsError('Destination exists: ' + move['destination'])
        dest.parent.mkdir(parents=True, exist_ok=True)
        move_exclusive(source, dest)
    mapping = {m['source']: m['destination'] for m in planned['moves']}
    for path, edit in planned['edits'].items():
        target = mapping.get(path, path)
        atomic_write(files.config.path_for(target, writable=True), edit['after'])
    for update in planned['registry']:
        websites.register(
            planned['root'], update['directory'], update['entry'],
            update.get('spa', False), update['id'])


def report(planned: dict) -> None:
    print('Vault:', planned['root'])
    print('Attachment folder:', planned['folder'])
    print('Projects to relocate:', len(planned['registry']))
    print('Files to move:', len(planned['moves']))
    print('Static rewrites:', len(planned['edits']), '(refs touched:', planned['references'], ')')
    print('Blockers:', len(planned['blockers']))
    for update in planned['registry'][:50]:
        print('  project', update['previous_directory'], '->', update['directory'])
    for move in planned['moves'][:80]:
        print('  ', move['kind'], move['source'], '->', move['destination'])
    if len(planned['moves']) > 80:
        print('  ...', len(planned['moves']) - 80, 'more moves')
    for item in planned['blockers'][:40]:
        print('  !', item.get('path'), ':', item.get('reason'))
    if len(planned['blockers']) > 40:
        print('  ...', len(planned['blockers']) - 40, 'more blockers')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', help='Vault root (default: LeafLoom connected folder)')
    parser.add_argument('--home', help='LeafLoom state directory (default: platform state dir)')
    parser.add_argument('--apply', action='store_true', help='Perform moves/rewrites (default: dry-run)')
    parser.add_argument('--force', action='store_true', help='Apply even when blockers exist')
    args = parser.parse_args(argv)

    home = Path(args.home).expanduser().resolve() if args.home else state_directory()
    config = LocalConfig(home)
    if args.root:
        config.save({'root': str(Path(args.root).expanduser().resolve())})
    if not config.data.get('root'):
        print('No connected vault. Pass --root PATH.', file=sys.stderr)
        return 2

    websites = HtmlProjects(config, 0)
    print('Planning…', flush=True)
    planned = plan(config, websites)
    report(planned)
    if not args.apply:
        print('\nDry-run only. Re-run with --apply to write (close LeafLoom first).')
        return 1 if planned['blockers'] else 0
    if planned['blockers'] and not args.force:
        print('\nRefusing --apply while blockers remain. Fix them or pass --force.', file=sys.stderr)
        return 3
    if not planned['moves'] and not planned['edits'] and not planned['registry']:
        print('\nNothing to do.')
        return 0
    apply_plan(config, websites, planned)
    print('\nApplied', len(planned['moves']), 'moves,', len(planned['edits']), 'rewrites,',
          len(planned['registry']), 'registry updates.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
