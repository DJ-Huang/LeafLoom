"""Conservative, read-only reference planning for attachment moves.

Only recognized static destination spans are changed. This is deliberately not a
JavaScript interpreter: scripts and unsupported document references require review.
The caller must revalidate snapshots before applying this plan atomically.
"""
from __future__ import annotations

import html
import posixpath
import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote

from vault_rag.platform_support import path_key

MAX_TEXT_BYTES = 10 * 1024 * 1024
_STATIC = {'.md', '.markdown', '.html', '.htm', '.css', '.svg'}
_BINARY = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif', '.ico', '.bmp',
           '.tif', '.tiff', '.mp3', '.wav', '.ogg', '.flac', '.mp4', '.webm',
           '.mov', '.avi', '.woff', '.woff2', '.ttf', '.otf', '.pdf', '.zip',
           '.7z', '.gz', '.tar', '.exe', '.dll', '.so', '.dylib', '.m4a',
           '.aac', '.m4v', '.doc', '.xls', '.ppt', '.rar', '.bz2',
           '.docx', '.xlsx', '.pptx', '.odt', '.ods', '.odp', '.epub'}


def _masked(text, spans):
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            if chars[i] not in '\r\n':
                chars[i] = ' '
    return ''.join(chars)


def _markdown_code(text):
    spans = []
    fence = None
    offset = 0
    for line in text.splitlines(keepends=True):
        match = re.match(r' {0,3}(`{3,}|~{3,})', line)
        if fence:
            spans.append((offset, offset + len(line)))
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence):
                fence = None
        elif match:
            fence = match[1]
            spans.append((offset, offset + len(line)))
        elif line.startswith(('    ', '\t')):
            spans.append((offset, offset + len(line)))
        offset += len(line)
    clean = _masked(text, spans)
    for match in re.finditer(r'(`+)([^`]|(?!\1)`)*?\1(?!`)', clean):
        spans.append(match.span())
    return spans



def _list_indented_lines(text):
    """Return indented list continuations whose code/link context is ambiguous.

    Four spaces alone do not establish an indented code block inside a list.
    Until a full CommonMark block parser is available, require review rather
    than silently exempting these possible live attachment destinations.
    """
    in_list = False
    fence = None
    for line in text.splitlines():
        match = re.match(r' {0,3}(`{3,}|~{3,})', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence):
                fence = None
            continue
        if match:
            fence = match[1]
            continue
        if re.match(r'^\s*(?:[-+*]|[0-9]+[.)])\s+', line):
            in_list = True
        elif line.strip() and not line[0].isspace():
            in_list = False
        if in_list and line.startswith(('    ', '\t')):
            yield line


def _destination(text, start):
    """Return a Markdown destination span, respecting escapes and balanced ()."""
    n = len(text)
    while start < n and text[start] in ' \t\r\n':
        start += 1
    if start >= n:
        return None
    if text[start] == '<':
        end = start + 1
        while end < n:
            if text[end] == '\\':
                end += 2
                continue
            if text[end] == '>':
                return start + 1, end
            if text[end] in '\r\n':
                return None
            end += 1
        return None
    end, depth = start, 0
    while end < n:
        c = text[end]
        if c == '\\':
            end += 2
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            if depth == 0:
                break
            depth -= 1
        elif c.isspace():
            break
        end += 1
    return (start, end) if end > start and depth == 0 else None


