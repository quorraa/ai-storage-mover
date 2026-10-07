"""Package the complete portable bundle, including its executable configuration."""
import hashlib
from pathlib import Path
import tomllib
import zipfile


root = Path(__file__).resolve().parents[1]
bundle = root / 'dist' / 'AI Storage Mover'
version = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
archive = root / 'dist' / f'ai-storage-mover-v{version}-windows-x64.zip'
required = ('AI Storage Mover.exe', 'AI Storage Mover.exe.config',
            'ai-storage-worker.exe', 'LICENSE.txt', 'README.md',
            '_internal/pythonnet/runtime/Python.Runtime.dll',
            '_internal/ai_storage_mover/desktop/Inter-LICENSE.txt')
assert all((bundle / name).is_file() for name in required), 'Incomplete desktop bundle'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for file in sorted(bundle.rglob('*')):
        if file.is_file():
            relative = file.relative_to(bundle)
            assert not file.name.endswith('.local.json'), relative
            assert not any(part in ('.runs', '.migrations', '.codex', '.claude') for part in relative.parts), relative
            output.write(file, Path('AI Storage Mover') / relative)
with zipfile.ZipFile(archive) as packaged:
    assert packaged.testzip() is None, 'ZIP failed CRC validation'
    assert all('AI Storage Mover/' + name in packaged.namelist() for name in required)
with archive.open('rb') as file:
    digest = hashlib.file_digest(file, 'sha256').hexdigest()
(archive.parent / 'SHA256SUMS.txt').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
print(f'{archive.name}: {archive.stat().st_size} bytes; SHA256 {digest}')
