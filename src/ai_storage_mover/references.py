"""Explicit config references only; history and repository-wide text are opt-in."""
import json
from contextlib import closing
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

from .model import MigrationError, atomic_json


def map_path(value, roots):
    if not isinstance(value, str):
        return value
    prefix = '\\\\?\\' if value.startswith('\\\\?\\') else ''
    plain = value[len(prefix):]
    normalized = plain.replace('/', '\\') if ':' in plain[:3] else plain
    for root in sorted(roots, key=lambda e: len(e['source']), reverse=True):
        source = root['source'].replace('/', '\\') if ':' in root['source'][:3] else root['source']
        comparison = normalized.casefold() if ':' in normalized[:3] else normalized
        expected = source.casefold() if ':' in source[:3] else source
        separator = '\\' if ':' in source[:3] else os.sep
        if comparison == expected or comparison.startswith(expected + separator):
            return prefix + root['destination'] + normalized[len(source):]
    return value


def nested(value, roots):
    if isinstance(value, dict):
        return {map_path(k, roots): nested(v, roots) for k, v in value.items()}
    if isinstance(value, list):
        return [nested(v, roots) for v in value]
    return map_path(value, roots)


def named_path_fields(value, roots, names):
    """Change known directory/file fields without rewriting prompts or titles."""
    if isinstance(value, dict):
        return {key: map_path(child, roots) if key in names and isinstance(child, str)
                else named_path_fields(child, roots, names) for key, child in value.items()}
    if isinstance(value, list):
        return [named_path_fields(child, roots, names) for child in value]
    return value


def codex_ui_paths(value, roots):
    for key in ('local-projects', 'thread-workspace-root-hints', 'thread-projectless-output-directories',
                'electron-saved-workspace-roots', 'active-workspace-roots', 'electron-workspace-root-labels', 'selected-project'):
        if key in value:
            value[key] = nested(value[key], roots)
    atoms = value.get('electron-persisted-atom-state', {})
    for key, atom in list(atoms.items()):
        if key.startswith('external-agent-import-discovery:'):
            atoms[key] = named_path_fields(atom, roots, {'cwd', 'path'})
        elif key.startswith('thread-tab-routes-v1:') and isinstance(atom, dict):
            for route in atom.get('routes', []):
                params = route.get('params', {})
                if isinstance(params.get('path'), str):
                    params['path'] = map_path(params['path'], roots)
        elif key == 'heartbeat-thread-permissions-by-id' and isinstance(atom, dict):
            for permissions in atom.values():
                if isinstance(permissions, dict):
                    policy = permissions.get('sandboxPolicy', {})
                    if 'writableRoots' in policy:
                        policy['writableRoots'] = nested(policy['writableRoots'], roots)
    return value


def repoint_files(plan, files):
    archive = Path(plan['run_dir']) / 'reference-backups' / uuid.uuid4().hex
    archive.mkdir(parents=True)
    changes = []
    for supplied in files:
        path = Path(supplied).absolute()
        if not path.is_file() or path.is_symlink():
            raise MigrationError(f'Expected an explicit regular config file: {path}')
        raw = path.read_bytes()
        if len(raw) > 8 * 1024**2:
            raise MigrationError('Config exceeds 8 MiB; select a smaller structured file')
        encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'
        text = raw.decode(encoding)
        if path.suffix.lower() == '.json':
            result = json.dumps(nested(json.loads(text), plan['roots']), indent=2, ensure_ascii=False)
        else:
            result = text
            for root in sorted(plan['roots'], key=lambda e: len(e['source']), reverse=True):
                for factor in (4, 2, 1):
                    source = root['source'].replace('\\', '\\' * factor)
                    destination = root['destination'].replace('\\', '\\' * factor)
                    pattern = re.escape(source) + r'''(?=$|[\\/\s"';,)\]}])'''
                    result = re.sub(pattern, lambda m: destination, result, flags=re.I if ':' in source[:3] else 0)
            if path.suffix.lower() == '.toml':
                import tomllib
                tomllib.loads(result)
        if result == text:
            continue
        saved = archive / (uuid.uuid4().hex + path.suffix)
        saved.write_bytes(raw)
        if path.read_bytes() != raw:
            raise MigrationError('Configuration changed concurrently; backup retained, retry')
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        temporary.write_bytes(result.encode(encoding))
        os.replace(temporary, path)
        changes.append(dict(path=str(path), backup=str(saved)))
    atomic_json(archive / 'receipt.json', changes)
    return changes


