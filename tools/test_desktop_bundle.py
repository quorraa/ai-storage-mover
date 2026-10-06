"""Exercise the shipped binaries on disposable roots, without changing app/user settings."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

base = Path(__file__).resolve().parents[1]
runs = base / '.runs'
runs.mkdir(exist_ok=True)
fixture = Path(tempfile.mkdtemp(prefix='desktop-bundle-', dir=runs))
bundle = base / 'dist' / 'AI Storage Mover'
worker, gui = bundle / 'ai-storage-worker.exe', bundle / 'AI Storage Mover.exe'
assert worker.is_file() and gui.is_file()
source, target = fixture / 'Sample Agent', fixture / 'storage' / 'Projects' / 'Sample Agent'
source.mkdir()
(source / 'hello.txt').write_text('retain this original')
flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def run(*args, success=True, environment=None):
    result = subprocess.run([str(worker), *map(str, args)], capture_output=True, text=True,
                            timeout=60, creationflags=flags, env=environment)
    if success and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    if not success and not result.returncode:
        raise AssertionError('Operation should have been refused')
    return result


try:
    proof = fixture / 'gui.json'
    process = subprocess.Popen([str(gui), '--self-test', str(proof)], creationflags=flags)
    try:
        assert process.wait(timeout=30) == 0
    finally:
        if process.poll() is None:
            process.terminate()  # Only this disposable, owned GUI test process.
            process.wait(timeout=10)
    assert json.loads(proof.read_text())['desktop'] == 'passed'
    plan_file, runtime_file = fixture / 'plan.local.json', fixture / 'runtime.local.json'
    run('plan', '--storage-root', fixture / 'storage', '--project', source, '--verification', 'metadata',
        '--reserve-gib', '0', '--output', plan_file)
    plan = json.loads(plan_file.read_text())
    run('apply', '--plan', plan_file, '--apps-closed')
    backup = source.with_name(source.name + '.ai-mover-backup-' + plan['id'])
    assert (backup / 'hello.txt').read_text() == 'retain this original'
    assert (target / 'hello.txt').read_text() == 'retain this original'
    run('runtime', '--storage-root', fixture / 'storage', '--output', runtime_file)
    runtime = json.loads(runtime_file.read_text())
    assert runtime['environment']['UV_TOOL_DIR'].startswith(str(fixture))
    environment = dict(os.environ, **runtime['environment'])
    for path in runtime['environment'].values():
        Path(path).mkdir(parents=True, exist_ok=True)
    run('verify-runtime', '--runtime', runtime_file, '--output', fixture / 'temp-proof.json', environment=environment)
    run('retire', '--plan', plan_file, '--confirm', plan['id'], success=False)
    assert backup.exists()
    run('retire', '--plan', plan_file, '--confirm', plan['id'], '--acknowledge', 'wrong phrase', success=False)
    assert backup.exists()
    run('retire', '--plan', plan_file, '--confirm', plan['id'], '--acknowledge',
        'I UNDERSTAND MY OLD PROJECTS WILL BE DELETED AND UNRECOVERABLE')
    assert not backup.exists() and (target / 'hello.txt').is_file()
    print(json.dumps({'windowed_gui': 'passed', 'bundled_native_copy': 'passed', 'original_retention': 'passed',
                      'bundled_temp_write': 'passed', 'cleanup_phrase_gate': 'passed'}))
finally:
    assert fixture.resolve().parent == runs.resolve()
    if source.is_symlink() or getattr(source, 'is_junction', lambda: False)():
        assert source.resolve() == target.resolve()
        os.rmdir(source)
    shutil.rmtree(fixture)
