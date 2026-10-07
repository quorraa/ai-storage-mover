"""Verify the shipped repair launcher survives an actual launching-process tree kill.

Only a read-only heartbeat task runs. No real app profile is inspected or modified.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bundle', type=Path)
args = parser.parse_args()
base = root / '.runs' / ('repair-lifetime-' + uuid.uuid4().hex)
base.mkdir(parents=True)
pointer = base / 'launched.json'
child = """
import json, sys, time
from pathlib import Path
import ai_storage_mover.repair as repair
if sys.argv[3]:
    sys.frozen = True
    bundle = Path(sys.argv[3]).resolve()
    sys.executable = str(bundle / 'AI Storage Mover.exe')
    repair.__file__ = str(bundle / '_internal' / 'ai_storage_mover' / 'repair.py')
record = repair.start_job(Path(sys.argv[1]), 'probe')
Path(sys.argv[2]).write_text(json.dumps({'record': str(record)}))
time.sleep(90)
"""
env = dict(os.environ, PYTHONPATH=str(root / 'src'))
flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
process = subprocess.Popen([sys.executable, '-c', child, str(base), str(pointer), str(args.bundle or '')],
                           env=env, creationflags=flags, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def await_status(record, predicate, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = json.loads((record / 'status.json').read_text())
            if value.get('phase') == 'failed':
                raise AssertionError(value)
            if predicate(value):
                return value
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(.2)
    raise AssertionError('No fresh independent heartbeat within test deadline')


try:
    deadline = time.monotonic() + 35
    while not pointer.exists() and time.monotonic() < deadline and process.poll() is None:
        time.sleep(.2)
    if not pointer.exists():
        if process.poll() is not None:
            raise AssertionError(process.communicate()[1].decode(errors='replace'))
        raise AssertionError('Repair launcher did not return a record')
    record = Path(json.loads(pointer.read_text())['record'])
    assert record.resolve().parent == base.resolve()
    first = await_status(record, lambda s: s.get('tick', -1) >= 1)
    # Real process-tree teardown, not a mocked subprocess or a detached-child assumption.
    killed = subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                            timeout=15, creationflags=flags)
    assert killed.returncode == 0, killed.stderr
    process.wait(timeout=10)
    after = await_status(record, lambda s: s.get('tick', -1) >= first['tick'] + 2)
    assert after['pid'] == first['pid'] and after['unpackaged'] is True
    final = await_status(record, lambda s: s.get('phase') == 'complete')
    task = json.loads((record / 'request.json').read_text())['task']
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        query = subprocess.run(['schtasks.exe', '/Query', '/TN', task], capture_output=True, creationflags=flags)
        if query.returncode:
            break
        time.sleep(.3)
    assert query.returncode, 'One-shot task was not removed'
    proof = dict(launcher_tree_terminated=True, fresh_heartbeat_after_teardown=True,
                 unpackaged=True, task_removed=True, bundled=bool(args.bundle), record=str(record))
    (base / 'proof.json').write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof))
finally:
    if process.poll() is None:
        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=flags)
        process.wait(timeout=10)
    if pointer.exists():
        record = Path(json.loads(pointer.read_text())['record'])
        assert record.resolve().parent == base.resolve()
        request = json.loads((record / 'request.json').read_text())
        assert request['mode'] == 'probe' and request['task'] == 'AIStorageMover-Repair-' + record.name
        subprocess.run(['schtasks.exe', '/Delete', '/TN', request['task'], '/F'], capture_output=True, creationflags=flags)