def repoint_codex(plan, profile):
    profile = Path(profile).absolute()
    db_path = profile / 'state_5.sqlite'
    archive = Path(plan['run_dir']) / 'reference-backups' / uuid.uuid4().hex
    archive.mkdir(parents=True)
    counts = {}
    # Never create an empty replacement DB when an installed schema is absent.
    if not db_path.is_file():
        raise MigrationError('Codex state DB is absent; installed version needs a different adapter')
    with closing(sqlite3.connect(db_path, timeout=30)) as db:
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise MigrationError('Codex state integrity failed')
        for table, columns in [('threads', {'id', 'cwd'}), ('project_roots', {'project_id', 'position', 'path'})]:
            actual = {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}
            if not columns <= actual:
                raise MigrationError('Unknown Codex path schema; no records changed')
        with closing(sqlite3.connect(archive / 'state.before.sqlite')) as backup:
            db.backup(backup)
        db.execute('BEGIN IMMEDIATE')
        for table, keys, column in [('threads', ('id',), 'cwd'), ('project_roots', ('project_id', 'position'), 'path')]:
            counts[table] = 0
            for row in db.execute('SELECT ' + ','.join((*keys, column)) + ' FROM ' + table).fetchall():
                value = map_path(row[-1], plan['roots'])
                if value != row[-1]:
                    cursor = db.execute('UPDATE ' + table + ' SET ' + column + '=? WHERE ' + ' AND '.join(k + '=?' for k in keys) + ' AND ' + column + '=?', (value, *row[:-1], row[-1]))
                    counts[table] += cursor.rowcount
        db.commit()
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise MigrationError('Codex state integrity failed after path update')
    ui = profile / '.codex-global-state.json'
    if ui.exists():
        raw = ui.read_bytes()
        value = json.loads(raw)
        value = codex_ui_paths(value, plan['roots'])
        if value != json.loads(raw):
            (archive / 'ui.before.json').write_bytes(raw)
            if ui.read_bytes() != raw:
                raise MigrationError('Codex UI settings changed concurrently; close the app and retry')
            atomic_json(ui, value)
    atomic_json(archive / 'receipt.json', counts)
    return counts


def repoint_claude(plan, profile=None, desktop=None):
    """Explicit Claude Code preferences and desktop session directory records.

    Package folders stay in place. Only selected JSON path fields are edited.
    Session messages, prompt snapshots and historical transcripts are untouched.
    """
    selected = []
    if profile:
        base = Path(profile).absolute()
        for name in ('.claude.json', 'legacy-user-root/.claude.json'):
            selected.append((base / name, ('projects', 'mcpServers', 'githubRepoPaths')))
        selected.append((base / 'settings.json', ('env',)))
        for index in (base / 'projects').glob('*/sessions-index.json'):
            selected.append((index, None))
    if desktop:
        base = Path(desktop).absolute()
        selected += [(base / 'claude_desktop_config.json', ('mcpServers', 'coworkUserFilesPath', 'preferences')),
                     (base / 'git-worktrees.json', ('worktrees', 'untrackedDirGc', 'originUrls', 'originPins')),
                     (base / 'git-shadow' / 'cli-temp-roots.json', '*')]
        for folder in ('claude-code-sessions', 'local-agent-mode-sessions'):
            for path in (base / folder).glob('*/*/*.json'):
                if path.name.startswith('local_'):
                    selected.append((path, ('cwd', 'originCwd', 'worktreePath', 'planPath', 'gitAnchors', 'sessionPermissionUpdates', 'writtenBranches')))
                elif path.name in ('scheduled-tasks.json', 'spaces.json'):
                    selected.append((path, None))
                elif path.name == 'remote-session-spaces.json':
                    selected.append((path, '*'))
    archive = Path(plan['run_dir']) / 'reference-backups' / uuid.uuid4().hex
    archive.mkdir(parents=True)
    changes = []
    seen = set()
    for path, sections in selected:
        if not path.exists():
            continue
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            if not profile or not resolved.is_relative_to(Path(profile).resolve()):
                raise MigrationError(f'Claude metadata pointer escaped the selected profile: {path}')
            path = resolved
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            raise MigrationError(f'Expected a regular Claude metadata file: {path}')
        raw = path.read_bytes()
        if len(raw) > 8 * 1024**2:
            raise MigrationError(f'Claude metadata exceeds 8 MiB: {path}')
        value = json.loads(raw)
        if not isinstance(value, dict) and not (sections in (None, '*') and isinstance(value, list)):
            raise MigrationError(f'Unknown Claude metadata schema: {path}')
        if sections == '*':
            value = nested(value, plan['roots'])
        elif sections is None:
            value = named_path_fields(value, plan['roots'], {'cwd', 'originCwd', 'worktreePath', 'projectPath', 'fullPath', 'originalPath', 'path'})
        else:
            for key in sections:
                if key in value:
                    value[key] = nested(value[key], plan['roots'])
        if value == json.loads(raw):
            continue
        backup = archive / (uuid.uuid4().hex + '.json')
        backup.write_bytes(raw)
        if path.read_bytes() != raw:
            raise MigrationError('Claude metadata changed concurrently; close the app and retry')
        atomic_json(path, value)
        changes.append({'path': str(path), 'backup': str(backup)})
    atomic_json(archive / 'receipt.json', changes)
    return changes
