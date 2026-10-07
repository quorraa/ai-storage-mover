# Local validation — 6 October 2026

## Desktop-profile safety v0.2.3

Final local Windows/Python 3.14 checks: **67 fixture tests passed** in 27.650 seconds. The real WebView2 review/repair controls, Windows status integration, packaged independent-worker teardown test, and freshly extracted ZIP with Internet-zone flags passed. The ZIP check includes GUI launch, native copying, retained originals, future temp writes and the typed cleanup gate. A separate read-only inspection correctly identified an already-repaired physical Codex profile and made no profile changes.

Desktop-profile moves now fail in the backend, including manual selections, logical junction aliases, enclosing user/AppData folders, old saved plans and desktop-profile runtime overrides. CLI profiles and supported development caches remain eligible.

The repair is tested against disposable profiles: retained original target and account state, preserved caches and empty directories, repeat inspection, corrupt copies, source changes, stale previews, insufficient disk, cancellation, running apps, nested links and rename failure. These fixtures never redirect a real installed app. A real WebView2 flow verifies the repair acknowledgment gate and completion state.

The independent-worker test launches a bounded, read-only heartbeat through the same Windows Task Scheduler launcher used for repair. It terminates the launching process **and its child tree**, observes fresh heartbeats from the same unpackaged worker afterward, and verifies the one-shot task removes itself. This is an actual equivalent parent teardown, not a mocked process-lifetime test. Windows download CI repeats it with the bundled worker.

The repair does not claim measured leak cessation on arbitrary computers. Its success status reports a verified profile copy and completed folder/cache repair. Real application behavior after reopening still needs checking; the earlier incident's measured repair is evidence for this specific remedy, not a universal app/driver guarantee.

## First-run layout v0.2.2

The initial empty project screen was inspected in the real WebView2 window at 1120×790 in light mode and 880×690 in dark mode. The folder icon now sits inside the centered Choose a folder button and inherits its contrasting foreground. The previous standalone icon and the 1:1 icon/background contrast are removed. The existing folder-picker action, disabled Continue state, discovery controls and backup notice are retained. The README gallery now includes this initial screen, using only fictional state.

## Downloaded ZIP startup v0.2.1

The v0.2.0 startup failure was reproduced with Windows Internet-zone metadata on the downloaded `Python.Runtime.dll`. Its bytes matched the published bundle. Tests of locally generated files had missed this download-specific failure. v0.2.1 places `AI Storage Mover.exe.config` beside the executable so the CLR can load this app's managed dependencies while retaining the download flags; it does not change system policy.

The original extracted download passed its real WebView2 launch check after adding that configuration, with its `ZoneId=3` unchanged. A freshly packaged v0.2.1 ZIP was then extracted into a separate folder and every bundled file was marked with `ZoneId=3`. Real GUI rendering, light/dark switching, cleanup gating, native copying, retained originals, temporary writes and refusal of missing/wrong cleanup phrases passed. The flags remained present. The Windows download workflow now runs this test on the actual ZIP before uploading it.

All **55 fixture tests passed** in 23.279 seconds on the local Windows/Python 3.14 build. The test simulates the file metadata of a browser download; it does not automate SmartScreen dialogs or guarantee behavior under every enterprise security policy.

## Desktop setup v0.2.0

Windows with Python 3.14: **55 fixture tests passed** in 20.581 seconds on the final desktop revision. Cases cover saved desktop sessions, exact project destinations, nested profile/cache mapping, standalone Claude preferences, bounded discovery, native-copy failures, retained originals, corruption detected before deleting any root (including a previously hash-verified copy with unchanged size/timestamps), and the exact cleanup phrase in both the UI and backend. Detection covers Windows environment-variable casing, pip's actual cache directory, npm global packages, existing Codex desktop overrides, exclusion of stale packaged-app roaming copies, and older uv layouts. Windows PowerShell 5 status/journal integration passed. The offline UI bridge rejects unreviewed locations and unacknowledged cleanup.

The portable Windows GUI/worker bundle was built with PyInstaller 6.22.3 and pywebview 6.2.1. Its offline WebView2 window, actual light/dark switch, rendered cleanup-button gate, native copy/cutover on disposable folders, retained originals, a real bundled-process temp write, and refusal of missing/wrong cleanup acknowledgments passed. A real-window flow fixture verifies typed storage defaults, revisiting Review after destination edits, future temp locations, starting the exact displayed plan, and keyboard focus after navigation/removing a row; its copy operation is substituted, and original files are untouched. UI fixtures were inspected at 1120×790 and 880×690, including review and permanent-cleanup states. The interface uses native folder dialogs and bundled fonts; it exposes no remote debugging port or HTTP UI server.

A 5,000-file synthetic fixture took **4.217 seconds** for native copying with metadata checks and **0.852 seconds** for the subsequent unchanged pass. A separate portable content-verified run took 24.937 seconds. The verification policies differ and other processes were active; this comparison is not a general speed multiplier. Permanent cleanup in fast mode defers SHA-256 checks until explicitly requested. These runs do not predict large production migrations or physical drive performance.

Hosted results appear in [fixture CI](https://github.com/quorraa/ai-storage-mover/actions/workflows/test.yml) and the [Windows download build](https://github.com/quorraa/ai-storage-mover/actions/workflows/windows-download.yml). A complete new Windows installation with every real provider, shell integration and updater remains an end-to-end release check; neither fixture tests nor the risk notice replaces an independent manual backup.

## Earlier CLI checkpoint

Windows with Python 3.14: **31 fixture tests passed** in 23.485 seconds. Fixtures cover verified cutover, restart after interruptions, protected deletion, concurrent writers and space reservations, equal-metadata corruption, scoped temp writes, and Codex/Claude directory records while preserving prompts and history. Configuration fixtures preserve MCP secrets, HTTP servers, existing global instructions and legacy preferences; a second setup is idempotent.

Native LevelDB fixtures passed for live-lock refusal, unchanged authentication bytes, Unicode destinations, opaque working-directory identifiers, component boundaries, idempotent repairs and invalid-store refusal. Windows PowerShell 5 parsed the setup script successfully and executed its actual status function on disposable fixtures: atomic replacement of an existing file, preserved journal fields and monotonic progress passed. The complete guided setup has not been run end to end against a fresh Windows installation; its native shell/shortcut integrations still need that release check.

The final wheel was built without runtime dependencies, installed into an isolated local folder, and checked with the CLI help command. Its packaged dashboard and Windows activation script are present. The loopback dashboard served its measured status with no-store and CSP headers; an unqualified status route returned 404.

An earlier 1,000-file synthetic run on this machine took 4.691 seconds for cold verification/copy and 0.170 seconds with the existing verification journal. These numbers describe that fixture, not the performance of a multi-million-file migration.

GitHub CI runs on Windows and Linux with Python 3.11 and 3.13. See the [hosted fixture results](https://github.com/quorraa/ai-storage-mover/actions/workflows/test.yml) for each published revision. The source is published at [quorraa/ai-storage-mover](https://github.com/quorraa/ai-storage-mover).
