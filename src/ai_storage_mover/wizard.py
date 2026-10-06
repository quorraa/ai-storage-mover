"""GUI operations with persistent sessions, explicit selections and no auto-cleanup."""
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys

from .engine import Engine, run_lock, utc
from .model import CLEANUP_PHRASE, MigrationError, atomic_json, inside, protected, read_json, make_plan, validate
from .runtime import settings
from .references import map_path


def create_session(projects, storage, items=(), *, tools_temp=None, claude_temp=None,
                   verify_contents=False, projects_destination=None, destinations=None, reserve_bytes=2 * 1024**3):
    storage = Path(storage).absolute()
    project_base = Path(projects_destination or storage / 'Projects').absolute()
    if protected(storage) or protected(project_base):
        raise MigrationError('Choose an ordinary storage folder outside Windows and app packages')
    destinations = destinations or {}
    roots = [(Path(p).resolve(), Path(destinations.get(str(Path(p).resolve()), project_base / Path(p).resolve().name)).absolute(), 'project') for p in projects]
    for item in items:
        source = Path(item['source']).resolve()
        destination = storage / item['slot']
        if source == destination.resolve():
            continue
        if any(inside(source, root[0]) for root in roots):
            # Already included by a selected parent; do not scan/copy it twice.
            continue
        roots.append((source, destination, item['category']))
    if os.name == 'nt':
        local = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
        shared = [local / 'Temp', Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Temp']
        if any(Path(a).resolve() == p.resolve() for a, _, _ in roots for p in shared):
            raise MigrationError('Shared Windows temp stays in place. Select a dedicated AI/build temp folder; future tool writes can still use the new drive.')
    plan = make_plan(roots, storage, verification='hash' if verify_contents else 'metadata',
                     workers=8, reserve_bytes=reserve_bytes)
    plan['transfer'] = 'auto'
    for root in plan['roots']:
        item = next((i for i in items if Path(i['source']).resolve() == Path(root['source'])), None)
        if item and item.get('provider'):
            root['provider'] = item['provider']
    runtime = settings(storage)
    slots = {
        'Cache/uv/cache': ('UV_CACHE_DIR',), 'Cache/pip/cache': ('PIP_CACHE_DIR',),
        'Cache/npm-cache': ('npm_config_cache',), 'Cache/python-bytecode': ('PYTHONPYCACHEPREFIX',),
        'Toolchains/uv/python': ('UV_PYTHON_INSTALL_DIR',), 'Toolchains/uv/tools': ('UV_TOOL_DIR',),
        'Temp/tools': ('TEMP', 'TMP', 'TMPDIR'), 'Temp/claude': ('CLAUDE_CODE_TMPDIR',),
    }
    for item in items:
        mapped = map_path(str(Path(item['source']).resolve()), plan['roots'])
        if mapped != str(Path(item['source']).resolve()):
            for variable in slots.get(item['slot'], ()):
                runtime['environment'][variable] = mapped
    for key, value in (('TEMP', tools_temp), ('TMP', tools_temp), ('TMPDIR', tools_temp),
                       ('CLAUDE_CODE_TMPDIR', claude_temp)):
        if value:
            path = Path(value).absolute()
            if protected(path) or path == Path(path.anchor):
                raise MigrationError('Choose a dedicated temp folder outside Windows and app packages')
            runtime['environment'][key] = str(path)
    for provider, variable in (('codex', 'CODEX_HOME'), ('claude', 'CLAUDE_CONFIG_DIR')):
        entry = next((r for r in plan['roots'] if r.get('provider') == provider or
                      (r['category'] == 'profile' and Path(r['source']).name == '.' + provider)), None)
        if entry:
            runtime['environment'][variable] = entry['destination']
        else:
            item = next((i for i in items if i.get('provider') == provider), None)
            mapped = map_path(str(Path(item['source']).resolve()), plan['roots']) if item else None
            if mapped and mapped != str(Path(item['source']).resolve()):
                runtime['environment'][variable] = mapped
                continue
            current = os.environ.get(variable)
            if current and inside(Path(current).resolve(), storage):
                runtime['environment'][variable] = str(Path(current).resolve())
            else:
                runtime['environment'].pop(variable, None)
    session = dict(schema=1, plan=plan, runtime=runtime, storage=str(storage),
                   projects=str(project_base), created_utc=utc(), status='reviewed')
    return session


def save_session(session):
    run = Path(session['plan']['run_dir'])
    atomic_json(run / 'plan.local.json', session['plan'])
    atomic_json(run / 'runtime.local.json', session['runtime'])
    atomic_json(run / 'wizard.local.json', session)


def load_session(file):
    file = Path(file)
    if file.name == 'plan.local.json':
        file = file.with_name('wizard.local.json')
    value = read_json(file)
    if value.get('schema') != 1:
        raise MigrationError('Unknown saved setup')
    validate(value['plan'])
    if file.resolve().parent != Path(value['plan']['run_dir']).resolve():
        raise MigrationError('Saved setup was moved; choose its original migration folder')
    return value


def setup_command(session, *, preflight=False):
    run = Path(session['plan']['run_dir'])
    frozen = getattr(sys, 'frozen', False)
    worker = Path(sys.executable).with_name('ai-storage-worker.exe') if frozen else Path(sys.executable)
    cmd = ['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
           str(Path(__file__).with_name('Setup-Storage.ps1')), '-PlanPath', str(run / 'plan.local.json'),
           '-StorageRoot', session['storage'], '-ProjectsPath', session['projects'],
           '-PythonPath', str(worker), '-RuntimeInput', str(run / 'runtime.local.json'),
           '-AppsClosed', '-ConfigureOnly']
    if frozen:
        cmd.append('-BundledRuntime')
    if preflight:
        cmd.append('-PreflightOnly')
    return cmd


def windows_setup(session, *, preflight=False):
    run = Path(session['plan']['run_dir'])
    log = run / ('preflight.log' if preflight else 'setup.log')
    env = os.environ.copy()
    if not getattr(sys, 'frozen', False):
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    with log.open('wb') as stream:
        result = subprocess.run(setup_command(session, preflight=preflight), stdout=stream,
                                stderr=subprocess.STDOUT, env=env,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        detail = log.read_text(encoding='utf-8', errors='replace')[-5000:]
        if 'AI apps are still running' in detail:
            raise MigrationError('Close Codex and Claude normally, then choose Retry. No apps were closed by the tool.')
        raise MigrationError(f'Setup stopped. Originals retained. Open the error details: {log}')


def migrate(session, *, cancelled=lambda: False, configure_windows=True):
    save_session(session)
    run = Path(session['plan']['run_dir'])
    if os.name == 'nt' and configure_windows:
        windows_setup(session, preflight=True)
    with run_lock(run), closing(Engine(session['plan'], cancelled=cancelled)) as engine:
        try:
            engine.apply(apps_closed=True)
        except BaseException as exc:
            engine.fail(exc)
            raise
    if cancelled():
        raise MigrationError('Stopped. Originals retained; Retry completes configuration.')
    if os.name == 'nt' and configure_windows:
        windows_setup(session)
    else:
        from .configure import configure
        env = session['runtime']['environment']
        with run_lock(run):
            configure(session['plan'], session['runtime'], codex=env.get('CODEX_HOME'),
                      claude=env.get('CLAUDE_CONFIG_DIR'), projects=session['projects'], apps_closed=True)
    session['status'] = 'complete'
    session['completed_utc'] = utc()
    atomic_json(run / 'wizard.local.json', session)
    atomic_json(run / 'status.json', dict(phase='complete', percent=100, detail='Migration complete. Original copies retained.', updated_utc=utc()))


def backups(session):
    plan = session['plan']
    return [str(Path(r['source']).with_name(Path(r['source']).name + '.ai-mover-backup-' + plan['id']))
            for r in plan['roots']]


def cleanup(session, phrase, *, tested=False, cancelled=lambda: False, configure_windows=True):
    if phrase != CLEANUP_PHRASE or not tested:
        raise MigrationError('Test the new projects and type the complete confirmation phrase')
    if session.get('status') not in ('complete', 'cleaned'):
        raise MigrationError('Finish setup before removing old copies')
    if os.name == 'nt' and configure_windows:
        windows_setup(session, preflight=True)
    run = Path(session['plan']['run_dir'])
    with run_lock(run), closing(Engine(session['plan'], cancelled=cancelled)) as engine:
        try:
            engine.retire(session['plan']['id'], acknowledgment=phrase)
        except BaseException as exc:
            engine.fail(exc)
            raise
    session['status'] = 'cleaned'
    session['cleanup_utc'] = utc()
    atomic_json(run / 'wizard.local.json', session)
