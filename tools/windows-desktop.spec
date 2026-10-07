# Two launchers share one portable runtime. No one-file extraction to C: temp.
from pathlib import Path
import shutil

root = Path(SPECPATH).parent
data = [(str(root / 'src' / 'ai_storage_mover' / name), 'ai_storage_mover')
        for name in ('Setup-Storage.ps1', 'Activate-Package.ps1', 'repair_claude_browser_state.cjs', 'dashboard.html')]
data.append((str(root / 'src' / 'ai_storage_mover' / 'desktop'), 'ai_storage_mover/desktop'))
gui = Analysis([str(root / 'tools' / 'desktop_entry.pyw')], pathex=[str(root / 'src')], datas=data)
worker = Analysis([str(root / 'tools' / 'worker_entry.py')], pathex=[str(root / 'src')], datas=data)
gui_exe = EXE(PYZ(gui.pure), gui.scripts, exclude_binaries=True, name='AI Storage Mover', console=False, upx=False)
worker_exe = EXE(PYZ(worker.pure), worker.scripts, exclude_binaries=True, name='ai-storage-worker', console=True, upx=False)
COLLECT(gui_exe, worker_exe, gui.binaries, gui.datas, worker.binaries, worker.datas,
        name='AI Storage Mover', upx=False)
# The CLR reads this beside the executable before pywebview loads Python.NET.
# Putting it in _internal would leave Internet-marked downloads unable to start.
shutil.copy2(root / 'tools' / 'desktop.exe.config',
             Path(DISTPATH) / 'AI Storage Mover' / 'AI Storage Mover.exe.config')
