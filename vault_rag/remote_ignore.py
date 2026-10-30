"""Bounded, hierarchical attachment discovery rules, independent of note scopes."""
from pathlib import PurePosixPath

import pathspec


IGNORE_NAME='leafloom.ignore'
IGNORE_HEADER='# leafloom-ignore v1'
MAX_IGNORE_BYTES=64*1024
MAX_TOTAL_IGNORE_BYTES=1024*1024
MAX_IGNORE_LINES=2048
from vault_rag.attachment_policy import DEFAULT_EXTENSIONS, allows



class IgnoreRuleError(ValueError):
    pass


class RemoteIgnore:
    """Local directory rules override ancestors; directories are always visited.

    Gitignore pattern syntax is used, but traversal deliberately does not prune
    excluded directories, so a child's own rules can re-include its files.
    """
    def __init__(self,reserved=(), *, allowed_extensions=None):
        self.allowed_extensions=tuple(DEFAULT_EXTENSIONS if allowed_extensions is None else allowed_extensions)
        self.specs={};self.total_bytes=0;self.reserved=tuple(reserved)

    def add(self,directory,data):
        if len(data)>MAX_IGNORE_BYTES or self.total_bytes+len(data)>MAX_TOTAL_IGNORE_BYTES:
            raise IgnoreRuleError('ignore_rules_too_large')
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:raise IgnoreRuleError('ignore_rules_invalid_encoding') from None
        if '\x00' in text or text.lstrip().lower().startswith(('<!doctype html','<html')):
            raise IgnoreRuleError('ignore_rules_invalid_text')
        lines=text.splitlines()
        if not lines or lines[0]!=IGNORE_HEADER:raise IgnoreRuleError('ignore_rules_invalid_header')
        if len(lines)>MAX_IGNORE_LINES or any(len(line)>2048 for line in lines):
            raise IgnoreRuleError('ignore_rules_too_large')
        try:spec=pathspec.GitIgnoreSpec.from_lines(lines)
        except (ValueError,TypeError):raise IgnoreRuleError('ignore_rules_invalid_pattern') from None
        self.specs[directory]=spec;self.total_bytes+=len(data)

    @staticmethod
    def _decision(spec,path):
        if spec.match_file(path):return True
        # Keep compatibility with pathspec>=0.12.1: distinguish a negative
        # match from no match without relying on newer check_file APIs.
        if any(pattern.include is False and pattern.match_file(path) is not None for pattern in spec.patterns):return False
        return None

    def excluded(self,path):
        if any(path==prefix or path.startswith(prefix+'/') for prefix in self.reserved):return True
        name=PurePosixPath(path).name
        if name==IGNORE_NAME or not allows(path,self.allowed_extensions):return True
        excluded=False
        parts=path.split('/')
        for depth in range(len(parts)):
            directory='/'.join(parts[:depth]);spec=self.specs.get(directory)
            if spec is None:continue
            decision=self._decision(spec,'/'.join(parts[depth:]))
            if decision is not None:excluded=decision
        return excluded
