import argparse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import webbrowser

from .engine import Engine, run_lock
from .model import CLEANUP_PHRASE, MigrationError, atomic_json, discover, make_plan, read_json, validate
from .runtime import launch, settings
from .references import repoint_files, repoint_codex, repoint_claude
from .configure import configure


def dashboard(run, port=0, open_browser=True):
    run = Path(run).absolute()
    page = Path(__file__).with_name('dashboard.html').read_bytes()
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/' + token:
                data, mime = page, 'text/html; charset=utf-8'
            elif self.path == '/' + token + '/status':
                try:
                    data = (run / 'status.json').read_bytes()
                except FileNotFoundError:
                    data = b'{"phase":"waiting","detail":"No operation has started","percent":0}'
                mime = 'application/json'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(('127.0.0.1', port), Handler) as server:
        url = f'http://127.0.0.1:{server.server_port}/{token}'
        print(url, flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv == ['setup']:
        from .gui import main as wizard
        return wizard()
    parser = argparse.ArgumentParser(description='Move AI/project storage; keep desktop installers and Windows-managed package data in place.')
    commands = parser.add_subparsers(dest='action', required=True)
    repair = commands.add_parser('repair-worker', help=argparse.SUPPRESS)
    repair.add_argument('--record', required=True)
    plan = commands.add_parser('plan', help='Create an explicit path plan; no source files are changed')
    plan.add_argument('--storage-root', required=True)
    plan.add_argument('--project', action='append', default=[])
    plan.add_argument('--profile', action='append', choices=['codex', 'claude', 'shared', 'caches'], default=[])
    plan.add_argument('--root', action='append', default=[], metavar='SOURCE=DESTINATION')
    plan.add_argument('--verification', choices=['hash', 'metadata'], default='hash')
    plan.add_argument('--workers', type=int, default=4)
    plan.add_argument('--transfer', choices=['auto', 'native', 'portable'], default='auto')
    plan.add_argument('--reserve-gib', type=float, default=2)
    plan.add_argument('--output', required=True)
    for action in ('inspect', 'stage', 'apply', 'retire', 'rollback'):
        sub = commands.add_parser(action)
        sub.add_argument('--plan', required=True)
        if action in ('apply', 'rollback'):
            sub.add_argument('--apps-closed', action='store_true')
        if action == 'retire':
            sub.add_argument('--confirm', required=True, help='Exact run ID from the reviewed plan')
            sub.add_argument('--acknowledge', required=True, help=CLEANUP_PHRASE)
    runtime = commands.add_parser('runtime', help='Generate launch-scoped profile, cache and temp locations')
    runtime.add_argument('--storage-root', required=True)
    runtime.add_argument('--output', required=True)
    run = commands.add_parser('run', help='Launch a command with storage settings inherited by its children')
    run.add_argument('--runtime', required=True)
    run.add_argument('command', nargs=argparse.REMAINDER)
    package = commands.add_parser('package', help='Use Windows package activation rather than starting a WindowsApps executable directly')
    package.add_argument('--name', required=True)
    package.add_argument('--app-id', required=True)
    package.add_argument('--runtime')
    view = commands.add_parser('dashboard', help='Independent local live dashboard')
    view.add_argument('--plan', required=True)
    view.add_argument('--port', type=int, default=0)
    view.add_argument('--no-browser', action='store_true')
    references = commands.add_parser('references', help='Repoint selected configs and known Codex/Claude project and session directories')
    references.add_argument('--plan', required=True)
    references.add_argument('--file', action='append', default=[])
    references.add_argument('--codex-home')
    references.add_argument('--claude-home')
    references.add_argument('--claude-desktop-home', help='Explicit desktop data folder; package registration and files stay in place')
    setup = commands.add_parser('configure', help='Repair saved provider paths and configure future projects, builds, temp and MCP caches without rescanning files')
    setup.add_argument('--plan', required=True)
    setup.add_argument('--runtime', required=True)
    setup.add_argument('--codex-home')
    setup.add_argument('--claude-home')
    setup.add_argument('--claude-desktop-home', action='append', default=[])
    setup.add_argument('--apps-closed', action='store_true')
    setup.add_argument('--projects', help='Default directory for new projects')
    windows = commands.add_parser('setup', help='Windows guided setup: preflight, cutover, cached paths, future writes and launchers')
    windows.add_argument('--plan', required=True)
    windows.add_argument('--storage-root', required=True)
    windows.add_argument('--projects')
    windows.add_argument('--configure-only', action='store_true', help='Skip file migration; repair configuration after a completed cutover')
    windows.add_argument('--apps-closed', action='store_true')
    proof = commands.add_parser('verify-runtime', help=argparse.SUPPRESS)
    proof.add_argument('--runtime', required=True)
    proof.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'repair-worker':
            from .repair import run_job
            return run_job(args.record)
        elif args.action == 'plan':
            roots = discover(args.storage_root, args.project, args.profile)
            for custom in args.root:
                if '=' not in custom:
                    raise MigrationError('--root must be SOURCE=DESTINATION')
                a, b = custom.split('=', 1)
                roots.append((a, b, 'custom'))
            value = make_plan(roots, args.storage_root, verification=args.verification,
                              workers=args.workers, reserve_bytes=int(args.reserve_gib * 1024**3))
            value['transfer'] = args.transfer
            atomic_json(args.output, value)
            print(json.dumps(value, indent=2))
        elif args.action == 'verify-runtime':
            import tempfile
            runtime = read_json(args.runtime)
            expected = Path(runtime['environment']['TEMP']).resolve()
            with tempfile.NamedTemporaryFile() as stream:
                stream.write(b'proof')
                stream.flush()
                actual = Path(stream.name).resolve().parent
                if actual != expected:
                    raise MigrationError(f'Temp write used {actual}, expected {expected}')
            atomic_json(args.output, {'temp': str(actual), 'environment': runtime['environment']})
        elif args.action == 'runtime':
            value = settings(args.storage_root)
            atomic_json(args.output, value)
            print(json.dumps(value, indent=2))
        elif args.action == 'run':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            return launch(read_json(args.runtime), command)
        elif args.action == 'package':
            if os.name != 'nt':
                raise MigrationError('Package activation is a Windows feature')
            cmd = ['powershell.exe', '-NoProfile', '-File', str(Path(__file__).with_name('Activate-Package.ps1')),
                   '-PackageName', args.name, '-ApplicationId', args.app_id]
            if args.runtime:
                cmd += ['-RuntimePath', str(Path(args.runtime).absolute())]
            return subprocess.call(cmd)
        elif args.action == 'setup':
            if os.name != 'nt':
                raise MigrationError('The guided setup is a Windows feature; use configure on other systems')
            cmd = ['powershell.exe', '-NoProfile', '-File', str(Path(__file__).with_name('Setup-Storage.ps1')),
                   '-PlanPath', str(Path(args.plan).absolute()), '-StorageRoot', str(Path(args.storage_root).absolute()),
                   '-PythonPath', sys.executable]
            if args.projects:
                cmd += ['-ProjectsPath', str(Path(args.projects).absolute())]
            if args.configure_only:
                cmd += ['-ConfigureOnly']
            if args.apps_closed:
                cmd += ['-AppsClosed']
            return subprocess.call(cmd)
        else:
            value = validate(read_json(args.plan))
            if args.action == 'inspect':
                print(json.dumps(value, indent=2))
            elif args.action == 'dashboard':
                dashboard(value['run_dir'], args.port, not args.no_browser)
            elif args.action == 'references':
                with run_lock(Path(value['run_dir'])):
                    result = {'files': repoint_files(value, args.file)}
                    if args.codex_home:
                        result['codex'] = repoint_codex(value, args.codex_home)
                    if args.claude_home or args.claude_desktop_home:
                        result['claude'] = repoint_claude(value, args.claude_home, args.claude_desktop_home)
                    print(json.dumps(result, indent=2))
            elif args.action == 'configure':
                with run_lock(Path(value['run_dir'])):
                    result = configure(value, read_json(args.runtime), codex=args.codex_home, claude=args.claude_home,
                                       desktops=args.claude_desktop_home, projects=args.projects, apps_closed=args.apps_closed)
                    print(json.dumps(result, indent=2))
            else:
                with run_lock(Path(value['run_dir'])), closing(Engine(value)) as engine:
                    try:
                        if args.action == 'stage':
                            print(json.dumps(engine.stage(), indent=2))
                        elif args.action == 'apply':
                            engine.apply(apps_closed=args.apps_closed)
                        elif args.action == 'retire':
                            engine.retire(args.confirm, acknowledgment=args.acknowledge)
                        elif args.action == 'rollback':
                            engine.rollback(apps_closed=args.apps_closed)
                    except BaseException as exc:
                        engine.fail(exc)
                        raise
    except (MigrationError, OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0
