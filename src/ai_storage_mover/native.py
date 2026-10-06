"""Windows copy acceleration. No mirror, purge, move or source deletion."""
import os
from pathlib import Path
import shutil
import subprocess
import time

from .model import MigrationError, linked, physical_parents


def written_bytes(process):
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
    function = ctypes.WinDLL('kernel32', use_last_error=True).GetProcessIoCounters
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters)]
    function.restype = wintypes.BOOL
    values = Counters()
    return values.write_bytes if function(wintypes.HANDLE(int(process._handle)), ctypes.byref(values)) else None


def command(source, destination, threads=16):
    return ['robocopy.exe', str(source), str(destination), '/E', f'/MT:{threads}',
            '/R:1', '/W:0', '/COPY:DAT', '/DCOPY:DAT', '/XJ', '/SL',
            '/XC', '/XN', '/XO', '/NFL', '/NDL', '/NP']


def copy_new_tree(entry, run, *, reserve, notify, cancelled=lambda: False):
    """Accelerate fresh trees; the journal handles existing/conflicting trees.

    Avoid native traversal of pre-existing destination junctions altogether.
    A subsequent metadata/content pass builds the same guarded manifest as
    the portable engine. An interrupted native pass is safe to resume there.
    """
    source, destination = Path(entry['source']), Path(entry['destination'])
    if not source.is_dir() or linked(source) or linked(destination):
        return False
    physical_parents(destination)
    if destination.exists():
        if not destination.is_dir():
            return False
        with os.scandir(destination) as children:
            if next(children, None) is not None:
                return False
    destination.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination).free < reserve:
        raise MigrationError('Destination free-space reserve would be crossed')
    log = Path(run) / ('native-' + entry['id'] + '.log')
    with log.open('wb') as output:
        process = subprocess.Popen(command(source, destination), stdout=output,
                                   stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while process.poll() is None:
                if cancelled():
                    raise MigrationError('Stopped. Original files are retained.')
                if shutil.disk_usage(destination).free < reserve:
                    raise MigrationError('Destination free-space reserve would be crossed; originals retained')
                notify('native-copy', detail=f'Copying {source.name} with 16 parallel Windows workers', percent=2,
                       transfer_bytes=written_bytes(process))
                time.sleep(0.25)
            # Robocopy 0–7 are successful/non-fatal, including extra target files.
            if process.returncode >= 8:
                raise MigrationError(f'Windows copy stopped (code {process.returncode}). Details: {log}')
        finally:
            if process.poll() is None:
                # Only our disposable copy worker; never an AI application.
                process.terminate()
                process.wait(timeout=10)
    return True
