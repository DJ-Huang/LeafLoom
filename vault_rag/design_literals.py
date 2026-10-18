"""Inspect/edit legacy metadata without evaluating project JavaScript.

Initializer offsets preserve custom declarations, functions, exports and comments.
Literal reading rejects calls, operators and interpolated code.
"""
from __future__ import annotations
import ast
import copy
import json
import re

TOKEN = re.compile(r'''\s+|//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[A-Za-z_$][\w$]*|\.\.\.|[^\s]''')
IDENTIFIER = re.compile(r'^[A-Za-z_$][\w$]*$')


def tokens(source):
    result, offset = [], 0
    expression_start = {'=', '(', '[', '{', ',', ':', ';', '!', '?', '&', '|', '>', '<', '+', '-', '*', '%', 'return', 'throw', 'case', '=>'}
    while offset < len(source):
        match = TOKEN.match(source, offset)
        if not match:
            raise ValueError('Unsupported JavaScript source')
        value = match[0]
        start, end = match.span()
        offset = end
        if value.isspace() or value.startswith(('//', '/*')):
            continue
        if value == '/' and (not result or result[-1][0] in expression_start):
            index, escaped, character_class = end, False, False
            while index < len(source) and source[index] not in '\r\n':
                character = source[index]
                if escaped:
                    escaped = False
                elif character == '\\':
                    escaped = True
                elif character == '[':
                    character_class = True
                elif character == ']':
                    character_class = False
                elif character == '/' and not character_class:
                    index += 1
                    while index < len(source) and source[index].isalpha():
                        index += 1
                    value, end, offset = source[start:index], index, index
                    break
                index += 1
        result.append((value, start, end))
    return result


def declarations(source):
    """Return simple top-level bindings and exact initializer spans."""
    items, result, depth, index = tokens(source), [], [], 0
    pairs = {'(': ')', '[': ']', '{': '}'}
    while index < len(items):
        value = items[index][0]
        if not depth and value in ('const', 'let', 'var'):
            kind, cursor = value, index + 1
            while cursor + 1 < len(items) and IDENTIFIER.fullmatch(items[cursor][0]):
                name = items[cursor][0]
                if items[cursor + 1][0] != '=':
                    break
                start = cursor + 2
                end, nested, statement_boundary = start, [], False
                while end < len(items):
                    current = items[end][0]
                    if not nested and current in (',', ';'):
                        break
                    if not nested and end > start and any(character in source[items[end - 1][2]:items[end][1]] for character in '\r\n\u2028\u2029'):
                        previous = items[end - 1][0]
                        incomplete = {'=', '.', '+', '-', '*', '/', '%', '&', '|', '^', '!', '?', ':', '<', '>', 'in', 'instanceof', 'await', 'yield', 'new', 'typeof', 'void', 'delete'}
                        next_statement = (IDENTIFIER.fullmatch(current) and current not in ('in', 'instanceof')) or current.startswith(('"', "'")) or current == '{'
                        if previous not in incomplete and next_statement:
                            statement_boundary = True
                            break
                    if current in pairs:
                        nested.append(pairs[current])
                    elif current in (')', ']', '}'):
                        if not nested or current != nested.pop():
                            break
                    end += 1
                if end > start:
                    result.append({'name': name, 'kind': kind, 'start': items[start][1], 'end': items[end - 1][2],
                                   'tokens': [item[0] for item in items[start:end]]})
                if end < len(items) and items[end][0] == ',':
                    cursor = end + 1
                    continue
                index = end - 1 if statement_boundary else end
                break
            if index >= len(items):
                break
            value = items[index][0]
        if value in pairs:
            depth.append(pairs[value])
        elif value in (')', ']', '}') and depth and depth[-1] == value:
            depth.pop()
        index += 1
    return result


def bindings(source):
    result = {item['name'] for item in declarations(source)}
    items, depth = tokens(source), []
    pairs = {'(': ')', '[': ']', '{': '}'}
    for index, (value, _, _) in enumerate(items):
        if not depth and value in ('function', 'class'):
            next_index = index + 1 + (index + 1 < len(items) and items[index + 1][0] == '*')
            if next_index < len(items) and IDENTIFIER.fullmatch(items[next_index][0]):
                result.add(items[next_index][0])
        if value in pairs:
            depth.append(pairs[value])
        elif depth and value == depth[-1]:
            depth.pop()
    return result


