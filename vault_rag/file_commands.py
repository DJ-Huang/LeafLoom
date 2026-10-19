"""Typed commands for the two public file tools; no arbitrary command dispatch."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from typing_extensions import NotRequired, TypedDict
from pydantic import BaseModel, ConfigDict, Field


class ChatFile(TypedDict):
    download_url: str
    file_id: str
    mime_type: NotRequired[str]
    file_name: NotRequired[str]


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ListFiles(Command):
    action: Literal['list']
    query: str = ''
    kind: Literal['all', 'image', 'pdf', 'audio', 'video', 'other'] = 'all'
    sort: Literal['name', 'modified', 'size', 'path'] = 'modified'
    order: Literal['asc', 'desc'] = 'desc'
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str = ''


class StatFile(Command):
    action: Literal['stat']
    path: str
    source_note: str = ''


class ReadFile(Command):
    action: Literal['read']
    expected_revision: str
    path: str = ''
    job_id: str = ''
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=65536, ge=1, le=262144)


class ExportFiles(Command):
    action: Literal['export']
    paths: list[str] = Field(min_length=1, max_length=100)


class FileStatus(Command):
    action: Literal['status']
    job_id: str = ''
    section: Literal['jobs', 'moves', 'references', 'blockers', 'exclusions', 'results'] = 'jobs'
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str = ''


ReadCommand = Annotated[Union[ListFiles, StatFile, ReadFile, ExportFiles, FileStatus], Field(discriminator='action')]


class UploadFiles(Command):
    action: Literal['upload']
    source: Literal['files']
    folder: str = ''


class BeginUpload(Command):
    action: Literal['upload']
    source: Literal['begin']
    name: str
    size: int = Field(ge=0, le=268435456)
    sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')
    folder: str = ''


class AppendUpload(Command):
    action: Literal['upload']
    source: Literal['chunk']
    job_id: str
    offset: int = Field(ge=0)
    data_base64: str = Field(max_length=349528)


class FinishUpload(Command):
    action: Literal['upload']
    source: Literal['commit', 'abort']
    job_id: str


UploadCommand = Annotated[Union[UploadFiles, BeginUpload, AppendUpload, FinishUpload], Field(discriminator='source')]


class MoveFiles(Command):
    action: Literal['move']
    paths: list[str] = Field(min_length=1, max_length=100)
    destination: str
    destination_kind: Literal['folder', 'path'] = 'folder'


class TrashFiles(Command):
    action: Literal['trash']
    paths: list[str] = Field(min_length=1, max_length=100)


class OrganizeFiles(Command):
    action: Literal['organize']
    destination: str = '_attachments'


class ReindexFiles(Command):
    action: Literal['reindex']


class UpdateJob(Command):
    action: Literal['job']
    job_id: str
    command: Literal['execute', 'cancel', 'resume', 'undo']
    expected_revision: str = ''
    confirm: bool = False


WriteCommand = Annotated[Union[UploadCommand, MoveFiles, TrashFiles, OrganizeFiles, ReindexFiles, UpdateJob], Field(discriminator='action')]
