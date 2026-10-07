"""Offline desktop UI with a native folder picker and a narrow Python bridge."""
import base64
import os
from pathlib import Path
import shutil
import sys
import threading
import time

from .discovery import candidates, project_suggestions, scan_folder
from .model import CLEANUP_PHRASE, MigrationError, atomic_json, read_json
from .wizard import backups, cleanup, create_session, load_session, migrate


class SetupAPI:
    """Exposed operations are selections or the explicitly reviewed session only."""
    def __init__(self):
        self._window = None
        self._session = None
        self._busy = False
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._error = ''
        self._result = None
        self._operation = None
        self._started = None
        self._repair = None
        try:
            self._repair = Path(read_json(self._repair_pointer())['record'])
        except (OSError, ValueError, KeyError):
            pass

    def _repair_pointer(self):
        return self._recent_file().with_name('recent-repair.local.json')

    def _repair_status(self):
        if not self._repair:
            return None
        try:
            result = read_json(self._repair / 'status.json')
            result['record'] = str(self._repair)
            result['mode'] = read_json(self._repair / 'request.json')['mode']
            from .repair import TERMINAL
            result['active'] = result['phase'] not in TERMINAL
            if result['active'] and time.time() - result.get('updated', 0) > 35 * 60:
                result.update(active=False, phase='failed', detail='Repair worker stopped responding. Inspect the retained record before trying again.')
            return result
        except (OSError, ValueError, KeyError):
            return dict(active=False, phase='failed', detail='Repair record is unavailable.', record=str(self._repair))

    def _recent_file(self):
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2] / '.runs'
        return base / 'recent-migration.local.json'

    def _remember(self):
        try:
            atomic_json(self._recent_file(), {'session': str(Path(self._session['plan']['run_dir']) / 'wizard.local.json')})
        except OSError:
            pass

    def _idle(self):
        if self._busy:
            raise MigrationError('Wait for the current operation to finish')
        if (self._repair_status() or {}).get('active'):
            raise MigrationError('Wait for the Codex repair check or repair to finish')

    def _task(self, name, action):
        with self._lock:
            self._idle()
            self._busy, self._operation = True, name
            self._result, self._error, self._started = None, '', time.monotonic()
            self._stop.clear()
        def work():
            try:
                result = action()
                with self._lock:
                    self._result = result
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)
            finally:
                with self._lock:
                    self._busy = False
        threading.Thread(target=work, name='storage-' + name, daemon=False).start()
        return {'started': True}

    def snapshot(self):
        with self._lock:
            value = dict(busy=self._busy, operation=self._operation, error=self._error,
                         result=self._result, stopping=self._stop.is_set(),
                         elapsed=int(time.monotonic() - self._started) if self._started else 0,
                         session=self._summary(), cleanup_phrase=CLEANUP_PHRASE)
            value['repair'] = self._repair_status()
            if self._session and self._operation in ('migration', 'cleanup'):
                try:
                    value['progress'] = read_json(Path(self._session['plan']['run_dir']) / 'status.json')
                except (OSError, ValueError):
                    value['progress'] = {'percent': 0, 'detail': 'Checking apps and folders…'}
            return value

    def check_repair(self):
        with self._lock:
            self._idle()
            from .repair import start_job
            self._repair = start_job(self._recent_file().parent / 'repairs', 'inspect')
            atomic_json(self._repair_pointer(), dict(record=str(self._repair)))
            return self._repair_status()

    def start_repair(self, confirmed=False):
        with self._lock:
            self._idle()
            previous = self._repair_status() or {}
            inspection = previous.get('inspection')
            if confirmed is not True or previous.get('phase') != 'complete' or not inspection or not inspection.get('affected'):
                raise MigrationError('Check this computer and confirm the repair first.')
            from .repair import start_job
            self._repair = start_job(self._recent_file().parent / 'repairs', 'apply', inspection)
            atomic_json(self._repair_pointer(), dict(record=str(self._repair)))
            return self._repair_status()

    def stop_repair(self):
        if self._repair and (self._repair_status() or {}).get('active'):
            (self._repair / 'STOP').touch()
        return {'stopping': True}

    def open_repair_record(self):
        if self._repair and self._repair.is_dir() and os.name == 'nt':
            os.startfile(str(self._repair))

    def _summary(self):
        if not self._session:
            return None
        s = self._session
        return dict(status=s['status'], projects=s['projects'], storage=s['storage'],
                    roots=s['plan']['roots'], backups=backups(s), run_dir=s['plan']['run_dir'],
                    runtime=s['runtime']['environment'], verification=s['plan']['verification'])

    def choose_folder(self, title='Choose a folder', current=''):
        self._idle()
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=current or '')
        # Keep logical aliases until the backend has checked protected paths.
        return str(Path(result[0]).absolute()) if result else None

    def drives(self):
        result = []
        if os.name == 'nt':
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for n in range(26):
                if not mask & (1 << n):
                    continue
                path = chr(65 + n) + ':\\'
                if ctypes.windll.kernel32.GetDriveTypeW(path) != 3:
                    continue
                try:
                    result.append(dict(path=path, free=shutil.disk_usage(path).free))
                except OSError:
                    pass
        return result

    def available_space(self, folder):
        path = Path(folder).absolute()
        while not path.exists() and path != path.parent:
            path = path.parent
        return shutil.disk_usage(path).free

    def detected_data(self):
        self._idle()
        return candidates()

    def find_projects(self):
        return self._task('search', lambda: dict(projects=project_suggestions(), temps=[], limited=False))

    def scan(self, folder):
        return self._task('search', lambda: scan_folder(folder, cancelled=self._stop.is_set))

    def review(self, selections):
        with self._lock:
            self._idle()
            if not selections.get('projects'):
                raise MigrationError('Select at least one project folder')
            if not selections.get('storage'):
                raise MigrationError('Choose a destination folder')
            self._session = create_session(selections['projects'], selections['storage'], selections.get('items', []),
                projects_destination=selections.get('project_destination'), destinations=selections.get('destinations'),
                tools_temp=selections.get('tools_temp'), claude_temp=selections.get('claude_temp'),
                verify_contents=bool(selections.get('verify_contents')))
            return self._summary()

    def start_migration(self, apps_closed=False):
        if not self._session or not apps_closed:
            raise MigrationError('Review your selection and close apps and terminals before starting')
        self._remember()
        return self._task('migration', lambda: migrate(self._session, cancelled=self._stop.is_set))

    def start_cleanup(self, phrase, tested=False):
        if not self._session or self._session['status'] != 'complete':
            raise MigrationError('Finish the migration before cleanup')
        if phrase != CLEANUP_PHRASE or tested is not True:
            raise MigrationError('Check the new projects and type the exact confirmation phrase')
        return self._task('cleanup', lambda: cleanup(self._session, phrase, tested=True, cancelled=self._stop.is_set))

    def stop(self):
        self._stop.set()
        return {'stopping': True}

    def restore(self, recent=False):
        self._idle()
        if recent:
            file = read_json(self._recent_file())['session']
        else:
            import webview
            result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=('Saved migration (*.json)',))
            if not result:
                return None
            file = result[0]
        self._session = load_session(file)
        self._operation, self._error, self._result = None, '', None
        return self._summary()

    def open_location(self, kind, index=0):
        if not self._session:
            raise MigrationError('No reviewed migration')
        locations = {'projects': [self._session['projects']], 'record': [self._session['plan']['run_dir']],
                     'backup': backups(self._session), 'destination': [r['destination'] for r in self._session['plan']['roots']]}
        if kind not in locations or type(index) is not int or not 0 <= index < len(locations[kind]):
            raise MigrationError('Unknown migration location')
        path = Path(locations[kind][index])
        if not path.is_dir():
            path = path.parent
        if not path.is_dir():
            raise MigrationError('This folder is not available yet')
        if os.name == 'nt':
            os.startfile(str(path))
        else:
            import subprocess
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])

    def close(self):
        with self._lock:
            if self._busy:
                self._stop.set()
                return False
        self._window.destroy()
        return True

    def _on_closing(self):
        with self._lock:
            if self._busy:
                self._stop.set()
                return False
        return True


