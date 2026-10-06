"""Smoke-check an isolated installed wheel and its loopback dashboard."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

base = Path(__file__).resolve().parents[1] / '.runs'
installed = base / 'smoke-install'
environment = dict(os.environ, PYTHONPATH=str(installed))
package = installed / 'ai_storage_mover'
assert (package / 'dashboard.html').is_file()
assert (package / 'Activate-Package.ps1').is_file()
assert (package / 'Setup-Storage.ps1').is_file()
assert (package / 'repair_claude_browser_state.cjs').is_file()
for asset in ('index.html', 'style.css', 'app.js', 'InterVariable.woff2', 'Inter-LICENSE.txt'):
    assert (package / 'desktop' / asset).is_file()
subprocess.run([sys.executable, '-m', 'ai_storage_mover', '--help'], env=environment, check=True, stdout=subprocess.DEVNULL)
fixture = Path(tempfile.mkdtemp(prefix='dashboard-smoke-', dir=base))
(fixture / 'status.json').write_text(json.dumps({'phase': 'done', 'percent': 100, 'done': 3, 'total': 3, 'detail': 'fixture'}))
code = 'from ai_storage_mover.cli import dashboard; dashboard(' + repr(str(fixture)) + ', open_browser=False)'
process = subprocess.Popen([sys.executable, '-u', '-c', code], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    url = process.stdout.readline().strip()
    assert url.startswith('http://127.0.0.1:')
    with urllib.request.urlopen(url, timeout=5) as response:
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'Content-Security-Policy' in response.headers
        assert b'<html' in response.read().lower()
    with urllib.request.urlopen(url + '/status', timeout=5) as response:
        value = json.load(response)
        assert value['percent'] == 100 and value['done'] == value['total']
    try:
        urllib.request.urlopen(url.rsplit('/', 1)[0] + '/status', timeout=5)
        raise AssertionError('An unqualified endpoint should not expose status')
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
finally:
    # Only the disposable server spawned above is terminated.
    process.terminate()
    process.communicate(timeout=10)
print(json.dumps({'isolated_wheel': 'passed', 'packaged_dashboard': 'passed', 'packaged_activation_script': 'passed', 'loopback_status': 'passed', 'unguessed_route': '404'}))
