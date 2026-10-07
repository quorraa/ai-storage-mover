"""Plans are explicit path allowlists, never a global drive-letter replacement."""
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import uuid


class MigrationError(RuntimeError):
    pass


CLEANUP_PHRASE = 'I UNDERSTAND MY OLD PROJECTS WILL BE DELETED AND UNRECOVERABLE'


def linked(path):
    if not os.path.lexists(path):
        return False
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def inside(path, parent):
    path, parent = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(parent))
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:
        return False


def protected(path):
    # Inspect Windows syntax even in cross-platform tests.
    parts = [p.casefold() for p in PureWindowsPath(str(path)).parts]
    return ("windowsapps" in parts or "modifiablewindowsapps" in parts
            or (parts and parts[-1] == 'appdata')
            or (len(parts) >= 2 and parts[-2] == 'appdata' and parts[-1] in ('local', 'roaming'))
            or (len(parts) > 1 and parts[1] == "windows")
            or any(parts[i:i + 3] == ["appdata", "local", "packages"] for i in range(len(parts)))
            or any(parts[i] == 'appdata' and parts[i + 1] in ('local', 'roaming')
                   and parts[i + 2] in ('codex', 'claude', 'chatgpt') for i in range(len(parts) - 2)))


def assert_movable(path):
    """Check logical paths BEFORE resolving junctions, including broad parent selections."""
    path = Path(os.path.abspath(path))
    if protected(path):
        raise MigrationError(f'Desktop profiles and Windows-managed storage stay in place: {path}. Use Repair Codex for an older profile migration.')
    # Fixed-depth probes, never a drive-wide crawl. Covers another user's profile too.
    for relative in ('AppData', 'Local/Packages', 'Packages', 'WindowsApps',
                     'Local/Codex', 'Local/Claude', 'Local/ChatGPT',
                     'Roaming/Codex', 'Roaming/Claude', 'Roaming/ChatGPT'):
        child = path / relative
        if os.path.lexists(child):
            raise MigrationError(f'This folder includes desktop or Windows-managed data: {child}. Select individual project or tool folders.')
    home = Path.home()
    local = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
    roaming = Path(os.environ.get('APPDATA', home / 'AppData' / 'Roaming'))
    reserved = [base / name for base in (local, roaming) for name in ('Codex', 'Claude', 'ChatGPT')]
    reserved += [local / 'Packages', local / 'Temp', Path(os.environ.get('WINDIR', 'C:/Windows'))]
    override = os.environ.get('CODEX_ELECTRON_USER_DATA_PATH')
    if override:
        reserved.append(Path(override))
    for blocked in reserved:
        # Preserve the logical alias AND its current physical target.
        for candidate in (blocked.absolute(), blocked.resolve()):
            if inside(path, candidate) or inside(candidate, path):
                raise MigrationError(f'This selection overlaps protected desktop/system storage: {blocked}. Select individual project or tool folders.')
    return path


def validate_runtime(runtime):
    if any(key.upper() == 'CODEX_ELECTRON_USER_DATA_PATH' for key in runtime.get('environment', {})):
        raise MigrationError('Desktop profile relocation is no longer supported. Remove CODEX_ELECTRON_USER_DATA_PATH from this saved setup; use Repair Codex to check an older migration.')
    return runtime


def physical_parents(path):
    for parent in Path(path).parents:
        if linked(parent):
            raise MigrationError(f"Linked ancestor requires a physical canonical path: {parent}")


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate(plan):
    if plan.get("schema") != 1 or not re.fullmatch(r"[a-f0-9]{32}", plan.get("id", "")):
        raise MigrationError("Unknown plan schema or invalid run ID")
    if plan.get("verification") not in ("hash", "metadata"):
        raise MigrationError("Choose hash or metadata verification")
    if plan.get('transfer', 'auto') not in ('auto', 'native', 'portable'):
        raise MigrationError('Unknown transfer method')
    if not 1 <= plan.get("workers", 0) <= 16 or plan.get("reserve_bytes", -1) < 0:
        raise MigrationError("Invalid workers or free-space reserve")
    if not plan.get("roots"):
        raise MigrationError("Plan has no roots")
    paths = []
    ids = set()
    for entry in plan["roots"]:
        if entry.get('provider') in ('codex-desktop', 'claude-desktop', 'chatgpt-desktop'):
            raise MigrationError('Desktop profiles stay in place. Use Repair Codex for an older migration.')
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", entry.get("id", "")) or entry["id"] in ids:
            raise MigrationError("Root IDs must be unique simple identifiers")
        ids.add(entry["id"])
        for field in ("source", "destination"):
            path = Path(entry[field])
            if not path.is_absolute() or path == Path(path.anchor) or protected(path):
                raise MigrationError(f"Protected, relative, or volume-root path: {path}")
            assert_movable(path)
            physical_parents(path)
            paths.append(str(path))
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if inside(a, b) or inside(b, a):
                raise MigrationError(f"Migration roots overlap: {a} and {b}")
    run = Path(plan["run_dir"])
    if not run.is_absolute() or protected(run):
        raise MigrationError("Run directory must be an absolute non-system path")
    physical_parents(run)
    if any(inside(run, p) or inside(p, run) for p in paths):
        raise MigrationError("Journal cannot be inside a migration root")
    return plan


def make_plan(roots, storage, *, verification="hash", workers=4, reserve_bytes=2 * 1024**3):
    run_id = uuid.uuid4().hex
    plan = dict(schema=1, id=run_id, verification=verification, workers=workers,
                reserve_bytes=reserve_bytes, run_dir=str(Path(storage).absolute() / ".migrations" / run_id),
                roots=[dict(id=f"root-{i:03d}", source=str(Path(a).absolute()),
                            destination=str(Path(b).absolute()), category=category)
                       for i, (a, b, category) in enumerate(roots)])
    return validate(plan)


def discover(storage, projects=(), profiles=()):
    storage, home = Path(storage).absolute(), Path.home()
    roots = [(p, storage / "Projects" / Path(p).name, "project") for p in projects]
    presets = {
        "codex": [(home / ".codex", storage / "Profiles" / "codex", "profile")],
        "claude": [(home / ".claude", storage / "Profiles" / "claude", "profile"),
                   (home / ".claude.json", storage / "Profiles" / "claude-legacy" / ".claude.json", "profile")],
        "shared": [(home / ".agents", storage / "Profiles" / "shared-agents", "profile")],
    }
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        presets["caches"] = [(local / name, storage / "Cache" / name, "cache")
                              for name in ("uv", "pip", "npm-cache")]
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
        presets["caches"] = [(cache / name, storage / "Cache" / name, "cache")
                              for name in ("uv", "pip")]
    for profile in profiles:
        roots.extend((a, b, c) for a, b, c in presets[profile] if a.exists() and not linked(a))
    return roots