def document():
    """Inline all local assets; no HTTP server, remote assets or debugging port."""
    assets = Path(__file__).with_name('desktop')
    html = (assets / 'index.html').read_text(encoding='utf-8')
    css = (assets / 'style.css').read_text(encoding='utf-8')
    font = base64.b64encode((assets / 'InterVariable.woff2').read_bytes()).decode('ascii')
    css = css.replace('INTER_FONT_DATA', 'data:font/woff2;base64,' + font)
    return html.replace('/* INLINE_STYLE */', css).replace('/* INLINE_SCRIPT */', (assets / 'app.js').read_text(encoding='utf-8'))


def main(self_test=None):
    try:
        import webview
    except ImportError as exc:
        raise SystemExit('Use the Windows download, or install ai-storage-mover[desktop] for source development') from exc
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
    webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = False
    api = SetupAPI()
    window = webview.create_window('AI Storage Mover', html=document(), js_api=api,
        width=1120, height=790, min_size=(850, 660), background_color='#f7f8fa', text_select=True,
        hidden=bool(self_test), confirm_close=False)
    api._window = window
    window.events.closing += api._on_closing
    def smoke():
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                result = window.evaluate_js('window.__uiSmoke ? window.__uiSmoke() : null')
                if result and result.get('ready'):
                    if not all(result.get(k) for k in ('projects', 'theme_switch', 'cleanup_gate')):
                        raise RuntimeError('Desktop UI smoke check failed')
                    atomic_json(self_test, dict(desktop='passed', renderer='WebView2', **result))
                    window.destroy()
                    return
            except Exception:
                pass
            time.sleep(.1)
        window.destroy()
    webview.start(smoke if self_test else None, gui='edgechromium' if os.name == 'nt' else None,
                  debug=False, http_server=False, private_mode=True)
