"""Compare normalized task snapshots; no file writes or network calls."""
import json
import sys

FIELDS = ('summary', 'description', 'assignees', 'due', 'status')


def normalized(field, value, schema_version=1):
    if field == 'assignees':
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise ValueError('assignees must be a list of stable IDs')
        return sorted(set(value))
    if field == 'due':
        if value is None:
            return None
        if schema_version == 2:
            if not isinstance(value, dict):
                raise ValueError('due must be a provider-validated JSON object or null')
            # Round-trip validation rejects non-JSON Python values and NaN/Infinity.
            encoded = json.dumps(value, sort_keys=True, allow_nan=False)
            if json.loads(encoded) != value:
                raise ValueError('due must preserve its JSON structure')
            return value
        if (not isinstance(value, dict) or set(value) != {'timestamp', 'is_all_day'}
                or not isinstance(value['timestamp'], str)
                or not value['timestamp'].isdigit() or type(value['is_all_day']) is not bool):
            raise ValueError('due must preserve timestamp and is_all_day')
        return value
    if not isinstance(value, str) or field == 'status' and value not in {'todo', 'done'}:
        raise ValueError('Invalid normalized ' + field)
    return value


def compare(baseline, local, remote, schema_version=1):
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise ValueError('Unsupported schema_version; expected 1 or 2')
    if not all(isinstance(v, dict) for v in (baseline, local, remote)):
        raise ValueError('baseline, local and remote must be objects')
    result = {'pull': {}, 'push': {}, 'conflicts': {}, 'incomplete': [], 'agreed': {}}
    for field in FIELDS:
        if any(field not in v for v in (baseline, local, remote)):
            result['incomplete'].append(field)
            continue
        old, mine, theirs = [normalized(field, v[field], schema_version)
                             for v in (baseline, local, remote)]
        # JSON distinguishes booleans from numbers; Python's equality does not.
        def equal(left, right):
            if schema_version == 2 and field == 'due':
                return (json.dumps(left, sort_keys=True, allow_nan=False) ==
                        json.dumps(right, sort_keys=True, allow_nan=False))
            return left == right

        if equal(mine, theirs):
            result['agreed'][field] = theirs
        elif equal(mine, old):
            result['pull'][field] = theirs
        elif equal(theirs, old):
            result['push'][field] = mine
        else:
            result['conflicts'][field] = {'baseline': old, 'local': mine, 'remote': theirs}
    return result


def main():
    try:
        value = json.load(sys.stdin)
        result = compare(value['baseline'], value['local'], value['remote'],
                         value.get('schema_version', 1))
    except (ValueError, KeyError, TypeError) as error:
        json.dump({'ok': False, 'error': str(error)}, sys.stdout, ensure_ascii=False)
        return 1
    json.dump({'ok': True, **result}, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
