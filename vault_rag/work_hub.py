"""Office preferences shared by the settings UI and the conversational skill."""
import re
from pathlib import PurePosixPath

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from vault_rag.local_state import ConflictError, relative


# Availability describes bundled adapters, not account sign-in or permissions.
OFFICE_PROVIDERS = ('auto', 'local', 'feishu', 'dingtalk', 'wecom', 'notion')
IMPLEMENTED = {'auto', 'local', 'feishu'}
_UNSET = object()


class WorkHubSettings:
    def __init__(self, notes):
        self.notes, self.config = notes, notes.config

    def location(self):
        folder = relative(self.config.data.get('write_targets', {}).get('work_hub', '工作中枢'))
        if not folder:
            raise ValueError('Choose a dedicated work hub folder')
        path = folder + '/配置.md'
        self.config.path_for(path, writable=True)
        parts = PurePosixPath(folder).parts
        for index in range(1, len(parts) + 1):
            parent = self.config.path_for('/'.join(parts[:index]), writable=True)
            if parent.exists() and not parent.is_dir():
                raise ValueError('Choose a dedicated work hub folder')
        return folder, path

    @staticmethod
    def validate(settings):
        if not isinstance(settings, dict):
            raise ValueError('Invalid work hub configuration')
        version = settings.get('schema_version', 1)
        if type(version) is not int or version != 1:
            raise ValueError('Unsupported work hub configuration version')
        providers = settings.get('office_providers') if 'office_providers' in settings else [settings.get('office_provider', 'auto')]
        if (not isinstance(providers, list) or not providers
                or any(not isinstance(provider, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', provider)
                       for provider in providers)):
            raise ValueError('Invalid work hub office provider')
        providers = list(dict.fromkeys(providers))
        if len(providers) > 1 and any(provider in {'auto', 'local'} for provider in providers):
            raise ValueError('Automatic and local modes cannot be combined with office platforms')
        return providers

    def document(self, path):
        try:
            note = self.notes.files.read(path)
        except FileNotFoundError:
            return None, {}
        except IsADirectoryError as error:
            raise ValueError('Invalid work hub configuration') from error
        match = re.match(r'^---\r?\n(.*?)\r?\n---(?:\r?\n|$)', note['text'], re.S)
        if not match:
            raise ValueError('Invalid work hub configuration')
        try:
            metadata = YAML().load(match.group(1))
        except YAMLError as error:
            raise ValueError('Invalid work hub configuration') from error
        if not isinstance(metadata, dict) or 'work_hub' not in metadata:
            raise ValueError('Invalid work hub configuration')
        self.validate(metadata['work_hub'])
        return note, metadata['work_hub']

    def read(self, root=None):
        with self.config.lock:
            if root is not None and root != str(self.config.root):
                raise ConflictError('Workspace changed; reload work hub settings')
            folder, path = self.location()
            note, settings = self.document(path)
            providers = self.validate(settings)
            return {'root': str(self.config.root), 'folder': folder, 'path': path,
                    'workspace_revision': self.notes.workspace_revision,
                    'revision': note['etag'] if note else '', 'configured': note is not None,
                    'office_providers': providers,
                    'office_provider': providers[0] if len(providers) == 1 else None,
                    'implemented': all(provider in IMPLEMENTED for provider in providers),
                    'providers': [{'id': key, 'implemented': key in IMPLEMENTED}
                                  for key in OFFICE_PROVIDERS]}

    def write(self, *, root, workspace_revision, revision, office_provider=_UNSET, office_providers=_UNSET):
        if (office_provider is _UNSET) == (office_providers is _UNSET):
            raise ValueError('Invalid work hub office provider')
        providers = self.validate({'office_providers': office_providers} if office_providers is not _UNSET
                                  else {'office_provider': office_provider})
        with self.config.lock, self.notes.files.lock:
            self.notes.check_workspace(workspace_revision)
            if root != str(self.config.root):
                raise ConflictError('Workspace changed; reload work hub settings')
            current = self.read(root)
            if revision != current['revision']:
                raise ConflictError('Work hub settings changed; reload before saving')
            if office_providers is _UNSET and len(current['office_providers']) > 1:
                raise ConflictError('Multiple office platforms are configured; reload the updated settings')
            path = current['path']
            note, settings = self.document(path)
            if (note['etag'] if note else '') != revision:
                raise ConflictError('Work hub settings changed; reload before saving')
            updated = settings.copy()
            updated.update(schema_version=1, office_providers=providers)
            # Move comments attached to the legacy key along with its value.
            if hasattr(updated, 'ca') and 'office_provider' in updated.ca.items:
                updated.ca.items['office_providers'] = updated.ca.items.pop('office_provider')
            updated.pop('office_provider', None)
            if note is None:
                # Validate the entire destination before creating any directory.
                self.notes.files.ensure_mutable()
                parts = PurePosixPath(current['folder']).parts
                for index in range(1, len(parts) + 1):
                    folder = '/'.join(parts[:index])
                    target = self.config.path_for(folder, writable=True)
                    if not target.exists():
                        self.notes.create_folder(folder, workspace_revision)
                    elif not target.is_dir():
                        raise ValueError('Choose a dedicated work hub folder')
                text = ('---\nwork_hub:\n  schema_version: 1\n  office_providers:\n'
                        + ''.join('    - ' + provider + '\n' for provider in providers)
                        + '---\n\n# 工作中枢配置\n')
                self.notes.create(path, workspace_revision, text=text)
            else:
                # Preserve unrelated frontmatter, future options, comments and body.
                self.notes.properties(path, workspace_revision, revision, {'work_hub': updated})
            return {**self.read(root), 'saved': True}
