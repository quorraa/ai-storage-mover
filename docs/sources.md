# Supported storage controls

- [Claude Code environment variables](https://code.claude.com/docs/en/env-vars): `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_TMPDIR`, settings `env`, and inheritance behavior.
- [uv storage](https://docs.astral.sh/uv/reference/storage/): Windows temp precedence, cache location, Python/tool installation overrides, and moved-environment limitations.
- [uv caching](https://docs.astral.sh/uv/concepts/cache/): `UV_CACHE_DIR` and placing the cache on the same filesystem as the environment.
- [Codex configuration reference](https://developers.openai.com/codex/config-reference/): shell environment overrides and MCP server environment controls.
- [Windows IApplicationActivationManager](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-iapplicationactivationmanager): supported activation of registered applications.
- [Windows Robocopy](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/robocopy): parallel copying, exclusion of junctions, link handling and return codes. Source-removing switches are not used.
- [PyInstaller](https://pyinstaller.org/en/stable/usage.html): the desktop download bundles the Python/Tk runtime in a portable folder with a windowed launcher.

An upstream [Claude MSIX launch issue](https://github.com/anthropics/claude-code/issues/68070) records the same untrusted-mount error on direct executable launch. Reports are evidence of a vendor-specific failure mode, not proof that every such error has the same cause. This tool uses package activation and preserves Windows security settings.
