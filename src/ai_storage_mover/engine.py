"""Bounded parallel copy, persistent verification cache, and guarded retirement."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
from threading import Lock
import time
import uuid

from .model import (CLEANUP_PHRASE, MigrationError, atomic_json, fingerprint, inside, linked,
                    physical_parents, read_json, validate)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sig(path):
    info = os.lstat(path)
    return [info.st_ino, info.st_size, info.st_mtime_ns]


def sha(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def volume(path):
    parent = Path(path).absolute()
    while not parent.exists():
        parent = parent.parent
    if os.name != "nt":
        return str(parent.stat().st_dev)
    import ctypes
    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(str(parent.anchor), buffer, len(buffer)):
        raise ctypes.WinError()
    return buffer.value


def link_root(source, destination):
    if os.name == "nt" and Path(destination).is_dir():
        # Junctions need no Developer Mode. Only a new pointer is created.
        quote = lambda s: "'" + str(s).replace("'", "''") + "'"
        code = "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path " + quote(source) + " -Target " + quote(destination) + " | Out-Null"
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
                                capture_output=True, text=True)
        if result.returncode:
            raise MigrationError(result.stderr.strip())
    else:
        os.symlink(str(destination), str(source), target_is_directory=Path(destination).is_dir())


def correct_link(source, destination):
    return linked(source) and os.path.normcase(os.path.realpath(source)) == os.path.normcase(os.path.realpath(destination))


def unlink_pointer(path):
    if not linked(path):
        raise MigrationError("Refusing to remove a physical source root")
    if os.name == "nt" and os.lstat(path).st_file_attributes & 0x10:
        os.rmdir(path)
    else:
        os.unlink(path)


@contextmanager
def run_lock(run):
    run.mkdir(parents=True, exist_ok=True)
    with (run / "writer.lock").open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise MigrationError("Another operation owns this migration") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class Engine:
    def __init__(self, plan, *, cancelled=None):
        self.plan = validate(plan)
        self.cancelled = cancelled or (lambda: False)
        self.run = Path(plan["run_dir"])
        self.run.mkdir(parents=True, exist_ok=True)
        if linked(self.run):
            raise MigrationError("Linked journal directory")
        self.plan_hash = fingerprint(plan)
        state_path = self.run / "state.json"
        self.state = read_json(state_path) if state_path.exists() else dict(plan_hash=self.plan_hash, roots={}, percent=0)
        if self.state.get("plan_hash") != self.plan_hash:
            raise MigrationError("Plan changed since the journal was created; review the original plan")
        self.db = sqlite3.connect(self.run / "manifest.sqlite")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS files (root TEXT, relative TEXT, kind TEXT, source_sig TEXT, destination_sig TEXT, digest TEXT, generation TEXT, PRIMARY KEY(root,relative))")
        self.db.commit()
        self.last = 0
        self.space_lock = Lock()
        self.space_reserved = {}
        self.save()

    def close(self):
        self.db.close()

    def save(self):
        atomic_json(self.run / "state.json", self.state)

    def update(self, phase, *, done=0, total=None, detail="", percent=0, force=False, **extra):
        if phase != 'failed' and self.cancelled():
            detail = ('Stopped. Completed cleanup deletions cannot be undone; remaining old copies stay.'
                      if any(v.get('state') in ('retiring', 'retired') for v in self.state['roots'].values())
                      else 'Stopped. Original files are retained; reopen this migration to continue.')
            raise MigrationError(detail)
        self.state["percent"] = max(self.state.get("percent", 0), percent)
        if force or time.monotonic() - self.last >= 0.5:
            atomic_json(self.run / "status.json", dict(updated_utc=utc(), phase=phase, done=done, total=total,
                        detail=detail, percent=self.state["percent"], **extra))
            self.last = time.monotonic()

    def fail(self, exc):
        self.save()
        self.update("failed", detail=str(exc), force=True)

    def root_state(self, entry):
        return self.state["roots"].setdefault(entry["id"], {})

    def backup(self, entry):
        source = Path(entry["source"])
        result = source.with_name(source.name + ".ai-mover-backup-" + self.plan["id"])
        if result.parent != source.parent or protected_backup(result):
            raise MigrationError("Backup escaped its exact source parent")
        physical_parents(result)
        return result

    def check_volume(self, entry):
        destination = Path(entry["destination"])
        current = volume(destination)
        value = self.root_state(entry)
        if value.get("destination_volume", current) != current:
            raise MigrationError("Destination volume identity changed")
        value["destination_volume"] = current
        self.save()

    def probe(self, entry):
        source = Path(entry["source"])
        probe = source.with_name(source.name + ".ai-mover-probe-" + self.plan["id"])
        value = self.root_state(entry)
        if os.path.lexists(probe):
            if os.path.lexists(source) or value.get("probe_identity") != sig(probe)[0]:
                raise MigrationError("Unresolved rename probe; originals preserved")
            os.rename(probe, source)
        if linked(source) or not source.exists():
            raise MigrationError(f"Source must be physical before cutover: {source}")
        value["probe_identity"] = sig(source)[0]
        self.save()
        try:
            os.rename(source, probe)
            os.rename(probe, source)
        except OSError as exc:
            if os.path.lexists(probe) and not os.path.lexists(source):
                os.rename(probe, source)
            raise MigrationError(f"Folder is locked or cannot rename: {source}. Close apps, shells, Explorer tabs and background writers.") from exc

    def walk(self, entry, destination_metadata=False):
        source = Path(entry["source"])
        stack = [(source, ".", os.lstat(source), None)]
        while stack:
            path, relative, info, target_info = stack.pop()
            kind = kind_of(info)
            if kind == "unsupported":
                raise MigrationError(f"Unsupported file type: {path}")
            yield path, relative, kind, signature(info), target_info
            if kind == "d":
                targets = {}
                if destination_metadata:
                    directory = Path(entry['destination']) if relative == '.' else Path(entry['destination']) / relative
                    with os.scandir(directory) as existing:
                        for child in existing:
                            targets[child.name.casefold() if os.name == 'nt' else child.name] = child.stat(follow_symlinks=False)
                with os.scandir(path) as children:
                    for child in children:
                        if self.cancelled():
                            raise MigrationError('Stopped. Original files are retained.')
                        rel = child.name if relative == "." else relative + "/" + child.name
                        child_info = child.stat(follow_symlinks=False)
                        # Windows enumeration supplies this metadata already.
                        # Stream files instead of reopening or queuing the whole tree.
                        target_info = targets.get(child.name.casefold() if os.name == 'nt' else child.name, False) if destination_metadata else None
                        if kind_of(child_info) == 'd':
                            stack.append((Path(child.path), rel, child_info, target_info))
                        elif kind_of(child_info) == 'unsupported':
                            raise MigrationError(f'Unsupported file type: {child.path}')
                        else:
                            yield Path(child.path), rel, kind_of(child_info), signature(child_info, child.path), target_info

    def preserve(self, destination, entry, relative):
        target = self.run / "conflicts" / entry["id"] / ("__root__" if relative == "." else relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(target):
            target = target.with_name(target.name + "." + uuid.uuid4().hex)
        os.rename(destination, target)

    @contextmanager
    def copy_space(self, destination, size):
        # Include reservations from other workers before any new copy starts.
        # Keeping the full reservation until completion is conservative when
        # disk usage already includes bytes written by an in-flight copy.
        key = Path(destination).anchor.casefold() if os.name == 'nt' else str(Path(destination).parent.stat().st_dev)
        with self.space_lock:
            reserved = self.space_reserved.get(key, 0)
            if shutil.disk_usage(Path(destination).parent).free - reserved - size < self.plan['reserve_bytes']:
                raise MigrationError('Destination free-space reserve would be crossed')
            self.space_reserved[key] = reserved + size
        try:
            yield
        finally:
            with self.space_lock:
                self.space_reserved[key] -= size

    def copy_file(self, source, destination, before, entry, relative, cached, destination_info=None):
        exists = os.path.lexists(destination) if destination_info is None else destination_info is not False
        info = os.lstat(destination) if exists and destination_info is None else destination_info
        current = signature(info, destination) if exists else None
        source_hash = None
        if exists and kind_of(info) == 'f':
            if cached and cached[0] == before and cached[1] == current and cached[2]:
                return current, cached[2], "journal-reused", 0
            if self.plan["verification"] == "metadata" and before[1:] == current[1:]:
                return current, None, "metadata-reused", 0
            source_hash = sha(source)
            destination_hash = sha(destination)
            if sig(source) != before or sig(destination) != current:
                raise MigrationError("File changed while comparing; close writers and rerun")
            if source_hash == destination_hash:
                return current, source_hash, "hash-matched", 0
        if exists:
            self.preserve(destination, entry, relative)
        temp = destination.with_name(destination.name + ".ai-mover-copy-" + uuid.uuid4().hex)
        result = hashlib.sha256()
        with self.copy_space(destination, before[1]):
            with source.open("rb") as reader, temp.open("xb") as writer:
                while block := reader.read(8 * 1024 * 1024):
                    writer.write(block)
                    result.update(block)
                writer.flush()
                os.fsync(writer.fileno())
            if sig(source) != before:
                raise MigrationError("Source changed during copy; temporary file retained")
            if sha(temp) != result.hexdigest():
                raise MigrationError("Destination SHA-256 verification failed; temporary file retained")
            shutil.copystat(source, temp, follow_symlinks=False)
            os.replace(temp, destination)
        return sig(destination), result.hexdigest(), "copied", before[1]

    def stage(self):
        if any(v.get("state") in ("rename-intent", "linked", "retired") for v in self.state["roots"].values()):
            raise MigrationError("Cutover already began; use apply to resume, not stage")
        self.state.pop("verified", None)
        self.save()
        generation = uuid.uuid4().hex
        count = completed = copied = reused = copied_bytes = 0
        pending = {}

        def record(entry, relative, kind, source_sig, destination_sig, digest):
            self.db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)",
                            (entry["id"], relative, kind, dump(source_sig), dump(destination_sig), digest, generation))

        def collect(done):
            nonlocal completed, copied, reused, copied_bytes
            for future in done:
                entry, relative, source_sig = pending.pop(future)
                destination_sig, digest, action, size = future.result()
                record(entry, relative, "f", source_sig, destination_sig, digest)
                completed += 1
                native = entry['id'] in native_roots
                copied += action == "copied" or native
                reused += action != "copied" and not native
                copied_bytes += source_sig[1] if native else size
            if completed % 1000 == 0:
                self.db.commit()
            self.update("copying", done=completed, total=None, detail="Scanning and verifying; final total is still being counted",
                        percent=10, copied=copied, reused=reused, copied_bytes=copied_bytes)

        self.update("scanning", detail="Counting storage entries without following links", force=True)
        native_roots = set()
        if os.name == 'nt' and self.plan.get('transfer', 'auto') != 'portable':
            from .native import copy_new_tree
            for entry in self.plan['roots']:
                self.check_volume(entry)
                if copy_new_tree(entry, self.run, reserve=self.plan['reserve_bytes'],
                                 notify=self.update, cancelled=self.cancelled):
                    native_roots.add(entry['id'])
        with ThreadPoolExecutor(max_workers=self.plan["workers"]) as pool:
            for entry in self.plan["roots"]:
                self.check_volume(entry)
                source, destination = Path(entry["source"]), Path(entry["destination"])
                if linked(source) or linked(destination):
                    raise MigrationError("Stage needs physical source and destination roots")
                destination.parent.mkdir(parents=True, exist_ok=True)
                physical_parents(destination)
                for path, relative, kind, source_sig, target_info in self.walk(entry, destination_metadata=True):
                    count += 1
                    target = destination if relative == "." else destination / relative
                    cached = self.db.execute("SELECT source_sig,destination_sig,digest FROM files WHERE root=? AND relative=?",
                                             (entry["id"], relative)).fetchone()
                    cached = (load(cached[0]), load(cached[1]), cached[2]) if cached else None
                    if kind == "f":
                        # Metadata-matched files need no future, open/read or hash.
                        # Keep this common clone/native-copy path in the scan loop.
                        if self.plan['verification'] == 'metadata' and target_info not in (None, False) and kind_of(target_info) == 'f':
                            destination_sig = signature(target_info, target)
                            if source_sig[1:] == destination_sig[1:]:
                                record(entry, relative, kind, source_sig, destination_sig, None)
                                completed += 1
                                if entry['id'] in native_roots:
                                    copied += 1
                                    copied_bytes += source_sig[1]
                                else:
                                    reused += 1
                                if count % 1000 == 0:
                                    self.db.commit()
                                    self.update('scanning', done=completed, detail=f'Checking {entry["category"]}: {path.parent.name}',
                                                percent=10, copied=copied, reused=reused, copied_bytes=copied_bytes)
                                continue
                        future = pool.submit(self.copy_file, path, target, source_sig, entry, relative, cached, target_info)
                        pending[future] = (entry, relative, source_sig)
                        if len(pending) >= self.plan["workers"] * 2:
                            collect(wait(pending, return_when=FIRST_COMPLETED)[0])
                    elif kind == "d":
                        if os.path.lexists(target) and (linked(target) or not target.is_dir()):
                            self.preserve(target, entry, relative)
                        target.mkdir(parents=True, exist_ok=True)
                        physical_parents(target)
                        record(entry, relative, kind, source_sig, sig(target), None)
                        completed += 1
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        desired = os.readlink(path)
                        if os.path.lexists(target) and not (linked(target) and os.readlink(target) == desired):
                            self.preserve(target, entry, relative)
                        if not os.path.lexists(target):
                            os.symlink(desired, target, target_is_directory=path.is_dir())
                        record(entry, relative, kind, source_sig, sig(target), desired)
                        completed += 1
                    if count % 1000 == 0:
                        self.db.commit()
                        self.update("scanning", done=completed, total=None, detail=f"{count:,} entries discovered; {copied:,} copied",
                                    percent=10, copied=copied, reused=reused, copied_bytes=copied_bytes)
            while pending:
                collect(wait(pending, return_when=FIRST_COMPLETED)[0])
        self.db.execute("DELETE FROM files WHERE generation != ?", (generation,))
        self.db.commit()
        self.state["verified"] = dict(plan_hash=self.plan_hash, entries=count, copied=copied,
                                      reused=reused, copied_bytes=copied_bytes, utc=utc(), policy=self.plan["verification"])
        self.save()
        self.update("staged", done=count, total=count, detail="Copies verified. Sources unchanged. Close writers before apply.",
                    percent=60, force=True, copied=copied, reused=reused, copied_bytes=copied_bytes)
        return self.state["verified"]

    def check_manifest(self, entry, source_root, *, allow_missing=False, destination_present=False):
        # Walk once, reject destination-only assumptions and new source files.
        observed = 0
        temporary = dict(entry, source=str(source_root))
        for path, relative, kind, source_sig, _ in self.walk(temporary):
            row = self.db.execute("SELECT kind,source_sig,digest FROM files WHERE root=? AND relative=?", (entry["id"], relative)).fetchone()
            if not row or row[0] != kind or (kind == "f" and load(row[1]) != source_sig) or (kind == "l" and row[2] != os.readlink(path)):
                raise MigrationError(f"Backup/source changed since verification: {entry['id']} / {relative}")
            observed += 1
            if destination_present:
                target = Path(entry["destination"]) if relative == "." else Path(entry["destination"]) / relative
                physical_parents(target)
                if not os.path.lexists(target):
                    raise MigrationError("Destination entry disappeared; backup retained")
                if kind == "f" and (linked(target) or not target.is_file()):
                    raise MigrationError("Destination type changed; backup retained")
                if kind == 'd' and (linked(target) or not target.is_dir()):
                    raise MigrationError('Destination directory changed; backup retained')
        expected = self.db.execute("SELECT count(*) FROM files WHERE root=?", (entry["id"],)).fetchone()[0]
        if not allow_missing and observed != expected:
            raise MigrationError("Source entries disappeared since verification")

    def apply(self, *, apps_closed=False):
        if not apps_closed:
            raise MigrationError("Close applications and background writers, then pass --apps-closed")
        resuming = any(v.get("state") in ("rename-intent", "linked", "retired") for v in self.state["roots"].values())
        if not resuming:
            for entry in self.plan["roots"]:
                self.probe(entry)
            self.stage()
        if self.state.get("verified", {}).get("plan_hash") != self.plan_hash:
            raise MigrationError("No complete verification receipt for this plan")
        for index, entry in enumerate(self.plan["roots"]):
            self.check_volume(entry)
            value = self.root_state(entry)
            source, destination, backup = Path(entry["source"]), Path(entry["destination"]), self.backup(entry)
            if value.get("state") in ("linked", "retired"):
                if not correct_link(source, destination):
                    raise MigrationError("Committed compatibility pointer changed")
                continue
            if os.path.lexists(backup):
                if linked(backup) or sig(backup)[0] != value.get("backup_identity"):
                    raise MigrationError("Unrecognized backup; refusing to touch it")
                self.check_manifest(entry, backup)
            else:
                self.check_manifest(entry, source)
                value.update(state="rename-intent", backup_identity=sig(source)[0])
                self.save()  # Intent precedes mutation; a crash can resume.
                os.rename(source, backup)  # Never a recursive move fallback.
            if os.path.lexists(source):
                if not correct_link(source, destination):
                    raise MigrationError("A writer recreated the source; both copies preserved")
            else:
                try:
                    link_root(source, destination)
                except Exception:
                    if not os.path.lexists(source):
                        os.rename(backup, source)
                        value["state"] = "verified"
                        self.save()
                    raise
            if not correct_link(source, destination):
                raise MigrationError("Compatibility pointer did not resolve to the destination")
            value["state"] = "linked"
            self.save()
            self.update("cutover", done=index + 1, total=len(self.plan["roots"]), detail="Pointers switched; verified backups retained",
                        percent=60 + 30 * (index + 1) / len(self.plan["roots"]), force=True)
        self.state["cutover_complete"] = True
        self.save()
        self.update("ready-for-cleanup", done=len(self.plan["roots"]), total=len(self.plan["roots"]), percent=90,
                    detail="Storage switched. Test apps through their launchers, then explicitly retire verified backups.", force=True)

    def verify_cleanup_contents(self):
        """Fast setup never authorizes deletion by size/date alone.

        Validate every retained root before deleting ANY root. Re-read contents
        even when metadata matches: disk corruption can preserve timestamps.
        A changed/later destination is retained together with its old copy.
        """
        checked = 0
        total = self.db.execute("SELECT count(*) FROM files WHERE kind='f'").fetchone()[0]
        self.update('cleanup-verification', done=0, total=total, detail='Checking contents before permanent deletion', force=True)
        with ThreadPoolExecutor(max_workers=self.plan['workers']) as pool:
            pending = {}

            def compare(source, target, before, current):
                a, b = sha(source), sha(target)
                if sig(source) != before or sig(target) != current or a != b:
                    raise MigrationError(f'Copies differ or changed: {source}. Old copies retained; reconcile them before cleanup.')
                return a

            def collect(finished):
                nonlocal checked
                for future in finished:
                    entry, relative, before, current = pending.pop(future)
                    digest = future.result()
                    self.db.execute('UPDATE files SET digest=?,destination_sig=? WHERE root=? AND relative=?',
                                    (digest, dump(current), entry['id'], relative))
                    checked += 1
                self.db.commit()
                self.update('cleanup-verification', done=checked, total=total,
                            detail='Checking contents before permanent deletion', percent=40 * checked / max(total, 1))

            for entry in self.plan['roots']:
                self.check_volume(entry)
                value, backup = self.root_state(entry), self.backup(entry)
                if not correct_link(entry['source'], entry['destination']):
                    raise MigrationError('Source pointer changed; no retirement permitted')
                if not backup.exists():
                    if value.get('state') not in ('retiring', 'retired'):
                        raise MigrationError('Original backup is missing; cleanup refused')
                    continue
                if linked(backup) or sig(backup)[0] != value.get('backup_identity'):
                    raise MigrationError('Backup identity changed')
                self.check_manifest(entry, backup, allow_missing=value.get('state') == 'retiring', destination_present=True)
                rows = self.db.execute('SELECT relative,kind,source_sig,destination_sig,digest FROM files WHERE root=?', (entry['id'],))
                for relative, kind, old_source, old_destination, digest in rows:
                    source = backup if relative == '.' else backup / relative
                    target = Path(entry['destination']) if relative == '.' else Path(entry['destination']) / relative
                    if not os.path.lexists(source):
                        continue
                    if kind == 'l':
                        if not linked(target) or os.readlink(source) != os.readlink(target):
                            raise MigrationError('Destination link changed; backup retained')
                    if kind != 'f':
                        continue
                    before, current = sig(source), sig(target)
                    if before != load(old_source):
                        raise MigrationError('Original file changed; backup retained')
                    future = pool.submit(compare, source, target, before, current)
                    pending[future] = (entry, relative, before, current)
                    if len(pending) >= self.plan['workers'] * 2:
                        collect(wait(pending, return_when=FIRST_COMPLETED)[0])
                # Finish this cursor before updating its journal in the next root.
            while pending:
                collect(wait(pending, return_when=FIRST_COMPLETED)[0])
        self.db.commit()

    def retire(self, confirm, *, acknowledgment=None):
        if acknowledgment != CLEANUP_PHRASE:
            raise MigrationError('Permanent cleanup requires the exact typed acknowledgment phrase')
        if confirm != self.plan["id"] or not self.state.get("cutover_complete"):
            raise MigrationError("Retirement needs complete cutover and the exact confirmation run ID")
        if self.state.get("verified", {}).get("plan_hash") != self.plan_hash:
            raise MigrationError("Missing complete verification receipt")
        # Cleanup is a separate, explicitly confirmed task with its own progress.
        self.state['percent'] = 0
        self.verify_cleanup_contents()
        total = self.state["verified"]["entries"]
        removed = self.state.get("removed", 0)
        for entry in self.plan["roots"]:
            self.check_volume(entry)
            value = self.root_state(entry)
            if not correct_link(entry["source"], entry["destination"]):
                raise MigrationError("Source pointer changed; no retirement permitted")
            backup = self.backup(entry)
            if backup.exists():
                if linked(backup) or sig(backup)[0] != value.get("backup_identity"):
                    raise MigrationError("Backup identity changed")
                self.check_manifest(entry, backup, allow_missing=value.get("state") == "retiring", destination_present=True)
                value["state"] = "retiring"
                self.save()
                rows = self.db.execute("SELECT relative,kind,source_sig,destination_sig FROM files WHERE root=? ORDER BY length(relative) DESC", (entry["id"],))
                for relative, kind, original_sig, verified_sig in rows:
                    target = backup if relative == "." else backup / relative
                    if not inside(target, backup):
                        raise MigrationError("Manifest path escaped backup")
                    if not os.path.lexists(target):
                        continue
                    physical_parents(target)
                    if kind == "l":
                        unlink_pointer(target)
                    elif kind == "d":
                        if linked(target):
                            raise MigrationError("Directory replaced by a link")
                        os.rmdir(target)
                    else:
                        if linked(target):
                            raise MigrationError("File replaced by a link")
                        destination = Path(entry['destination']) if relative == '.' else Path(entry['destination']) / relative
                        physical_parents(destination)
                        if linked(destination) or sig(target) != load(original_sig) or sig(destination) != load(verified_sig):
                            raise MigrationError('A file changed during cleanup; remaining old copies retained')
                        if getattr(os.lstat(target), "st_file_attributes", 0) & 1:
                            os.chmod(target, stat.S_IWRITE)
                        os.unlink(target)
                    removed += 1
                    self.state["removed"] = removed
                    self.update("cleanup", done=removed, total=total, detail=f"Clearing verified backup: {entry['id']}",
                                percent=40 + 60 * min(removed, total) / max(total, 1))
                    if removed % 1000 == 0:
                        self.save()
            value["state"] = "retired"
            self.save()
        self.state["retired"] = True
        self.save()
        self.update("done", done=total, total=total, percent=100, detail="Storage moved and exact verified backups cleared. Desktop installers remain in place.", force=True)

    def rollback(self, *, apps_closed=False):
        if not apps_closed or any(v.get('state') in ('retiring', 'retired') for v in self.state['roots'].values()):
            raise MigrationError('Rollback requires closed writers and untouched source backups')
        for entry in reversed(self.plan['roots']):
            value = self.root_state(entry)
            source, backup = Path(entry['source']), self.backup(entry)
            if not backup.exists():
                if value.get('state') in ('linked', 'rename-intent'):
                    raise MigrationError('Original backup is unavailable')
                continue
            if linked(backup) or sig(backup)[0] != value.get('backup_identity'):
                raise MigrationError('Backup identity changed')
            self.check_manifest(entry, backup)
            if os.path.lexists(source):
                if not correct_link(source, entry['destination']):
                    raise MigrationError('A writer recreated the source; both trees retained')
                unlink_pointer(source)
            os.rename(backup, source)
            value['state'] = 'restored'
            self.save()
        self.state['cutover_complete'] = False
        self.save()
        self.update('rolled-back', detail='Original source snapshots restored; destination data retained, including later writes.', force=True)


def dump(value):
    import json
    return json.dumps(value)


def load(value):
    import json
    return json.loads(value)


def protected_backup(path):
    from .model import protected
    return protected(path)


def signature(info, path=None):
    # Windows DirEntry metadata omits the file ID. Keep that safety check
    # with a targeted stat rather than treating every file as inode zero.
    if os.name == 'nt' and not info.st_ino and path is not None:
        info = os.lstat(path)
    return [info.st_ino, info.st_size, info.st_mtime_ns]


def kind_of(info):
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        return 'l'
    if stat.S_ISDIR(info.st_mode):
        return 'd'
    return 'f' if stat.S_ISREG(info.st_mode) else 'unsupported'
