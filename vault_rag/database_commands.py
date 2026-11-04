"""Discoverable public database commands; execution stays in the shared service."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class CreateDatabase(Command):
    type: Literal['create']
    folder: str = Field(default='', description='Record folder. Omit to create a sibling folder named after the .base.')
    preset: Literal['tasks'] | None = None


class SetField(Command):
    type: Literal['field.set']
    key: str = Field(description='Stable property key; renaming only changes displayName.')
    field: dict[str, Any] = Field(description='Merge into field definition: type text|number|select|multiselect|date|checkbox|url|attachment, options, optionMeta. Set allowCustomOptions:false for managed choices, including an empty list. Unknown settings are preserved.')
    displayName: str | None = None
    detail_view_id: str | None = Field(default=None, description='Optional view whose record detail layout is updated atomically with the field. Supply together with detail_fields.')
    detail_fields: list[str] | None = Field(default=None, description='Existing visible detail field keys. The saved field key is appended; no record content is changed.')
    task_setup: dict[str, Any] | None = Field(default=None, description='Optional task status mapping saved atomically with option changes: statusField, priorityField, dueField, initialStatus, completedStatuses. Existing note values are preserved.')


class RemoveField(Command):
    type: Literal['field.remove']
    key: str = Field(description='Remove configuration only; Markdown property values are preserved.')


class AddView(Command):
    type: Literal['view.add']
    view: dict[str, Any] = Field(description='name, type (table|list|cards|leafloomTimeline|leafloomBoard), order, sort, groupBy, leafloom. Omit leafloom.id for a generated stable ID.')
    preset: Literal['tasks'] | None = None
    task_setup: dict[str, Any] | None = Field(default=None, description='statusField, priorityField, dueField, initialStatus, completedStatuses; existing compatible fields are reused.')


class UpdateView(Command):
    type: Literal['view.update']
    view_id: str
    patch: dict[str, Any] = Field(description='Partial view configuration. name; order (visible field order); sort [{property,direction:ASC|DESC}]; groupBy {property,direction}; filters; leafloom {conditions:[{field,operator,value}], detailFields (visible record detail keys), detailExtraOrder (collapsed property order), widths, coverField, cardSize, fit, startField, endField, board:{groupOrder,hiddenGroups,collapsedGroups,hideEmpty}}. Use returned group keys in column lists. Empty arrays clear sort/filters. Unknown settings are preserved.')
    task_setup: dict[str, Any] | None = None


class RemoveView(Command):
    type: Literal['view.remove']
    view_id: str = Field(description='Remove a view, preserving records; retain at least one view.')


class MoveView(Command):
    type: Literal['view.move']
    view_id: str = Field(description='Stable ID of the view to reposition; preserves its settings, records and embeds.')
    before_view_id: str | None = Field(default=None, description='Insert before this view. Supply exactly one of before_view_id or after_view_id.')
    after_view_id: str | None = None


class CreateRecord(Command):
    type: Literal['record.create']
    title: str = ''
    values: dict[str, Any] = Field(default_factory=dict, description='Typed properties; attachment values are lists of wiki references. Dates use YYYY-MM-DD.')
    view_id: str = Field(default='', description='Creation view (default: first view). Unambiguous writable equality conditions prefill values, including record type; explicit values override these defaults.')
    group_key: str | None = Field(default=None, description='Returned board group key; fills the grouping property.')
    search: str = ''
    return_record: bool = False


class UpdateRecord(Command):
    type: Literal['record.update']
    path: str
    record_revision: str
    values: dict[str, Any] = Field(default_factory=dict, description='Update properties, title, tags, attachment references, status or BOTH timeline date fields atomically. null clears a property. Body editing uses vault_update_note.')


class DuplicateRecord(Command):
    type: Literal['record.duplicate']
    path: str
    record_revision: str
    title: str = ''
    view_id: str = ''
    search: str = ''
    return_record: bool = False


class TrashRecord(Command):
    type: Literal['record.trash']
    path: str
    record_revision: str | None = None
    dry_run: bool = Field(default=True, description='Preview first. Commit with false and the returned operation_token.')
    operation_token: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str = ''


class MoveRecord(Command):
    type: Literal['record.move']
    view_id: str
    path: str
    record_revision: str
    group_key: str = Field(description='Target group key from the board query, including "null" for Ungrouped.')
    catalog_version: int
    before_path: str | None = Field(default=None, description='Insert before this target-column record; mutually exclusive with after_path.')
    after_path: str | None = None
    search: str = ''


class UndoBoard(Command):
    type: Literal['board.undo']
    move_id: str = Field(description='undo_id returned by record.move or board.group.remove. Rejects later changes.')
    path: str = Field(default='', description='Optional affected record path, compatible with UI requests.')


class SetGroup(Command):
    type: Literal['board.group.set']
    view_id: str
    value: str = Field(min_length=1, description='Stable single-select option value. Add if missing; edit its label/color if present, without rewriting note values.')
    label: str | None = None
    color: Literal['gray', 'blue', 'green', 'red', 'orange', 'yellow', 'purple', 'pink'] | None = None


class RecordVersion(Command):
    path: str
    revision: str


class RemoveGroup(Command):
    type: Literal['board.group.remove']
    view_id: str
    group_key: str
    dry_run: bool = Field(default=False, description='Use true for a full preview. Commit with false (or omit), records/catalog_version from preview, and a unique operation_id.')
    records: list[RecordVersion] | None = None
    catalog_version: int | None = None
    target_value: str | None = Field(default=None, description='null moves records to Ungrouped, or supply another existing option. Initial/sole completed task states require an explicit replacement.')


DatabaseCommand = Annotated[Union[CreateDatabase, SetField, RemoveField, AddView, UpdateView, RemoveView, MoveView,
    CreateRecord, UpdateRecord, DuplicateRecord, TrashRecord, MoveRecord, UndoBoard, SetGroup, RemoveGroup], Field(discriminator='type')]


def capabilities():
    """Compact workflows complement the actual tools/list command schema."""
    return {
        'ok': True, 'read_tool': 'vault_database', 'write_tool': 'vault_database_update',
        'read_actions': ['list', 'config', 'query', 'record', 'capabilities'],
        'view_types': ['table', 'list', 'cards', 'leafloomTimeline', 'leafloomBoard'],
        'field_types': ['text', 'number', 'select', 'multiselect', 'date', 'checkbox', 'url', 'attachment'],
        'commands': [v.model_fields['type'].annotation.__args__[0] for v in
                     (CreateDatabase, SetField, RemoveField, AddView, UpdateView, RemoveView, MoveView, CreateRecord,
                      UpdateRecord, DuplicateRecord, TrashRecord, MoveRecord, UndoBoard, SetGroup, RemoveGroup)],
        'workflows': {
            'records': 'record.create/update/duplicate/trash; create inherits unambiguous writable equality conditions from view_id, then column and explicit values override. values.title renames without changing the path; values accepts attachment references.',
            'views': 'view.add/update/remove; view.move reorders a stable view_id with exactly one before_view_id or after_view_id. view.update.patch configures name, visible field order, sort, groupBy, filters and leafloom layout, including detailFields/detailExtraOrder. field.set with detail_view_id/detail_fields creates and shows a property in one save. field.set displayName renames the shared label; field.remove removes its definition but keeps note values and bodies.',
            'gallery': 'view.update.patch.leafloom: coverField, cardSize (small|medium|large), fit (cover|contain).',
            'options': 'field.set.field options and optionMeta add/remove choices or edit labels/colors without rewriting stored values. Omitted displayName is preserved; optional field.set.task_setup saves explicit initial/completed replacements atomically. Record updates may retain their own historical values, never add unknown ones.',
            'timeline': 'Configure startField/endField; record.update.values writes both dates together for scheduling/resizing.',
            'board': 'Query summary, then page each returned group_key. record.move crosses columns or reorders with before_path/after_path; board.undo reverts.',
            'groups': 'board.group.set adds/edits a stable option. view.update.patch.leafloom.board controls groupOrder/hiddenGroups/collapsedGroups/hideEmpty. board.group.remove previews then migrates records and removes the shared option.',
            'tasks': 'create preset:tasks, or view.add/view.update with task_setup and explicit initial/completed states.',
            'body': 'vault_database action:record reads paged Markdown; vault_update_note edits it with workspace_revision and expected_revision.',
            'files': 'vault_move renames/moves a .base or record; vault_delete recycles a .base without its notes. Preview first; vault_list_records/vault_read_record/vault_restore handle history and trash.',
            'attachments': 'vault_files/vault_files_update select, upload and preview attachments; record.update.values stores their wiki references.',
            'embed': 'Use ![[path.base#view=<stable-view-id>]] in Markdown with vault_update_note; the same view configuration is shared.',
        },
        'guards': {'write_permission': 'workspace write grant', 'versions': ['workspace_revision', 'expected_revision', 'record_revision', 'catalog_version (board moves/removal)'],
                   'operation_id': 'Required for create, record.create/duplicate/move, board.undo and committed board.group.remove; reuse for identical retries.',
                   'delete': 'Preview and confirmation token for record trash and file operations; group removal uses the preview snapshot.',
                   'retrieval': 'Database operations never expand RAG selection.'},
        'pagination': {'default': 100, 'maximum': 200, 'recent_paths_maximum': 20},
    }
