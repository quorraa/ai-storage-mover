"""Configure future tool writes and repair provider metadata without rescanning projects."""
import json
import os
from pathlib import Path
import re
import tomllib
import uuid

from .model import MigrationError, atomic_json, validate, validate_runtime
from .references import repoint_claude, repoint_codex, repoint_files


def set_table(text, header, values):
    pattern = re.compile(r'^\[' + re.escape(header) + r'\][^\r\n]*\r?\n(?P<body>.*?)(?=^\[|\Z)', re.M | re.S)
    match = pattern.search(text)
    if match:
        body = match['body']
        for key, value in values.items():
            line = key + ' = ' + json.dumps(value)
            key_pattern = re.compile(r'^' + re.escape(key) + r'\s*=.*$', re.M)
            body = key_pattern.sub(lambda m: line, body) if key_pattern.search(body) else body.rstrip() + '\n' + line + '\n'
        return text[:match.start('body')] + body + text[match.end('body'):]
    return text.rstrip() + '\n\n[' + header + ']\n' + ''.join(k + ' = ' + json.dumps(v) + '\n' for k, v in values.items())


def codex_environment(text, environment):
    parsed = tomllib.loads(text)
    result = set_table(text, 'shell_environment_policy.set', environment)
    for name, server in parsed.get('mcp_servers', {}).items():
        if 'command' not in server:
            continue
        # Handle quoted server names as well as bare TOML names.
        segment = name if re.fullmatch(r'[A-Za-z0-9_-]+', name) else json.dumps(name)
        table = 'mcp_servers.' + segment
        pattern = re.compile(r'^\[' + re.escape(table) + r'\][^\r\n]*\r?\n(?P<body>.*?)(?=^\[|\Z)', re.M | re.S)
        match = pattern.search(result)
        if match and re.search(r'^env\s*=\s*\{', match['body'], re.M):
            values = dict(server.get('env', {}), **environment)
            line = 'env = { ' + ', '.join(json.dumps(k) + ' = ' + json.dumps(v) for k, v in values.items()) + ' }'
            body = re.sub(r'^env\s*=\s*\{[^\r\n]*\}[ \t]*\r?\n?', lambda m: line + '\n', match['body'], flags=re.M)
            result = result[:match.start('body')] + body + result[match.end('body'):]
        else:
            result = set_table(result, table + '.env', environment)
    tomllib.loads(result)
    return result


def configure(plan, runtime, *, codex=None, claude=None, desktops=(), projects=None, apps_closed=False):
    validate(plan)
    validate_runtime(runtime)
    if not apps_closed:
        raise MigrationError('Close AI apps before configuring saved paths; use --apps-closed')
    if runtime.get('schema') != 1:
        raise MigrationError('Unsupported runtime schema')
    environment = runtime['environment']
    for value in environment.values():
        if not Path(value).is_absolute():
            raise MigrationError('Runtime storage locations must be absolute')
        Path(value).mkdir(parents=True, exist_ok=True)
    child = {k: v for k, v in environment.items() if k not in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR')}
    archive = Path(plan['run_dir']) / 'setup-backups' / uuid.uuid4().hex
    archive.mkdir(parents=True)
    receipt = {'backup': str(archive), 'changed_configs': []}

    def write(path, raw):
        path = Path(path)
        old = path.read_bytes() if path.exists() else None
        if old == raw:
            return
        saved = archive / (uuid.uuid4().hex + path.suffix)
        if old is not None:
            saved.write_bytes(old)
        if (path.read_bytes() if path.exists() else None) != old:
            raise MigrationError('Configuration changed during setup; originals retained')
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        temp.write_bytes(raw)
        os.replace(temp, path)
        receipt['changed_configs'].append({'path': str(path), 'backup': str(saved) if old is not None else None})

    if codex:
        base = Path(codex)
        config = base / 'config.toml'
        if config.exists():
            repoint_files(plan, [config])
        text = config.read_text(encoding='utf-8') if config.exists() else ''
        write(config, codex_environment(text, child).encode('utf-8'))
        if (base / 'state_5.sqlite').is_file():
            receipt['codex_paths'] = repoint_codex(plan, base)
    if claude:
        base = Path(claude)
        # Preserve legacy global preferences when CLAUDE_CONFIG_DIR is introduced.
        global_settings = base / '.claude.json'
        legacy = next((Path(r['destination']) for r in plan['roots'] if Path(r['source']).name == '.claude.json'), None)
        if not legacy:
            legacy = Path.home() / '.claude.json'
        if legacy and legacy.is_file() and not global_settings.exists():
            write(global_settings, legacy.read_bytes())
        config = base / 'settings.json'
        value = json.loads(config.read_text(encoding='utf-8-sig')) if config.exists() else {}
        value.setdefault('env', {}).update(child)
        write(config, json.dumps(value, indent=2).encode('utf-8'))
    for desktop in desktops:
        config = Path(desktop) / 'claude_desktop_config.json'
        if config.exists():
            value = json.loads(config.read_text(encoding='utf-8-sig'))
            for server in value.get('mcpServers', {}).values():
                if 'command' in server:
                    server.setdefault('env', {}).update(child)
            write(config, json.dumps(value, indent=2).encode('utf-8'))
        receipt.setdefault('claude_paths', []).extend(repoint_claude(plan, claude, desktop))
    if claude and not desktops:
        receipt['claude_paths'] = repoint_claude(plan, claude)
    # Provider instruction files establish where future project scaffolds belong.
    projects = str(Path(projects or (Path(runtime['storage_root']) / 'Projects')).absolute())
    Path(projects).mkdir(parents=True, exist_ok=True)
    marker = '<!-- ai-storage-mover defaults -->'
    instructions = marker + '\nCreate new projects under ' + projects + '. Use the configured AI temp and cache directories for builds and scratch files.\n'
    for profile, name in ((codex, 'AGENTS.md'), (claude, 'CLAUDE.md')):
        if not profile:
            continue
        path = Path(profile) / name
        text = path.read_text(encoding='utf-8') if path.exists() else ''
        text = re.sub(re.escape(marker) + r'.*?(?=\n\n|\Z)', '', text, flags=re.S).rstrip()
        write(path, (text + '\n\n' + instructions).lstrip().encode('utf-8'))
    receipt['new_projects'] = projects
    receipt['tool_temp'] = environment.get('TEMP')
    atomic_json(archive / 'receipt.json', receipt)
    return receipt
