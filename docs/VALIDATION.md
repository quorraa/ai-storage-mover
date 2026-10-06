# Local validation — 6 October 2026

Windows with Python 3.14: **31 fixture tests passed** in 23.485 seconds. Fixtures cover verified cutover, restart after interruptions, protected deletion, concurrent writers and space reservations, equal-metadata corruption, scoped temp writes, and Codex/Claude directory records while preserving prompts and history. Configuration fixtures preserve MCP secrets, HTTP servers, existing global instructions and legacy preferences; a second setup is idempotent.

Native LevelDB fixtures passed for live-lock refusal, unchanged authentication bytes, Unicode destinations, opaque working-directory identifiers, component boundaries, idempotent repairs and invalid-store refusal. Windows PowerShell 5 parsed the setup script successfully. The complete guided setup has not been run end to end against a fresh Windows installation; its native shell/shortcut integrations still need that release check.

The final wheel was built without runtime dependencies, installed into an isolated local folder, and checked with the CLI help command. Its packaged dashboard and Windows activation script are present. The loopback dashboard served its measured status with no-store and CSP headers; an unqualified status route returned 404.

An earlier 1,000-file synthetic run on this machine took 4.691 seconds for cold verification/copy and 0.170 seconds with the existing verification journal. These numbers describe that fixture, not the performance of a multi-million-file migration.

GitHub CI is configured for Windows and Linux with Python 3.11 and 3.13. Those hosted jobs have not been run. The tool has not been published.