def _spans(text, suffix):
    """Yield (start, end, syntax) without normalizing any surrounding markup."""
    ignored = _markdown_code(text) if suffix in {'.md', '.markdown'} else []
    ignored += [m.span() for m in re.finditer(r'<!--.*?-->', text, re.S)]
    clean = _masked(text, ignored)
    if suffix in {'.md', '.markdown'}:
        for m in re.finditer(r'(?<!\\)\[\[([^\]\r\n]+)\]\]', clean):
            end = m.start(1) + len(m[1].split('|', 1)[0])
            yield m.start(1), end, 'wiki'
        for m in re.finditer(r'(?<!\\)\]\(', clean):
            span = _destination(clean, m.end())
            if span:
                yield *span, 'markdown'
        for m in re.finditer(r'^ {0,3}\[[^\]\r\n]+\]:[ \t]*', clean, re.M):
            span = _destination(clean, m.end())
            if span:
                yield *span, 'markdown'
    # Script bodies are never interpreted as HTML or CSS. Attribute destinations
    # on the opening script element (src) remain static and can be changed.
    script_bodies = [m.span(1) for m in re.finditer(
        r'<script\b[^>]*>(.*?)</script\s*>', clean, re.I | re.S)]
    clean = _masked(clean, script_bodies)
    if suffix != '.css':
        tag_re = r'<[a-zA-Z][^>"\']*(?:(?:"[^"]*"|\'[^\']*\')[^>"\']*)*>'
        attr_re = r'(?<![\w:-])(src|href|xlink:href|poster|srcset|style|data|background)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))'
        for tag in re.finditer(tag_re, clean, re.S):
            for m in re.finditer(attr_re, tag[0], re.I | re.S):
                group = next(g for g in (2, 3, 4) if m[g] is not None)
                start = tag.start() + m.start(group)
                kind = m[1].lower()
                if kind == 'style':
                    continue  # CSS scanner handles url() in the original span.
                if kind == 'srcset':
                    # A data URL contains commas: leave it alone, flag via the
                    # unhandled-reference check if a local moved asset is mixed in.
                    if 'data:' in m[group].lower():
                        continue
                    for part in re.finditer(r'(?:^|,)\s*([^\s,]+)', m[group]):
                        yield start + part.start(1), start + part.end(1), 'html'
                else:
                    yield start, start + len(m[group]), 'html'
    for m in re.finditer(r'url\(\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s)]+))\s*\)', clean, re.I):
        group = next(g for g in (1, 2, 3) if m[g] is not None)
        yield m.start(group), m.end(group), 'css'
    for m in re.finditer(r'@import\s+(?:"([^"]*)"|\'([^\']*)\')', clean, re.I):
        group = 1 if m[1] is not None else 2
        yield m.start(group), m.end(group), 'css'


