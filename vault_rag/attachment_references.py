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
# These are retained engineering artifacts, not UTF-8 reference documents.
_BINARY |= {'.blend', '.blend1', '.blend2', '.glb', '.fbx', '.apk', '.aab',
            '.unitypackage', '.uasset', '.umap', '.psd', '.ai', '.pdb', '.bytes'}
OPAQUE_RESOURCE_TYPES = frozenset(_BINARY)
REFERENCE_TEXT = _STATIC | {'.txt', '.base', '.js', '.mjs', '.cjs', '.ts', '.tsx',
                            '.jsx', '.json', '.yaml', '.yml', '.xml', '.toml',
                            '.ini', '.cfg', '.py', '.csv', '.srt', '.vtt', '.log', '.gltf'}


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
    css_escape=r'\\(?:[0-9a-fA-F]{1,6}(?:\r\n|[ \t\r\n\f])?|[^\r\n])'
    css_unquoted='(?:'+css_escape+r'|[^\s)\\])+'
    for m in re.finditer(r'url\(\s*(?:"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'|('+css_unquoted+r'))\s*\)', clean, re.I):
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
                if syntax=='css' or relevant(raw) or path_key(source) in moved:
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


def discover_project_dependencies(files, paths: set[str], project_roots: set[str], *, reference_sources=()):
    """Protect HTML projects and their transitive static external dependencies.

    Whole project scopes stay in place, including dynamic scripts. Static file
    references and literal directory prefixes retain shared resources outside
    those scopes transitively. Unreadable dependency sources still fail closed.
    """
    paths = set(paths)
    root_prefix = files.config.root.as_posix().rstrip('/') + '/'
    root_key = path_key(root_prefix)
    reference_sources = set(reference_sources)
    by_key = {}
    basename = {}
    directories = {}
    for path in paths:
        by_key.setdefault(path_key(path), []).append(path)
        basename.setdefault(path_key(PurePosixPath(path).name), []).append(path)
        for parent in PurePosixPath(path).parents:
            directories.setdefault(path_key(str(parent)), []).append(path)
    directory_names={path_key(PurePosixPath(p).name) for p in directories}
    roots = {path_key(root.rstrip('/')) for root in project_roots}
    protected = {path for path in paths if any(
        not root or root == '.' or path_key(path) == root or path_key(path).startswith(root + '/')
        for root in roots)}
    protected.update(set(reference_sources) & paths)
    result = {'protected': protected, 'blockers': []}
    source_types = REFERENCE_TEXT | {PurePosixPath(p).suffix.lower() for p in reference_sources}
    pending = sorted(p for p in protected if PurePosixPath(p).suffix.lower() in source_types)
    seen = set()
    scope_cache = {}

    def script_unescape(match):
        value=match[0][1:]
        if value.startswith('u{'):return chr(int(value[2:-1],16))
        if value.startswith(('u','x')) and len(value)>1:return chr(int(value[1:],16))
        return {'n':'\n','r':'\r','t':'\t','b':'\b','f':'\f','v':'\v','0':'\x00',
                '\n':'','\r\n':''}.get(value,value)

    def block(source, reason, target=None):
        entry = {'path': source, 'reason': reason}
        if target is not None:
            entry['target'] = target
        if entry not in result['blockers']:
            result['blockers'].append(entry)

    def protect_target(source, raw, syntax):
        # Large configuration/geometry files contain many scalar tokens. A
        # bare token can name a dependency only if that name exists. Keep URL,
        # escape, markup and directory-prefix forms for full resolution below.
        if raw not in {'.','..'} and not any(c in raw for c in '/\\<%?#$&'):
            key=path_key(raw)
            if key not in basename and key not in directory_names:return
        target = html.unescape(raw) if syntax == 'html' else raw
        if syntax=='css':
            target=re.sub(r'\\(?:([0-9a-fA-F]{1,6})(?:\r\n|[ \t\r\n\f])?|(\r\n|[\r\n\f])|(.))',
                          lambda m:chr(int(m[1],16)) if m[1] and 0<int(m[1],16)<=0x10ffff else
                          '' if m[2] else m[3] or '\ufffd',target)
        if syntax == 'js' and '\\' in target:
            try:
                target = re.sub(r'\\(?:u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|\r?\n|.)',script_unescape,target)
            except ValueError:
                block(source, 'Escaped HTML project dependency requires manual review')
                return
        # Serialized markup is content, not a single escaped filename. Inspect
        # its static destinations without dumping the embedded text as an error.
        if '<' in target:
            for start,end,kind in _spans(target,'.html'):
                protect_target(source,target[start:end],kind)
            return
        if len(target)>4096:return
        target = target.split('${', 1)[0]
        target = target.replace('\\','/')
        local_absolute = path_key(target).startswith(root_key)
        if not local_absolute and re.match(r'^(?:[a-z][a-z0-9+.-]*:|//|#|\?)', target, re.I):
            return
        target = unquote(re.split(r'[?#]', target, maxsplit=1)[0])
        if not target:
            return
        if '\x00' in target or any(c in target for c in '\r\n'):
            return
        # Rooted web URLs resolve inside the retained project, not the vault.
        if source not in scope_cache:
            source_key=path_key(source)
            scopes=[root for root in roots if root in ('','.') or source_key.startswith(root+'/')]
            scope_cache[source]=max(scopes,key=len) if scopes else posixpath.dirname(source)
        scope=scope_cache[source]
        candidate = posixpath.normpath(posixpath.join(scope,target.lstrip('/')) if target.startswith('/') else
                                       posixpath.join(posixpath.dirname(source), target))
        # Configurations sometimes use vault-relative or absolute local paths.
        candidates = list(by_key.get(path_key(candidate), []))
        candidates += by_key.get(path_key(target.lstrip('/')), [])
        if local_absolute:
            local=path_key(posixpath.normpath(target[len(root_prefix):]))
            candidates += by_key.get(local, []) + directories.get(local, [])
        # Literal folder prefixes can be completed dynamically. Retain their
        # entire subtree, not just the file names we happen to see in scripts.
        if candidate != '.' or target.endswith('/'):
            candidates += directories.get(path_key(candidate), [])
        if not candidates and '/' not in target:
            candidates = basename.get(path_key(target), [])
        for candidate in candidates:
            if candidate not in protected:
                protected.add(candidate)
                if PurePosixPath(candidate).suffix.lower() in source_types:
                    pending.append(candidate)

    def inspect_script(source, script):
        for match in re.finditer(r'(["\'`])((?:\\.|(?!\1)[^\\\r\n])*)\1', script):
            protect_target(source, match[2], 'js')
        # Also retain unquoted INI/YAML/config paths. This scanner only adds
        # exclusions and never attempts to rewrite configuration or code.
        if PurePosixPath(source).suffix.lower() not in {'.js','.mjs','.cjs','.ts','.tsx','.jsx','.py'}:
            for match in re.finditer(r'[^\s"\'`<>()\[\]{},;:=]+', script):
                protect_target(source, match[0], 'js')

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
        if suffix not in _STATIC:
            inspect_script(source, text)
            continue
        # Scan markup strings too: base paths, event handlers and mixed srcsets
        # may contain external literal resources even though markup stays put.
        decoded=html.unescape(text)
        for start, end, syntax in _spans(decoded, suffix):
            protect_target(source, decoded[start:end], syntax)
        if suffix=='.css':inspect_script(source,text)
        for attr in re.finditer(r'\b(on\w+|srcdoc|srcset)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',text,re.I):
            value=html.unescape(attr[2] if attr[2] is not None else attr[3])
            if attr[1].lower()=='srcdoc':protect_target(source,value,'html')
            elif attr[1].lower()=='srcset':
                for part in re.finditer(r'(?:^|,)\s*([^\s,]+)',value):
                    protect_target(source,part[1],'html')
            else:inspect_script(source,value)
        for script in re.finditer(r'<script\b[^>]*>(.*?)</script\s*>', text, re.I | re.S):
            inspect_script(source, html.unescape(script[1]))
    return result