def literal_values(source):
    values = {}
    for declaration in declarations(source):
        items, cursor = declaration['tokens'], 0

        def parse(depth=0):
            nonlocal cursor
            if depth > 60 or cursor >= len(items):
                raise ValueError('Unsupported metadata literal')
            token = items[cursor]
            cursor += 1
            if token in ('[', '{'):
                end = ']' if token == '[' else '}'
                result = [] if token == '[' else {}
                while items[cursor] != end:
                    if items[cursor] == '...':
                        cursor += 1
                        spread = parse(depth + 1)
                        result.update(spread) if isinstance(result, dict) else result.extend(spread)
                    elif isinstance(result, dict):
                        key = items[cursor]
                        cursor += 1
                        key = ast.literal_eval(key) if key.startswith(('"', "'")) else key
                        if items[cursor] == ':':
                            cursor += 1
                            result[key] = parse(depth + 1)
                        elif key in values:
                            result[key] = copy.deepcopy(values[key])
                        else:
                            raise ValueError('Unsupported object metadata')
                    else:
                        result.append(parse(depth + 1))
                    if items[cursor] == ',':
                        cursor += 1
                    elif items[cursor] != end:
                        raise ValueError('Metadata contains executable expressions')
                cursor += 1
                return result
            if token.startswith(('"', "'")):
                return ast.literal_eval(token)
            if token.startswith('`') and '${' not in token:
                return token[1:-1]
            if re.fullmatch(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', token):
                return float(token) if any(value in token for value in '.eE') else int(token)
            if token in ('true', 'false', 'null'):
                return {'true': True, 'false': False, 'null': None}[token]
            if token in values:
                value = values[token]
                while cursor < len(items) and items[cursor] in ('.', '['):
                    accessor = items[cursor]
                    cursor += 1
                    if accessor == '.':
                        value = value[items[cursor]]
                        cursor += 1
                    else:
                        key = parse(depth + 1)
                        if items[cursor] != ']':
                            raise ValueError('Invalid metadata accessor')
                        cursor += 1
                        value = value[key]
                return copy.deepcopy(value)
            raise ValueError('Metadata contains executable expressions')

        try:
            value = parse()
            if cursor == len(items):
                values[declaration['name']] = value
        except (ValueError, IndexError, KeyError, TypeError, SyntaxError, AttributeError):
            continue
    return values


def screen_literals(source):
    values = literal_values(source)
    screens, variants = values.get('screens', []), values.get('variants', [])
    if not isinstance(screens, list) or not isinstance(variants, list):
        return None
    if any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in screens + variants):
        return None
    return (screens, variants, screens + variants) if screens else None


def screen_markers(source):
    names = {'/*__LEAFLOOM_SCREENS_JSON__*/', '/*__END_LEAFLOOM_SCREENS_JSON__*/'}
    return [match for match in TOKEN.finditer(source) if match[0] in names]


def marked_screen_data(source):
    markers = screen_markers(source)
    if len(markers) != 2 or markers[0][0] != '/*__LEAFLOOM_SCREENS_JSON__*/' or markers[1][0] != '/*__END_LEAFLOOM_SCREENS_JSON__*/':
        return None
    try:
        value = json.loads(source[markers[0].end():markers[1].start()])
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


def insert_declarations(source, prefix):
    position = 1 if source.startswith('\ufeff') else 0
    items = [item for item in tokens(source) if item[1] >= position]
    cursor = 0
    while cursor + 1 < len(items) and items[cursor][0].startswith(('"', "'")) and items[cursor + 1][0] == ';':
        position = items[cursor + 1][2]
        cursor += 2
    return source[:position] + '\n' + prefix + source[position:]


def replace_screen_metadata(source, screens, variants):
    payload = {'screens': screens, 'variants': variants, 'boards': screens + variants}
    markers = screen_markers(source)
    if len(markers) == 2 and markers[0][0] == '/*__LEAFLOOM_SCREENS_JSON__*/' and markers[1][0] == '/*__END_LEAFLOOM_SCREENS_JSON__*/':
        return source[:markers[0].end()] + ' ' + json.dumps(payload, ensure_ascii=False, indent=2) + ' ' + source[markers[1].start():]
    if markers:
        raise ValueError('Cannot safely update malformed screen metadata markers; original JavaScript was preserved')
    found = {item['name']: item for item in declarations(source) if item['name'] in payload}
    if 'screens' not in found:
        raise ValueError('Cannot safely locate the legacy screens declaration; original JavaScript was preserved')
    values = literal_values(source)
    if any(not isinstance(values.get(key), list) for key in found):
        raise ValueError('Legacy metadata uses executable expressions; original JavaScript was preserved instead of replacing authored logic')
    result = source
    for key, item in sorted(found.items(), key=lambda item: item[1]['start'], reverse=True):
        result = result[:item['start']] + json.dumps(payload[key], ensure_ascii=False, indent=2) + result[item['end']:]
    missing = [key for key in ('variants', 'boards') if key not in found]
    if missing:
        prefix = ''.join('const ' + key + ' = ' + json.dumps(payload[key], ensure_ascii=False, indent=2) + ';\n' for key in missing)
        result = insert_declarations(result, prefix)
    return result
