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
    source: Literal['all', 'local', 'remote'] = 'all'
    storage_id: str = ''
    tags: list[str] = Field(default_factory=list, max_length=100)
    category: str = ''
    group_id: str = ''


class StatFile(Command):
    action: Literal['stat']
    path: str = ''
    asset_id: str = ''
    source_note: str = ''


class ReadFile(Command):
    action: Literal['read']
    expected_revision: str
    path: str = ''
    asset_id: str = ''
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


class ListProducts(Command):
    action: Literal['products']
    query: str = Field(default='', max_length=500)
    status: str = Field(default='', max_length=100)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str = ''


class ProductDetails(Command):
    action: Literal['product']
    product_id: str = Field(min_length=1, max_length=200)


class PrepareAssetDownload(Command):
    action: Literal['prepare_download']
    asset_id: str = Field(min_length=1, max_length=200)


class AssetDownloadStatus(Command):
    action: Literal['download_status']
    job_id: str = ''


class ListAttachmentGroups(Command):
    action: Literal['groups']


class SearchAssets(Command):
    action: Literal['search_assets']
    query: str = Field(min_length=1, max_length=4096)
    mode: Literal['hybrid', 'keyword'] = 'hybrid'
    source: Literal['all', 'local', 'remote'] = 'all'
    storage_id: str = ''
    group_id: str = ''
    formats: list[str] = Field(default_factory=list, max_length=30)
    pipeline: Literal['', 'builtin', 'urp', 'hdrp', 'unknown'] = ''
    limit: int = Field(default=5, ge=1, le=20)


class AssetDetails(Command):
    action: Literal['asset_details']
    result_id: str = Field(min_length=1, max_length=200)


class AssetPreview(Command):
    action: Literal['asset_preview']
    result_id: str = Field(min_length=1, max_length=200)
    expected_revision: str


class DeliveryStatus(Command):
    action: Literal['delivery_status']
    job_id: str = Field(pattern=r'^[0-9a-f]{32}$')


ReadCommand = Annotated[Union[SearchAssets, AssetDetails, AssetPreview, DeliveryStatus, ListAttachmentGroups, ListFiles, StatFile, ReadFile, ExportFiles, FileStatus,
    ListProducts, ProductDetails, PrepareAssetDownload, AssetDownloadStatus], Field(discriminator='action')]


class UploadFiles(Command):
    action: Literal['upload']
    source: Literal['files']
    folder: str = ''
    storage_id: str = ''


class InlineUpload(Command):
    action: Literal['upload']
    source: Literal['base64']
    name: str
    data_base64: str = Field(max_length=2796204)
    sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')
    folder: str = ''
    storage_id: str = ''


class BeginUpload(Command):
    action: Literal['upload']
    source: Literal['begin']
    name: str
    size: int = Field(ge=0, le=268435456)
    sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')
    folder: str = ''
    storage_id: str = ''


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


UploadCommand = Annotated[Union[UploadFiles, InlineUpload, BeginUpload, AppendUpload, FinishUpload], Field(discriminator='source')]


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
    storage_id: str = ''


class UpdateFileMetadata(Command):
    action: Literal['metadata']
    path: str = ''
    asset_id: str = ''
    expected_revision: str
    tags: list[str] = Field(default_factory=list, max_length=100)
    category: str = Field(default='', max_length=200)
    description: str = Field(default='', max_length=10000)


class UpdateJob(Command):
    action: Literal['job']
    job_id: str
    command: Literal['execute', 'cancel', 'resume', 'undo']
    expected_revision: str = ''
    confirm: bool = False


class UpdateProduct(Command):
    action: Literal['product_update']
    operation: Literal['initialize', 'sync', 'rebuild', 'official', 'bind', 'personal', 'review',
                       'official_url', 'enrich', 'resolve', 'release_download', 'retry_download']
    product_id: str = ''
    asset_id: str = ''
    storage_id: str = ''
    job_id: str = ''
    url: str = Field(default='', max_length=2000)
    expected_revision: str = ''
    payload: dict = Field(default_factory=dict)


class UpdateAttachmentGroup(Command):
    action: Literal['group_update']
    operation: Literal['create','update','delete','members']
    payload: dict = Field(default_factory=dict)


class DeliverAsset(Command):
    action: Literal['deliver_asset']
    path: str = Field(min_length=1, max_length=8192)
    expected_revision: str


class DeliveryControl(Command):
    action: Literal['delivery_control']
    job_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    command: Literal['retry', 'cancel']
    expected_revision: str


WriteCommand = Annotated[Union[DeliverAsset, DeliveryControl, UpdateAttachmentGroup, UploadCommand, MoveFiles, TrashFiles, OrganizeFiles, ReindexFiles,
    UpdateFileMetadata, UpdateJob, UpdateProduct], Field(discriminator='action')]
