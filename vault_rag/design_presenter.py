"""Private speaker notes stay in managed source and history, never audience output."""
import copy


def audience_document(document):
    result = copy.deepcopy(document)
    for page in result.get('pages', []):
        page.pop('presenterNotes', None)
    return result


def validate_notes(notes):
    if not isinstance(notes, dict) or set(notes) - {'overview', 'cues'}:
        raise ValueError('Presenter notes require overview and cues')
    if not isinstance(notes.get('overview', ''), str):
        raise ValueError('Presenter overview must be text')
    cues = notes.get('cues', {})
    if not isinstance(cues, dict) or any(not isinstance(k, str) or not k or len(k) > 200 or not isinstance(v, str) for k, v in cues.items()):
        raise ValueError('Presenter cues require stable IDs and text')
