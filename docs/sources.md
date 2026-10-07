# Supported storage controls

- [Claude Code environment variables](https://code.claude.com/docs/en/env-vars): `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_TMPDIR`, settings `env`, and inheritance behavior.
- [uv storage](https://docs.astral.sh/uv/reference/storage/): Windows temp precedence, cache location, Python/tool installation overrides, and moved-environment limitations.
- [uv caching](https://docs.astral.sh/uv/concepts/cache/): `UV_CACHE_DIR` and placing the cache on the same filesystem as the environment.
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/): shell environment overrides and MCP server environment controls.
- [Windows IApplicationActivationManager](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-iapplicationactivationmanager): supported activation of registered applications.
- [Windows Robocopy](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/robocopy): parallel copying, exclusion of junctions, link handling and return codes. Source-removing switches are not used.
- [PyInstaller](https://pyinstaller.org/en/stable/usage.html): the desktop download bundles the Python runtime and UI dependencies in a portable folder with a windowed launcher.
- [pywebview API](https://pywebview.flowrl.com/api/): native folder dialogs, the explicit Python bridge, local HTML and WebView2 rendering.
- [Microsoft Edge WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/): the Windows rendering runtime and its Evergreen installer.
- [Microsoft .NET remote assembly loading](https://learn.microsoft.com/en-us/dotnet/framework/configure-apps/file-schema/runtime/loadfromremotesources-element): the portable launcher includes a process-scoped configuration so managed dependencies can load with Windows download flags retained.
- [Inter font](https://github.com/rsms/inter): bundled Inter Variable under the SIL Open Font License; its license is shipped with the font.

An upstream [Claude MSIX launch issue](https://github.com/anthropics/claude-code/issues/68070) records the same untrusted-mount error on direct executable launch. Reports are evidence of a vendor-specific failure mode, not proof that every such error has the same cause. This tool uses package activation and preserves Windows security settings.

Codex desktop's existing explicit-profile override was checked against the installed Windows 26.930 bootstrap source: it reads `CODEX_ELECTRON_USER_DATA_PATH` before its default app-data path. This is installed-version evidence, not a claim of a public stable API. Fixtures verify discovery and selected-path mapping; real signed-in profiles need separate app verification.