def plan_references(files, mapping: dict[str, str], paths: set[str], *, scan_paths=None):
    """Plan safe static rewrites; never mutate a file or execute its contents.

    ``paths`` is the caller's complete guarded original-file snapshot. Blockers
    make the entire migration non-applicable, even when some edits were planned.
    ``scan_paths`` optionally limits source inspection without narrowing target
    resolution. References counts recognized references affected by relocation.
    """
    result = {'edits': {}, 'blockers': [], 'references': 0}
    if not mapping:
        return result
    paths = set(paths)
    basename, by_key = {}, {}
    for path in paths:
        basename.setdefault(path_key(PurePosixPath(path).name), []).append(path)
        by_key.setdefault(path_key(path), []).append(path)
    moved = {path_key(path): new for path, new in mapping.items()}
    moved_names = {path_key(PurePosixPath(path).name) for path in mapping}

    def block(source, reason, target=None):
        value = {'path': source, 'reason': reason}
        if target is not None:
            value['target'] = target
        if value not in result['blockers']:
            result['blockers'].append(value)

    def relevant(text):
        decoded = path_key(unquote(html.unescape(text)))
        return any(name in decoded for name in moved_names)

    scan_keys = None if scan_paths is None else {path_key(p) for p in scan_paths}
    for source in sorted(p for p in paths if scan_keys is None or path_key(p) in scan_keys):
        suffix = PurePosixPath(source).suffix.lower()
        if suffix in _BINARY:
            continue
        try:
            path = files.config.path_for(source)
            if path.stat().st_size > MAX_TEXT_BYTES:
                block(source, 'Reference scan exceeds 10 MiB text limit')
                continue
            before = path.read_bytes()
            text = before.decode('utf-8')
        except UnicodeDecodeError:
            block(source, 'Unsupported non-UTF-8 document may contain attachment references')
            continue
        except (OSError, ValueError) as exc:
            block(source, 'Cannot safely read reference source: ' + str(exc))
            continue
        # Arbitrary scripts can construct a path without any literal filename.
        # Do not mistake absence of a matching string for proof of no dependency.
        dynamic = bool(text.strip())
        if suffix not in _STATIC:
            if relevant(text) or path_key(source) in moved or (suffix in {'.js', '.mjs', '.cjs', '.ts', '.jsx', '.tsx'} and dynamic):
                block(source, 'Unsupported source format or dynamic reference requires manual review')
            continue
        if suffix in {'.html', '.htm', '.svg'} and (any(m[1].strip() for m in re.finditer(r'<script\b[^>]*>(.*?)</script\s*>', text, re.I | re.S)) or re.search(r'\bon\w+\s*=|\bsrcdoc\s*=', text, re.I)):
            block(source, 'Script-generated resource references require manual dependency review')
        if suffix in {'.html', '.htm', '.svg'} and re.search(r'<base\b', text, re.I):
            block(source, 'HTML base URL changes dependency resolution; manual review required')
        if suffix in {'.md', '.markdown'} and any(relevant(line) for line in _list_indented_lines(text)):
            block(source, 'Indented Markdown list attachment may be live content; manual reference review required')
        replacements = []
        handled = []
        spans = sorted(set(_spans(text, suffix)))
        for start, end, syntax in spans:
            if handled and start < handled[-1][1]:
                continue
            handled.append((start, end))
            raw = text[start:end]
            target = html.unescape(raw) if syntax == 'html' else raw
            if syntax == 'markdown':
                target = re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\\\]^_`{|}~])', r'\1', target)
            if re.match(r'^(?:[a-z][a-z0-9+.-]*:|//|#|\?)', target, re.I):
                continue
            split = re.match(r'^([^?#]*)(.*)$', target, re.S)
            link, trailer = unquote(split[1]), split[2]
            if not link:
                continue
            if '\\' in link or '\x00' in link:
                block(source, 'Unsupported escaped attachment destination', raw)
                continue
            relative = posixpath.normpath(posixpath.join(posixpath.dirname(source), link))
            root = posixpath.normpath(link.lstrip('/'))
            candidates = (by_key.get(path_key(root), []) if link.startswith('/') else
                          by_key.get(path_key(relative), []))
            if not candidates:
                candidates = by_key.get(path_key(root), []) or basename.get(path_key(PurePosixPath(link).name), [])
            if len(candidates) > 1:
                if any(path_key(p) in moved for p in candidates):
                    block(source, 'Ambiguous attachment destination', raw)
                continue
            if not candidates:
                if relevant(raw):
                    block(source, 'Unresolved attachment destination requires manual review', raw)
                continue
            old = candidates[0]
            if path_key(old) not in moved and path_key(source) not in moved:
                continue
            new = moved.get(path_key(old), old)
            new_source = moved.get(path_key(source), source)
            if syntax == 'wiki':
                # Literal separators in a filename must not become a wiki
                # fragment, alias, closing delimiter, or URL scheme on rewrite.
                rewritten = re.sub(r'[%#?|\[\]:]', lambda m: quote(m[0], safe=''), new)
            elif link.startswith('/'):
                rewritten = '/' + new
            else:
                rewritten = posixpath.relpath(new, posixpath.dirname(new_source) or '.')
            if syntax != 'wiki':
                rewritten = quote(rewritten, safe='/.-_~')
            rewritten += trailer
            if syntax == 'html':
                rewritten = html.escape(rewritten, quote=True)
            if rewritten != raw:
                replacements.append((start, end, rewritten))
            result['references'] += 1
        # Any occurrence outside known static spans is deliberately surfaced,
        # including scripts, JSON/config values, HTML event handlers, and paths
        # split across unsupported syntax. Code examples in Markdown are exempt.
        ignored = handled + (_markdown_code(text) if suffix in {'.md', '.markdown'} else [])
        remaining = _masked(text, ignored)
        if relevant(remaining):
            block(source, 'Unrecognized or dynamic attachment reference requires manual review')
        # Moving a script-bearing HTML source can change relative fetch/import
        # behavior even when no literal moved basename appears.
        if path_key(source) in moved and re.search(r'<script\b(?![^>]*\bsrc\s*=)[^>]*>\s*\S', text, re.I):
            block(source, 'Moving HTML with inline scripts requires manual dependency review')
        if replacements:
            after = text
            for start, end, value in reversed(replacements):
                after = after[:start] + value + after[end:]
            result['edits'][source] = {'before': before, 'after': after.encode('utf-8')}
    return result


def discover_project_dependencies(files, paths: set[str], project_roots: set[str]):
    """Protect HTML projects and their transitive static external dependencies.

    This only reads bounded UTF-8 sources, never edits or executes them. Unknown
    script behavior, base-URL overrides, unreadable sources, and escaped resource
    destinations are explicit blockers. Literal JS strings are inspected to
    protect discoverable dependencies even when script review is still required.
    """
    paths = set(paths)
    by_key = {}
    for path in paths:
        by_key.setdefault(path_key(path), []).append(path)
    roots = {path_key(root.rstrip('/')) for root in project_roots}
    protected = {path for path in paths if any(
        not root or root == '.' or path_key(path) == root or path_key(path).startswith(root + '/')
        for root in roots)}
    result = {'protected': protected, 'blockers': []}
    source_types = {'.html', '.htm', '.css', '.svg', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'}
    pending = sorted(p for p in protected if PurePosixPath(p).suffix.lower() in source_types)
    seen = set()

    def block(source, reason, target=None):
        entry = {'path': source, 'reason': reason}
        if target is not None:
            entry['target'] = target
        if entry not in result['blockers']:
            result['blockers'].append(entry)

    def protect_target(source, raw, syntax):
        target = html.unescape(raw) if syntax == 'html' else raw
        if re.match(r'^(?:[a-z][a-z0-9+.-]*:|//|#|\?)', target, re.I):
            return
        target = unquote(re.split(r'[?#]', target, maxsplit=1)[0])
        if not target:
            return
        if '\\' in target or '\x00' in target:
            block(source, 'Escaped HTML project dependency requires manual review', raw)
            return
        # Web references are source-relative (or root-absolute), never basename
        # fallback: that fallback belongs only to the note-link resolver.
        candidate = posixpath.normpath(target.lstrip('/') if target.startswith('/') else
                                       posixpath.join(posixpath.dirname(source), target))
        candidates = by_key.get(path_key(candidate), [])
        for candidate in candidates:
            if PurePosixPath(candidate).suffix.lower() not in source_types | _BINARY:
                block(source, 'Unsupported HTML project dependency format requires manual review', raw)
            if candidate not in protected:
                protected.add(candidate)
                if PurePosixPath(candidate).suffix.lower() in source_types:
                    pending.append(candidate)

    def inspect_script(source, script):
        clean = re.sub(r'/\*.*?\*/|//[^\r\n]*', '', script, flags=re.S)
        for match in re.finditer(r'"([^"\r\n]*)"|\'([^\'\r\n]*)\'', script):
            protect_target(source, match[1] if match[1] is not None else match[2], 'js')
        # Static module imports have a known base and destination. Anything else
        # can construct/obfuscate URLs; the planner must not certify its safety.
        residue = re.sub(r'\bimport\s+(?:(?:[^;\r\n]*?)\s+from\s+)?["\'][^"\']+["\']\s*;?', '', clean)
        if residue.strip():
            block(source, 'HTML project script may construct external asset paths; manual dependency review required')

    while pending:
        source = pending.pop()
        if source in seen:
            continue
        seen.add(source)
        try:
            path = files.config.path_for(source)
            if path.stat().st_size > MAX_TEXT_BYTES:
                block(source, 'HTML project dependency scan exceeds 10 MiB limit')
                continue
            text = path.read_bytes().decode('utf-8-sig')
        except (UnicodeDecodeError, OSError, ValueError) as exc:
            block(source, 'Cannot safely inspect HTML project dependencies: ' + str(exc))
            continue
        suffix = PurePosixPath(source).suffix.lower()
        if suffix in {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'}:
            inspect_script(source, text)
            continue
        if re.search(r'<base\b|\bsrcdoc\s*=|\bon\w+\s*=', text, re.I):
            block(source, 'HTML project has custom base or dynamic markup; manual dependency review required')
        if re.search(r'srcset\s*=\s*[\"\'][^\"\']*data:', text, re.I):
            block(source, 'Mixed data-URL srcset requires manual dependency review')
        if re.search(r'style\s*=\s*[\"\'][^\"\']*&', text, re.I):
            block(source, 'Entity-encoded inline style requires manual dependency review')
        for start, end, syntax in _spans(text, suffix):
            protect_target(source, text[start:end], syntax)
        for script in re.finditer(r'<script\b[^>]*>(.*?)</script\s*>', text, re.I | re.S):
            inspect_script(source, html.unescape(script[1]))
    return result
