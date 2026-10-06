# Local validation — 6 October 2026

## Desktop setup v0.2.0

Windows with Python 3.14: **51 fixture tests passed** in 20.415 seconds. New cases cover saved desktop sessions, exact project destinations, nested profile/cache mapping, standalone Claude preferences, bounded discovery, native-copy failures, retained originals, corruption detected before deleting any root (including a previously hash-verified copy with unchanged size/timestamps), and the exact cleanup phrase in both the UI and backend. Detection covers Windows environment-variable casing, pip's actual cache directory, npm global packages, Codex desktop storage and older uv layouts. Windows PowerShell 5 status/journal integration passed.

The portable Windows GUI/worker bundle was built with PyInstaller 6.22.3. Its windowed Tk startup, native copy/cutover on disposable folders, retained originals, a real bundled-process temp write, and refusal of missing/wrong cleanup acknowledgments passed. UI fixtures were inspected at 1040×760 and 880×690, including review and permanent-cleanup states. Exact-destination controls and the fixed footer fit the compact window.

A 5,000-file synthetic fixture took **4.217 seconds** for native copying with metadata checks and **0.852 seconds** for the subsequent unchanged pass. A separate portable content-verified run took 24.937 seconds. The verification policies differ and other processes were active; this comparison is not a general speed multiplier. Permanent cleanup in fast mode defers SHA-256 checks until explicitly requested. These runs do not predict large production migrations or physical drive performance.

Hosted results appear in [fixture CI](https://github.com/quorraa/ai-storage-mover/actions/workflows/test.yml) and the [Windows download build](https://github.com/quorraa/ai-storage-mover/actions/workflows/windows-download.yml). A complete new Windows installation with every real provider, shell integration and updater remains an end-to-end release check; neither fixture tests nor the risk notice replaces an independent manual backup.

## Earlier CLI checkpoint

Windows with Python 3.14: **31 fixture tests passed** in 23.485 seconds. Fixtures cover verified cutover, restart after interruptions, protected deletion, concurrent writers and space reservations, equal-metadata corruption, scoped temp writes, and Codex/Claude directory records while preserving prompts and history. Configuration fixtures preserve MCP secrets, HTTP servers, existing global instructions and legacy preferences; a second setup is idempotent.

Native LevelDB fixtures passed for live-lock refusal, unchanged authentication bytes, Unicode destinations, opaque working-directory identifiers, component boundaries, idempotent repairs and invalid-store refusal. Windows PowerShell 5 parsed the setup script successfully and executed its actual status function on disposable fixtures: atomic replacement of an existing file, preserved journal fields and monotonic progress passed. The complete guided setup has not been run end to end against a fresh Windows installation; its native shell/shortcut integrations still need that release check.

The final wheel was built without runtime dependencies, installed into an isolated local folder, and checked with the CLI help command. Its packaged dashboard and Windows activation script are present. The loopback dashboard served its measured status with no-store and CSP headers; an unqualified status route returned 404.

An earlier 1,000-file synthetic run on this machine took 4.691 seconds for cold verification/copy and 0.170 seconds with the existing verification journal. These numbers describe that fixture, not the performance of a multi-million-file migration.

GitHub CI runs on Windows and Linux with Python 3.11 and 3.13. See the [hosted fixture results](https://github.com/quorraa/ai-storage-mover/actions/workflows/test.yml) for each published revision. The source is published at [quorraa/ai-storage-mover](https://github.com/quorraa/ai-storage-mover).
