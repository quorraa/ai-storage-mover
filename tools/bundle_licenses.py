"""Retain installed dependency notices alongside the Windows download."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
bundle = root / 'dist' / 'AI Storage Mover'
assert bundle.is_dir()
shutil.copy2(root / 'LICENSE', bundle / 'LICENSE.txt')
shutil.copy2(root / 'README.md', bundle / 'README.md')
shutil.copy2(Path(sys.base_prefix) / 'LICENSE.txt', bundle / 'PYTHON-LICENSE.txt')
notices = bundle / 'licenses'
for name in ('pywebview', 'pythonnet', 'clr_loader', 'cffi', 'pycparser', 'bottle',
             'proxy_tools', 'typing_extensions', 'PyInstaller'):
    installed = distribution(name)
    target = notices / (name + '-' + installed.version)
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for file in installed.files or ():
        if any(word in str(file).lower() for word in ('license', 'copying', 'copyright')):
            source = Path(installed.locate_file(file))
            if source.is_file():
                shutil.copy2(source, target / source.name)
                copied += 1
    if not copied:
        # Preserve upstream metadata and source attribution when no notice file ships.
        (target / 'METADATA.txt').write_text(installed.read_text('METADATA') or '', encoding='utf-8')
        if name == 'proxy_tools':
            shutil.copy2(installed.locate_file('proxy_tools/__init__.py'), target / 'attributed-source.py')
print('Bundled Python and installed dependency notices.')
