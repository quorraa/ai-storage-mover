"""Narrow, non-deleting repair for the legacy Codex Roaming junction.

The UI launches this through Task Scheduler: no packaged-process filesystem view,
no inherited Codex job lifetime, no forced app termination or Windows restart.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import uuid

from .model import MigrationError, atomic_json, inside, linked, physical_parents, read_json

CACHE = Path('web/Codex/Default/Cache/Cache_Data')
TERMINAL = {'complete', 'not-needed', 'blocked', 'failed', 'cancelled'}
MAX_BYTES = 4 * 1024**3
MAX_ENTRIES = 100_000


def unpackaged():
    if os.name != 'nt':
        return False
    size = ctypes.c_uint32()
    return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(size), None) == 15700


def physical(path):
    path = Path(path).absolute()
    physical_parents(path)
    if linked(path):
        raise MigrationError(f'Unexpected redirected folder: {path}')
    return path


def current_layout():
    """Called only by the independently launched worker, never from the UI process."""
    if not unpackaged():
        raise MigrationError('Repair requires an unpackaged Windows worker. No profile changes were made.')
    local = physical(Path(os.environ['LOCALAPPDATA']))
    roaming = physical(Path(os.environ['APPDATA']))
    packages = physical(local / 'Packages')
    matches = list(packages.glob('OpenAI.Codex_*'))
    if len(matches) != 1:
        raise MigrationError('Expected one current-user Codex package. No profile changes were made.')
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
        try:
            override = winreg.QueryValueEx(key, 'CODEX_ELECTRON_USER_DATA_PATH')[0]
        except FileNotFoundError:
            override = None
    if override or os.environ.get('CODEX_ELECTRON_USER_DATA_PATH'):
        raise MigrationError('A custom Codex desktop profile override is set. This repair cannot safely choose between profiles; no data was changed.')
    return roaming / 'Codex', physical(matches[0] / 'LocalCache' / 'Roaming' / 'Codex')


def inspect_layout(public, private):
    public, private = Path(public).absolute(), physical(private)
    physical_parents(public)
    if not os.path.lexists(public) or not linked(public):
        return dict(affected=False, public=str(public), detail='No redirected Codex Roaming profile found. No repair is needed for this issue.')
    info = public.lstat()
    if os.name == 'nt' and getattr(info, 'st_reparse_tag', 0) != 0xA0000003:
        raise MigrationError('The Codex profile uses an unsupported link type. No changes were made.')
    source = physical(public.resolve(strict=True))
    if not source.is_dir() or source == Path(source.anchor):
        raise MigrationError('The profile target is not an ordinary data folder.')
    for other in (public.parent, private):
        if inside(source, other) or inside(other, source):
            raise MigrationError('Profile locations overlap; refusing an ambiguous repair.')
    if not (source / CACHE).is_dir() or not (private / CACHE).is_dir():
        raise MigrationError('The known Codex browser-cache layout was not found in both profiles. No changes were made.')
    return dict(affected=True, public=str(public), source=str(source), private=str(private),
                identity=[info.st_dev, info.st_ino],
                detail='A redirected Codex Roaming profile was found. Restore a physical folder and preserve the old browser caches.')


def app_closed():
    # Fail closed if process inspection fails. ChatGPT.exe also covers older builds.
    script = "@(Get-CimInstance Win32_Process -ErrorAction Stop -Filter \"Name='ChatGPT.exe' OR Name='Codex.exe'\").Count"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or not result.stdout.strip().isdigit():
        raise MigrationError('Could not verify that Codex is closed. No further changes were made.')
    return int(result.stdout.strip()) == 0


def manifest(root, checkpoint=lambda: None):
    """Bounded traversal; reject links before descent, retain directory entries too."""
    root = physical(root)
    found, stack, total = {}, [root], 0
    while stack:
        directory = stack.pop()
        physical(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                checkpoint()
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise MigrationError(f'Nested links are not supported in this repair: {path}')
                key = path.relative_to(root).as_posix()
                if stat.S_ISDIR(info.st_mode):
                    found[key] = ['directory']
                    stack.append(path)
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    if total > MAX_BYTES:
                        raise MigrationError('Profile exceeds the 4 GiB repair limit. No original data was removed.')
                    with path.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    found[key] = ['file', info.st_size, digest]
                else:
                    raise MigrationError(f'Unsupported profile entry: {path}')
                if len(found) > MAX_ENTRIES:
                    raise MigrationError('Profile exceeds the 100,000-entry repair limit.')
    return found, total


def apply_repair(expected, record, *, closed=app_closed, cancelled=lambda: False, notify=lambda **kw: None):
    """Internal fixture-testable transaction; production paths come from current_layout."""
    public, private = Path(expected['public']), Path(expected['private'])
    record = physical(record)
    source = Path(expected['source'])
    if inspect_layout(public, private) != expected:
        raise MigrationError('The profile changed since inspection. Check it again before repairing.')
    if any(inside(record, path) or inside(path, record) for path in (public, private, source)):
        raise MigrationError('Repair records must be outside profile folders.')

    def checkpoint():
        if cancelled():
            raise MigrationError('Repair cancelled. Original data retained.')
    def assert_closed():
        checkpoint()
        if not closed():
            raise MigrationError('Codex reopened during repair. Close it and inspect the retained repair record.')

    assert_closed()
    token = uuid.uuid4().hex
    stage = public.with_name(public.name + '.ai-mover-repair-stage-' + token)
    backup = public.with_name(public.name + '.junction-before-ai-mover-repair-' + token)
    for path in (stage, backup):
        if path.parent != public.parent or os.path.lexists(path):
            raise MigrationError('Repair staging/backup path is not available.')
    before, total = manifest(source, checkpoint)
    if shutil.disk_usage(public.parent).free < total + 256 * 1024**2:
        raise MigrationError('Not enough free space for the verified local profile copy plus 256 MiB reserve.')
    atomic_json(record / 'source-manifest.json', before)
    receipt = dict(public=str(public), source=str(source), staging=str(stage), junction_backup=str(backup),
                   caches=[], operations=[], bytes=total, files=sum(v[0] == 'file' for v in before.values()))
    def journal(operation):
        receipt['operations'].append(operation)
        atomic_json(record / 'repair-receipt.json', receipt)
    journal('Preservation copy starting; original profile and target remain untouched')
    stage.mkdir()
    notify(phase='copying', detail='Preserving the browser profile.', files=receipt['files'])
    copied = 0
    for relative, value in before.items():
        checkpoint()
        destination = stage / relative
        physical_parents(destination)
        if value[0] == 'directory':
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            physical(source / relative)
            shutil.copy2(source / relative, destination)
            copied += 1
            if copied % 128 == 0:
                notify(phase='copying', detail=f'Preserving the browser profile: {copied:,} / {receipt["files"]:,} files.')
    notify(phase='verifying', detail='Checking every copied file with SHA-256.')
    if manifest(stage, checkpoint)[0] != before or manifest(source, checkpoint)[0] != before:
        raise MigrationError('Copy verification failed or the original changed. Originals and staging retained.')
    assert_closed()
    if inspect_layout(public, private) != expected:
        raise MigrationError('The profile path changed during copying. Originals and staging retained.')
    # Validate every rename before changing any active path.
    pairs = []
    for profile in (stage, private):
        cache = profile / CACHE
        if os.path.lexists(cache):
            physical(cache)
            if not cache.is_dir():
                raise MigrationError('Browser cache is not a directory.')
            saved = cache.with_name(cache.name + '.before-ai-mover-repair-' + token)
            if os.path.lexists(saved):
                raise MigrationError('Cache backup already exists.')
            pairs.append((cache, saved))
    receipt['caches'] = [dict(original=str(a), backup=str(b)) for a, b in pairs]
    moved, link_moved, installed = [], False, False
    try:
        notify(phase='repairing', detail='Restoring the local profile and preserving old caches.')
        for original, saved in pairs:
            assert_closed()
            journal('Rename cache: ' + str(original) + ' -> ' + str(saved))
            original.rename(saved)
            moved.append((original, saved))
        assert_closed()
        journal('Preserve junction: ' + str(public) + ' -> ' + str(backup))
        public.rename(backup)
        link_moved = True
        journal('Install verified physical profile: ' + str(stage) + ' -> ' + str(public))
        stage.rename(public)
        installed = True
        physical(public)
        receipt['applied'] = True
        receipt['memory_leak_verified'] = False
        # Stage cache backups moved with their parent; report their final location.
        for item in receipt['caches']:
            for key in ('original', 'backup'):
                path = Path(item[key])
                if inside(path, stage):
                    item[key] = str(public / path.relative_to(stage))
        journal('Repair applied. Reopen Codex to recreate caches; memory growth has not been measured by this tool.')
        return receipt
    except BaseException:
        # Never overwrite a path recreated by an app, and never delete a profile.
        if not installed and closed():
            if link_moved and not os.path.lexists(public):
                backup.rename(public)
            for original, saved in reversed(moved):
                if not os.path.lexists(original):
                    saved.rename(original)
            journal('Interrupted before installation: previous paths restored; staging retained')
        raise


def run_job(record):
    record = physical(Path(record).absolute())
    request = read_json(record / 'request.json')
    started = time.monotonic()
    def status(**values):
        atomic_json(record / 'status.json', dict(updated=time.time(), pid=os.getpid(), unpackaged=unpackaged(), **values))
    try:
        if not unpackaged():
            raise MigrationError('The repair worker inherited a packaged context. Nothing was changed.')
        # Read-only lifetime check used by the Windows release test.
        if request['mode'] == 'probe':
            for n in range(12):
                status(phase='probe', detail='Independent worker lifetime check', tick=n)
                time.sleep(1)
            status(phase='complete', detail='Independent worker check finished')
            return 0
        public, private = current_layout()
        inspection = inspect_layout(public, private)
        if request['mode'] == 'inspect':
            atomic_json(record / 'inspection.json', inspection)
            status(phase='complete', detail=inspection['detail'], inspection=inspection)
            return 0
        if request['mode'] != 'apply' or not request.get('confirmed'):
            raise MigrationError('Review and confirm the repair first.')
        if not inspection['affected']:
            status(phase='not-needed', detail=inspection['detail'])
            return 0
        if inspection != request.get('inspection'):
            raise MigrationError('Profile paths changed. Run Check again before repairing.')
        while not app_closed():
            if (record / 'STOP').exists():
                status(phase='cancelled', detail='Cancelled before repair. No profiles changed.')
                return 0
            if time.monotonic() - started > 600:
                raise MigrationError('Codex did not close within ten minutes. No profiles changed.')
            status(phase='waiting', detail='Close Codex normally. The repair will continue here.')
            time.sleep(2)
        from .engine import run_lock
        # A second app instance must not race this transaction with another repair.
        lock = physical(public.parent / '.ai-storage-mover-repair')
        with run_lock(lock):
            receipt = apply_repair(inspection, record, cancelled=lambda: (record / 'STOP').exists(), notify=status)
        status(phase='complete', detail='Repair applied. Reopen Codex. Restart Windows if memory remains high; this tool does not restart it.', receipt=receipt)
        return 0
    except Exception as exc:
        status(phase='failed', detail=str(exc))
        return 1
    finally:
        task = request.get('task', '')
        if task == 'AIStorageMover-Repair-' + record.name and len(record.name) == 32:
            # Exact one-shot task only; records and backups remain.
            result = subprocess.run(['schtasks.exe', '/Delete', '/TN', task, '/F'], capture_output=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                (record / 'task-cleanup-warning.txt').write_text('Remove the inactive task ' + task + ' in Task Scheduler.', encoding='utf-8')


def start_job(base, mode, inspection=None):
    if os.name != 'nt' or mode not in ('inspect', 'apply', 'probe'):
        raise MigrationError('Codex profile repair is a Windows feature.')
    base = physical(Path(base).absolute())
    base.mkdir(parents=True, exist_ok=True)
    record = base / uuid.uuid4().hex
    record.mkdir()
    task = 'AIStorageMover-Repair-' + record.name
    atomic_json(record / 'request.json', dict(mode=mode, inspection=inspection, confirmed=mode == 'apply', task=task))
    atomic_json(record / 'status.json', dict(phase='starting', detail='Starting an independent Windows repair worker.', updated=time.time()))
    script = Path(__file__).with_name('Start-CodexRepair.ps1')
    frozen = getattr(sys, 'frozen', False)
    worker = (Path(sys.executable).with_name('ai-storage-worker.exe') if frozen else Path(sys.executable)).resolve()
    command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(script),
               '-Record', str(record), '-Worker', str(worker), '-TaskName', task]
    if not frozen:
        command += ['-SourceRoot', str(Path(__file__).resolve().parents[1])]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        atomic_json(record / 'status.json', dict(phase='failed', detail='Windows could not start the independent task. No profile changes were made.', updated=time.time()))
        (record / 'launch-error.txt').write_text(result.stderr or result.stdout, encoding='utf-8')
        raise MigrationError('Windows could not start the repair task. Details: ' + str(record))
    return record
