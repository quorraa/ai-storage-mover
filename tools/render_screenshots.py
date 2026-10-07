"""Capture the real interface using exclusively fictional, read-only demo state.

Requires Windows, the desktop extra and Pillow. No app profiles, disks, project
records or credentials are inspected. No migration operations are available.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import time

from PIL import Image
import webview

from ai_storage_mover.gui import document


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs' / 'screenshots'
PROJECTS = [r'C:\Projects\Sample Agent', r'C:\Projects\Demo Workspace']
ITEMS = [
    dict(label='Codex profile', source=r'C:\Users\Demo\.codex', category='profile', slot='Profiles/codex'),
    dict(label='uv cache', source=r'C:\Users\Demo\AppData\Local\uv\cache', category='cache', slot='Cache/uv/cache'),
    dict(label='Claude profile', source=r'C:\Users\Demo\.claude', category='profile', slot='Profiles/claude'),
]
RUNTIME = dict(TEMP=r'E:\AI\Temp\tools', CLAUDE_CODE_TMPDIR=r'E:\AI\Temp\claude')
ROOTS = [dict(source=p, destination='E:\\Projects\\' + p.split('\\')[-1], category='project') for p in PROJECTS]
ROOTS += [dict(source=i['source'], destination='E:\\AI\\' + i['slot'].replace('/', '\\'), category=i['category']) for i in ITEMS]
SESSION = dict(status='reviewed', roots=ROOTS, projects=r'E:\Projects', runtime=RUNTIME,
               backups=[r['source'] + '.ai-mover-backup-demo' for r in ROOTS])


class DemoAPI:
    """No live-data reads and no writable operations, even if a control is clicked."""
    def snapshot(self):
        return dict(busy=False, session=None, operation=None, error='', result=None)

    def drives(self):
        return [dict(path='C:\\', free=96 * 1024**3), dict(path='E:\\', free=740 * 1024**3)]

    def available_space(self, folder):
        return 740 * 1024**3

    def choose_folder(self, *args):
        return None


def capture(name):
    """PrintWindow captures only a verified window owned by this process."""
    user, gdi = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('gdi32', use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetDC.argtypes, user.GetDC.restype = [wintypes.HWND], wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [wintypes.HDC], wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes, gdi.CreateCompatibleBitmap.restype = [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HBITMAP
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE
    gdi.DeleteObject.argtypes, gdi.DeleteDC.argtypes = [wintypes.HANDLE], [wintypes.HDC]
    hwnds = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]

    @callback_type
    def own_window(hwnd, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid() and user.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(200)
            user.GetWindowTextW(hwnd, title, len(title))
            if title.value == 'AI Storage Mover':
                hwnds.append(hwnd)
        return True

    user.EnumWindows(own_window, 0)
    assert len(hwnds) == 1, 'Refusing to capture an ambiguous or unowned window'
    hwnd = hwnds[0]
    rect = wintypes.RECT()
    assert user.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    source = user.GetDC(hwnd)
    memory = gdi.CreateCompatibleDC(source)
    bitmap = gdi.CreateCompatibleBitmap(source, width, height)
    previous = gdi.SelectObject(memory, bitmap)

    class Header(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('width', ctypes.c_long), ('height', ctypes.c_long),
                    ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                    ('image_size', wintypes.DWORD), ('x', ctypes.c_long), ('y', ctypes.c_long),
                    ('colors', wintypes.DWORD), ('important', wintypes.DWORD)]

    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.POINTER(Header), wintypes.UINT]
    try:
        assert user.PrintWindow(hwnd, memory, 2)
        gdi.SelectObject(memory, previous)
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        assert gdi.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        Image.frombytes('RGB', (width, height), pixels.raw, 'raw', 'BGRX').save(OUTPUT / (name + '.png'))
    finally:
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--empty-only', action='store_true', help='Capture only the first-run project screen')
    parser.add_argument('--repair-only', action='store_true', help='Capture the repair review using fictional paths')
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('This captures the actual Windows window; run on Windows.')
    webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = False
    window = webview.create_window('AI Storage Mover', html=document(), js_api=DemoAPI(),
                                  width=1120, height=790, min_size=(850, 660), text_select=True)
    failures = []

    def work():
        try:
            for _ in range(200):
                if window.evaluate_js('state.ready && document.fonts.status === "loaded"'):
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Interface did not finish loading')
            # Suspend polling before inserting fixture-only progress and completion.
            window.evaluate_js('polling=true; Object.assign(state,' + json.dumps(dict(
                projects=PROJECTS, storage=r'E:\AI', project_destination=r'E:\Projects',
                tools_temp=RUNTIME['TEMP'], claude_temp=RUNTIME['CLAUDE_CODE_TMPDIR'],
                visited=3, apps_closed=False, view='setup', page=0)) +
                ');state.items=' + json.dumps(ITEMS) + ';state.selected=new Set([0,1,2]);state.session=' + json.dumps(SESSION) + ';')

            def shot(name, script, *, compact=False, ready=None):
                window.resize(880 if compact else 1120, 690 if compact else 790)
                window.evaluate_js(script + ';render()')
                if ready:
                    for _ in range(100):
                        if window.evaluate_js(ready):
                            break
                        time.sleep(.1)
                    else:
                        raise RuntimeError(f'{name} did not finish rendering')
                time.sleep(.35)
                capture(name)

            repair = dict(repair=dict(phase='complete', active=False, mode='inspect',
                detail='A redirected Codex Roaming profile was found.', inspection=dict(affected=True,
                public=r'C:\Users\Demo\AppData\Roaming\Codex', source=r'E:\AI\AppData\Codex')))
            shot('repair-dark', "state.view='repair';theme('dark');state.snapshot=" + json.dumps(repair), compact=True)
            if args.repair_only:
                return
            shot('empty-projects-light', "state.view='setup';state.projects=[];state.visited=0;theme('light')")
            shot('empty-projects-dark', "theme('dark')", compact=True)
            if args.empty_only:
                return
            shot('projects-light', "state.projects=" + json.dumps(PROJECTS) + ";state.visited=3;state.view='setup';state.page=0;theme('light')")
            shot('destination-dark', "state.page=1;theme('dark')", compact=True,
                 ready="document.querySelectorAll('#drives button svg').length === 2 && document.querySelector('#space').textContent === '740 GB available'")
            shot('data-dark', "state.page=2;theme('dark')")
            shot('review-light', "state.page=3;theme('light')")
            demo_progress = dict(operation='migration', busy=True, elapsed=45, progress=dict(
                phase='native-copy', percent=42, transfer_bytes=3 * 1024**3,
                detail=r'C:\Projects\Sample Agent → E:\Projects\Sample Agent'))
            shot('progress-dark', "state.view='progress';theme('dark');state.snapshot=" + json.dumps(demo_progress))
            shot('complete-light', "state.view='complete';theme('light');state.session.status='complete'")
            shot('cleanup-dark', "state.view='cleanup';theme('dark');state.snapshot={};")
        except Exception as exc:
            failures.append(exc)
        finally:
            window.destroy()

    webview.start(work, gui='edgechromium', debug=False, http_server=False, private_mode=True)
    if failures:
        raise failures[0]
    print(f'Saved {1 if args.repair_only else 3 if args.empty_only else 10} synthetic-only screenshots to docs/screenshots; no real data read or moved.')


if __name__ == '__main__':
    main()
