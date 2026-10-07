"""Launch-scoped temp settings; system TEMP and MSIX directories stay untouched."""
import os
from pathlib import Path
import subprocess
from .model import MigrationError, atomic_json, read_json, validate_runtime


def settings(storage):
    base = Path(storage).absolute()
    locations = {
        "CODEX_HOME": base / "Profiles" / "codex",
        "CLAUDE_CONFIG_DIR": base / "Profiles" / "claude",
        "CLAUDE_CODE_TMPDIR": base / "Temp" / "claude",
        "TEMP": base / "Temp" / "tools",
        "TMP": base / "Temp" / "tools",
        "TMPDIR": base / "Temp" / "tools",
        "UV_CACHE_DIR": base / "Cache" / "uv" / "cache",
        "UV_PYTHON_INSTALL_DIR": base / "Toolchains" / "uv" / "python",
        "UV_TOOL_DIR": base / "Toolchains" / "uv" / "tools",
        "UV_TOOL_BIN_DIR": base / "Toolchains" / "uv" / "bin",
        "UV_PYTHON_BIN_DIR": base / "Toolchains" / "uv" / "bin",
        "PIP_CACHE_DIR": base / "Cache" / "pip" / "cache",
        "npm_config_cache": base / "Cache" / "npm-cache",
        "npm_config_prefix": base / "Toolchains" / "npm-global",
        "PYTHONPYCACHEPREFIX": base / "Cache" / "python-bytecode",
    }
    return dict(schema=1, storage_root=str(base), environment={k: str(v) for k, v in locations.items()},
                note="Already-running apps do not inherit these settings. Windows may keep private package/sandbox temp on the system drive.")


def launch(runtime, command):
    validate_runtime(runtime)
    if runtime.get("schema") != 1 or not command:
        raise MigrationError("Invalid runtime or missing command")
    env = os.environ.copy()
    for key, value in runtime["environment"].items():
        if not isinstance(key, str) or not key.replace("_", "").isalnum() or not isinstance(value, str):
            raise MigrationError("Invalid environment entry")
        path = Path(value)
        if not path.is_absolute():
            raise MigrationError("Storage environment paths must be absolute")
        path.mkdir(parents=True, exist_ok=True)
        env[key] = value
    # No shell interpolation; caller supplies an argument vector.
    return subprocess.call(command, env=env)
