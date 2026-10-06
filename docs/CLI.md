# Advanced CLI and developer guide

[![Fixture tests](https://github.com/quorraa/ai-storage-mover/actions/workflows/test.yml/badge.svg)](https://github.com/quorraa/ai-storage-mover/actions/workflows/test.yml)

Keep desktop software installed and move the projects, profiles, package caches and build temp it uses. Windows first, with a standard-library Python CLI, an independent local dashboard, and explicit JSON path plans. Project names and drive letters are inputs.

This is an initial release. It is not a universal Windows app relocator. WindowsApps, Windows-managed `AppData/Local/Packages`, and the Windows directory are excluded. Installed desktop software stays registered in its original location. Portable tool binaries can be included as explicit roots if their updater supports it.

Requires Python 3.11+; Windows directory links use junctions. File links require Developer Mode or administrator rights. The core also works with ordinary directories and symlinks on Linux/macOS. No Python runtime dependencies.

```powershell
git clone https://github.com/quorraa/ai-storage-mover.git
cd ai-storage-mover
python -m pip install .
ai-storage-mover plan --storage-root D:\AI --project "C:\Projects\My Agent" --profile codex --profile claude --profile caches --output move.local.json
ai-storage-mover inspect --plan move.local.json
```

Review the plan before applying it. To select other data or a portable tool directory, repeat `--root "SOURCE=DESTINATION"`. Existing destination-only files are preserved. Conflicting destination files are archived, not overwritten without a backup. A root cannot contain another selected root or the operation journal.

For development without installation, set `PYTHONPATH` to the repository's `src` directory and use `python -m ai_storage_mover` instead of `ai-storage-mover`.

To develop the desktop interface from source, install the `desktop` extra (`python -m pip install -e ".[desktop]"`) and launch `ai-storage-mover-gui`. The Windows download already includes these dependencies. Its offline interface uses WebView2; it does not require a local web server.

## Windows setup

After reviewing the plan, quit the AI apps and any terminals writing to the selected folders. Keep the setup terminal outside those source folders. Open `dashboard` in another terminal, then run:

```powershell
ai-storage-mover setup --plan move.local.json --storage-root D:\AI --apps-closed
# Optional: choose the default folder for future projects.
# Add --projects D:\Projects
```

This command checks running AI apps before scanning, performs one resumable sync/cutover, repairs provider project/session/transcript references and Claude's saved browser workspace selectors, merges temp/cache values into tool and MCP configuration, saves user cache/profile defaults, and adds global instructions for new projects. It updates selected-path shortcuts, Explorer pins and open folder views, and creates package-safe desktop launchers and an AI terminal shortcut under `D:\AI\Launchers`. Profile switches require a matching selected profile root or an existing profile setting on the chosen storage drive; an unselected existing profile is never replaced with an empty one.

The optional Claude browser adapter installs `classic-level@3.0.0` with npm under the storage drive when a Claude desktop store is present. That step requires Node.js, npm and network access; installation scripts are disabled. The rest of the tool has no runtime dependencies. Authentication values are not edited and no browser debugging port is opened. Windows-managed package directories stay in place.

If the files have already moved, use `setup --configure-only` with the same plan and storage arguments. This repairs configuration and launchers without enumerating or copying project files again. A failed setup retains backups and reports the actual failed step. Reopen apps from the new launchers and reopen old terminal tabs before checking paths. Check the apps before explicitly running `retire` with the plan's exact ID.

`configure` provides the provider/configuration portion on other operating systems, with explicit `--runtime`, profile directories and `--apps-closed`. It does not persist Windows environment variables or edit shortcuts.

## Migration

Open the dashboard in one terminal. Use a second terminal whose working directory is outside every source root.

```powershell
ai-storage-mover dashboard --plan move.local.json
ai-storage-mover stage --plan move.local.json
# Close the apps, shells, Explorer tabs and services writing to selected roots.
ai-storage-mover apply --plan move.local.json --apps-closed
ai-storage-mover references --plan move.local.json --codex-home D:\AI\Profiles\codex --file D:\AI\Profiles\codex\config.toml
ai-storage-mover references --plan move.local.json --claude-home D:\AI\Profiles\claude --claude-desktop-home "C:\Users\YOUR_NAME\AppData\Local\Packages\CLAUDE_PACKAGE\LocalCache\Roaming\Claude"
ai-storage-mover runtime --storage-root D:\AI --output runtime.local.json
ai-storage-mover run --runtime runtime.local.json -- codex
ai-storage-mover run --runtime runtime.local.json -- claude
# Test your apps, then use the exact ID printed in the plan:
ai-storage-mover retire --plan move.local.json --confirm RUN_ID_FROM_PLAN --acknowledge "I UNDERSTAND MY OLD PROJECTS WILL BE DELETED AND UNRECOVERABLE"
```

`--apps-closed` is a declaration that writers are closed, not a command that terminates them. Atomic same-parent rename probes catch directory locks before an expensive scan. If a writer recreates a source during cutover, the tool stops and preserves both trees. Processes are never force-killed. Cutover writes intent before each rename and can resume after a crash by rerunning `apply --apps-closed`. After interrupted cleanup, rerun `retire` with the original ID.

`rollback --apps-closed` restores the pre-cutover source snapshots while retaining the destination, including any later writes there. It does not merge later destination writes into the original snapshot. Rollback is refused after retirement starts.

## Verification and speed

The default policy uses SHA-256 for existing files and verifies new copies by reading them back. A SQLite journal reuses prior content verification only when both source and destination file identities, sizes and modification times still match. File work uses a bounded pool (`--workers 1` through `16`, default `4`); the tool never creates millions of queued jobs. Journal writes are batched and live status updates are throttled. Existing unchanged files are not recopied.

For an already trusted clone, `plan --verification metadata` explicitly reuses matching size and modification time without hashing those existing files. With native Windows copying, new tree copies also use metadata checks in this mode; all old copies must pass SHA-256 content verification before tool-managed retirement. Portable changed/new copies receive SHA-256 verification during transfer. This is faster but cannot detect same-size corruption with an unchanged timestamp. The receipt records the chosen policy.

Cleanup is iterative, tied to exact backup paths and file identities, and never follows junctions or symlinks. Unexpected or changed backup entries, disappeared destination entries, changed destination volume identity, or a changed plan stop cleanup. Source snapshots are retained until you explicitly request retirement. File enumeration and NTFS deletion still cost time; there is no advertised speed multiplier.

The dashboard shows measured entry counts, copied/reused counts and monotonic phase progress. It says **Counting** while the denominator is unknown. Cleanup uses the manifest's fixed entry total. It never loops an animation that resembles a percentage. **DONE** means verified source backups were cleared, not merely that copies exist.

## Installed software on C:, storage elsewhere

`runtime` generates launch-scoped `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_TMPDIR`, `TEMP`, `TMP`, `TMPDIR`, `UV_CACHE_DIR`, `PIP_CACHE_DIR`, `npm_config_cache`, `npm_config_prefix`, `PYTHONPYCACHEPREFIX`, `UV_PYTHON_INSTALL_DIR`, `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR` and `UV_PYTHON_BIN_DIR`. `run` launches an argument vector without shell interpolation. These settings are inherited by normal child tools; the system-wide Windows temp settings are unchanged.

On Windows, activate packaged apps through Windows's package API, not by launching their `WindowsApps` executable directly:

```powershell
ai-storage-mover package --name Claude --app-id Claude --runtime runtime.local.json
ai-storage-mover package --name OpenAI.Codex --app-id App --runtime runtime.local.json
```

The included `Activate-Package.ps1` resolves the registered package and validates its application ID against its manifest. It does not change trust policy, registration, or installer ACLs. A shortcut can point to this PowerShell script with `-PackageName`, `-ApplicationId`, and `-RuntimePath`.

Quit an already-running desktop app before testing new launch environment values. Package activation may reuse its existing process. Windows can override temp inside a package or sandbox. This tool does **not** promise zero writes on the system drive and does not redirect private `Packages` or sandbox directories with junctions.

Projects and `.venv` directories should reside on the storage drive alongside the uv cache. Moving an existing virtual environment can leave absolute interpreter/shebang paths; rebuild that environment from its lockfile where necessary. This tool preserves existing environment files; it does not silently uninstall or regenerate dependencies. uv-managed Python/tool installation locations can be added as explicit roots and custom runtime variables after checking existing environments' interpreter paths.

`references` accepts explicitly selected files and known Codex/Claude path records. Codex includes directory columns, cached import directories and file tabs. Claude includes project preferences, worktree indexes and desktop session working directories. The desktop adapter edits metadata inside the package's existing data directory without relocating that directory. It recognizes ordinary Windows paths, `/` paths, and `\\?\` paths, uses boundary-aware longest-prefix mapping, creates backups, checks for concurrent edits and validates TOML/JSON. It preserves chat messages, prompt snapshots and Git history. Codex schema adapters fail closed if the installed version's path columns differ. Quit desktop apps before applying reference changes, then reopen them so cached paths are refreshed. Existing terminal sessions retain their working directories until reopened.

## Validation and sharing

Claude desktop also keeps workspace selectors and file-view paths in its browser state. If a saved workspace still opens on the old drive after `references` and a restart, quit Claude completely and use the optional offline adapter from the repository root:

```powershell
npm install --prefix tools/browser-state --ignore-scripts --no-audit --no-fund classic-level@3.0.0
node tools/repair_claude_browser_state.cjs move.local.json "C:\Users\YOUR_NAME\AppData\Local\Packages\CLAUDE_PACKAGE\LocalCache\Roaming\Claude\Local Storage\leveldb"
```

This optional adapter requires Node.js. It backs up the selected store, identifies a whitelist of Claude workspace/UI keys on a separate copy, checks for concurrent changes, obtains the native database lock, writes one atomic batch and verifies the values. Other keys, including authentication data, are retained. It edits the existing store in place and does not relocate Windows-managed package storage or expose a browser debugging endpoint. Backups are private migration evidence; keep them out of GitHub.

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
# Optional native browser-state fixtures after installing classic-level above:
node tools\test_browser_state.cjs
# Windows PowerShell 5 status/journal integration fixtures:
powershell -NoProfile -File tools\test_windows_setup.ps1
python tools\benchmark.py --files 1000
```

The test suite uses disposable fixtures, including equal-metadata corruption, interrupted cutover/cleanup, source recreation, modified backups, external links and runtime temp inheritance. The synthetic benchmark reports this machine's cold and journal-reused verification times; it does not estimate a multi-million-file production migration.

Plans, runtime settings, journals and credentials are local/private artifacts. The repository ignores `*.local.json`, `.runs`, databases and benchmark outputs. Do not publish your profiles or migration evidence. GitHub CI runs the fixture suite on Windows and Linux. See [limitations](limitations.md) and [sources](sources.md).
