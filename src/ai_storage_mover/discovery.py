"""Bounded, read-only suggestions. Never crawl every file on a drive."""
import json
import os
from pathlib import Path
import sqlite3
import time

from .model import inside, linked, protected, assert_movable, MigrationError


def candidates(home=None, environment=None):
    home = Path(home or Path.home())
    env = {k.upper(): v for k, v in (os.environ if environment is None else environment).items()}
    local = Path(env.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
    roaming = Path(env.get('APPDATA', home / 'AppData' / 'Roaming'))
    values = []
    seen = set()

    def add(label, path, category, slot, provider=None):
        path = Path(path).absolute()
        try:
            assert_movable(path)
        except MigrationError:
            return
        if not path.is_dir() or protected(path):
            return
        path = path.resolve()
        key = os.path.normcase(str(path))
        if key in seen or protected(path):
            return
        seen.add(key)
        values.append(dict(label=label, source=str(path), category=category,
                           slot=slot, provider=provider))

    for provider, variable in (('codex', 'CODEX_HOME'), ('claude', 'CLAUDE_CONFIG_DIR')):
        if env.get(variable):
            add(provider.title() + ' profile', env[variable], 'profile', 'Profiles/' + provider, provider)
        add(provider.title() + ' profile', home / ('.' + provider), 'profile', 'Profiles/' + provider, provider)
    add('Shared agent settings', home / '.agents', 'profile', 'Profiles/shared-agents')
    for label, variable, fallback, slot in (
        ('uv cache', 'UV_CACHE_DIR', local / 'uv' / 'cache', 'Cache/uv/cache'),
        ('pip cache', 'PIP_CACHE_DIR', local / 'pip' / 'Cache', 'Cache/pip/cache'),
        ('npm cache', 'npm_config_cache', local / 'npm-cache', 'Cache/npm-cache'),
        ('Python bytecode', 'PYTHONPYCACHEPREFIX', None, 'Cache/python-bytecode'),
        ('Claude temp', 'CLAUDE_CODE_TMPDIR', None, 'Temp/claude'),
    ):
        path = env.get(variable.upper()) or fallback
        if path:
            add(label, path, 'temp' if 'temp' in label else 'cache', slot)
    uv_data = roaming / 'uv' / 'data' if os.name == 'nt' else home / '.local' / 'share' / 'uv'
    for label, variable, fallback, slot in (
        ('uv Python versions', 'UV_PYTHON_INSTALL_DIR', uv_data / 'python', 'Toolchains/uv/python'),
        ('uv installed tools', 'UV_TOOL_DIR', uv_data / 'tools', 'Toolchains/uv/tools'),
    ):
        add(label, env.get(variable) or fallback, 'toolchain', slot)
    if os.name == 'nt':
        # Retain older uv layouts as separate suggestions for an explicit choice.
        add('uv Python versions (older layout)', roaming / 'uv' / 'python', 'toolchain', 'Toolchains/uv/python')
        add('uv installed tools (older layout)', roaming / 'uv' / 'tools', 'toolchain', 'Toolchains/uv/tools')
        # Desktop browser profiles/cache aliases are never migration candidates.
        add('npm global packages', env.get('NPM_CONFIG_PREFIX') or roaming / 'npm', 'toolchain', 'Toolchains/npm-global')
    # Shared Windows temp is a future-write suggestion, NEVER a migration root.
    shared = [local / 'Temp', Path(env.get('WINDIR', 'C:/Windows')) / 'Temp']
    for key in ('TEMP', 'TMP', 'TMPDIR'):
        value = env.get(key)
        if value and not any(Path(value).resolve() == p.resolve() for p in shared):
            add('Tool temp (' + key + ')', value, 'temp', 'Temp/tools')
    return values


def project_suggestions(home=None, environment=None):
    """Use saved app project records; no chat messages or file contents searched."""
    home = Path(home or Path.home())
    env = dict(os.environ if environment is None else environment)
    found = []
    codex = Path(env.get('CODEX_HOME', home / '.codex'))
    state = codex / 'state_5.sqlite'
    if state.is_file():
        try:
            with sqlite3.connect(state.as_uri() + '?mode=ro', uri=True, timeout=0.2) as db:
                for query in ('SELECT DISTINCT path FROM project_roots LIMIT 500',
                              'SELECT DISTINCT cwd FROM threads LIMIT 500'):
                    try:
                        found.extend(row[0] for row in db.execute(query) if row[0])
                    except sqlite3.Error:
                        pass
        except sqlite3.Error:
            pass
    claude = Path(env.get('CLAUDE_CONFIG_DIR', home / '.claude'))
    for file in (home / '.claude.json', claude / '.claude.json'):
        try:
            if file.stat().st_size <= 8 * 1024**2:
                data = json.loads(file.read_text(encoding='utf-8-sig'))
                if isinstance(data, dict) and isinstance(data.get('projects'), dict):
                    found.extend(data['projects'].keys())
        except (OSError, ValueError, TypeError):
            pass
    seen, result = set(), []
    for value in found:
        path = Path(value)
        if not path.is_absolute() or not path.is_dir() or protected(path):
            continue
        path = path.resolve()
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            result.append(str(path))
    return result


def scan_folder(folder, *, max_depth=3, max_entries=5000, seconds=3, cancelled=lambda: False):
    """Optional custom-folder helper: bounded directory scan, no reparse traversal."""
    folder = Path(folder).absolute()
    if protected(folder) or linked(folder):
        return {'projects': [], 'temps': [], 'limited': False}
    stack, projects, temps = [(folder, 0)], [], []
    deadline, inspected, limited = time.monotonic() + seconds, 0, False
    markers = {'.git', 'pyproject.toml', 'package.json', 'Cargo.toml', 'go.mod', '.claude', '.codex'}
    excluded = {'node_modules', '.venv', 'venv', '.git', '__pycache__', 'site-packages'}
    while stack:
        if cancelled() or time.monotonic() >= deadline or inspected >= max_entries:
            limited = True
            break
        path, depth = stack.pop()
        if protected(path) or linked(path):
            continue
        names, directories = set(), []
        try:
            with os.scandir(path) as children:
                for item in children:
                    inspected += 1
                    if inspected > max_entries or time.monotonic() >= deadline or cancelled():
                        limited = True
                        break
                    names.add(item.name)
                    if item.is_dir(follow_symlinks=False) and not linked(item.path):
                        directories.append(Path(item.path))
        except OSError:
            continue
        if names & markers:
            projects.append(str(path))
            # A project is one selectable root, not its dependency subfolders.
            continue
        for child in directories:
            if child.name.casefold() in ('temp', 'tmp', '.tmp', '.temp', 'build-temp'):
                temps.append(str(child))
            elif depth < max_depth and child.name.casefold() not in excluded:
                stack.append((child, depth + 1))
    return {'projects': projects, 'temps': temps, 'limited': limited}
