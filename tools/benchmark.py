"""Disposable synthetic verification benchmark; no production paths are scanned."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_storage_mover.engine import Engine
from ai_storage_mover.model import make_plan

parser = argparse.ArgumentParser()
parser.add_argument('--files', type=int, default=1000)
args = parser.parse_args()
if not 1 <= args.files <= 100000:
    parser.error('Choose 1 through 100000 disposable files')
base = Path(__file__).resolve().parents[1] / '.runs'
base.mkdir(exist_ok=True)
fixture = Path(tempfile.mkdtemp(prefix='benchmark-', dir=base))
try:
    source = fixture / 'source'
    source.mkdir()
    for i in range(args.files):
        folder = source / str(i // 100)
        folder.mkdir(exist_ok=True)
        (folder / (str(i) + '.txt')).write_bytes((str(i) + ': sample data').encode() * 20)
    plan = make_plan([(source, fixture / 'target', 'project')], fixture / 'storage', reserve_bytes=0)
    with closing(Engine(plan)) as engine:
        start = time.perf_counter()
        cold = engine.stage()
        cold_time = time.perf_counter() - start
        start = time.perf_counter()
        warm = engine.stage()
        warm_time = time.perf_counter() - start
    print(json.dumps(dict(files=args.files, cold_seconds=round(cold_time, 3), journal_reused_seconds=round(warm_time, 3),
                         cold_copied=cold['copied'], second_copied=warm['copied'], second_reused=warm['reused'],
                         note='Synthetic local fixture; not an estimate of production migration/deletion speed'), indent=2))
finally:
    resolved = fixture.resolve()
    if not resolved.is_relative_to(base.resolve()) or resolved == base.resolve():
        raise RuntimeError('Benchmark cleanup escaped its disposable root')
    shutil.rmtree(fixture)
