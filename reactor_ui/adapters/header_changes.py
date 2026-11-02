"""Explicit, reviewable plans and backed-up atomic header corrections."""

from __future__ import annotations

import copy
import json
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from header_text import associated_header_artifacts, converted_json_path, format_header_text


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


@dataclass(frozen=True)
class FileSnapshot:
    kind: str
    identity: tuple[int, int, int, int] | None = None


def inspect_path(path: Path) -> FileSnapshot:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return FileSnapshot("missing")
    if stat.S_ISLNK(info.st_mode):
        return FileSnapshot("symlink")
    if not stat.S_ISREG(info.st_mode):
        return FileSnapshot("other")
    return FileSnapshot("file", (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))


def _artifact_pairs(source: Path, username: str, header_path: Path | None) -> list[tuple[str, Path, Path]]:
    artifacts = associated_header_artifacts(source, username, str(header_path or ""))
    if not artifacts:
        pairs = [("selected", source, source)]
        if header_path is not None:
            pairs.append(("header_text", header_path, header_path))
        return pairs
    pairs = [
        (key, _absolute(artifacts[key]["current"]), _absolute(artifacts[key]["expected"]))
        for key in ("selected", "header_text", "raw", "condensed", "data_text")
    ]
    header = next(pair for pair in pairs if pair[0] == "header_text")
    pairs.append(("converted_header", converted_json_path(header[1]), converted_json_path(header[2])))
    return pairs


def inspect_header_artifacts(
    source: str | Path, username: str, header_text_path: str | Path | None
) -> dict[Path, FileSnapshot]:
    selected = _absolute(source)
    header = _absolute(header_text_path) if header_text_path else None
    paths = {path for _, current, expected in _artifact_pairs(selected, username, header) for path in (current, expected)}
    return {path: inspect_path(path) for path in paths}


@dataclass(frozen=True)
class PlannedRename:
    source: Path
    destination: Path


@dataclass(frozen=True)
class PlannedWrite:
    kind: str
    source: Path | None
    destination: Path
    temporary: Path


@dataclass(frozen=True)
class PlannedBackup:
    source: Path
    destination: Path


@dataclass(frozen=True)
class HeaderChangePlan:
    selected_after: Path
    header_after: Path | None
    renames: tuple[PlannedRename, ...]
    writes: tuple[PlannedWrite, ...]
    backups: tuple[PlannedBackup, ...]
    expected: tuple[tuple[Path, FileSnapshot], ...]
    read_only: tuple[Path, ...]


def build_header_change_plan(
    source: str | Path,
    username: str,
    header_text_path: str | Path | None,
    *,
    save_header_text: bool,
    align_names: bool,
    inventory: Mapping[Path, FileSnapshot],
    timestamp: str,
    token: str,
    read_only_header: bool = False,
) -> HeaderChangePlan:
    """Build a plan using only the supplied file inventory; perform no I/O."""
    selected = _absolute(source)
    header = _absolute(header_text_path) if header_text_path else None
    if not token or any(char not in "0123456789abcdef" for char in token.lower()):
        raise ValueError("The plan token must contain hexadecimal characters.")
    if not timestamp or any(char not in "0123456789-" for char in timestamp):
        raise ValueError("The plan timestamp is invalid.")
    if align_names and (not username.strip() or any(char in username for char in '<>:"/\\|?*')):
        raise ValueError("The username must be nonempty and contain no filename separators or invalid characters.")
    pairs = _artifact_pairs(selected, username, header)
    if align_names and not associated_header_artifacts(selected, username, str(header or "")):
        raise ValueError("Filename alignment is unavailable for this data filename.")
    if save_header_text and header is None:
        raise ValueError("Select a header text file to update or create.")

    def snapshot(path: Path) -> FileSnapshot:
        if path not in inventory:
            raise ValueError(f"No file inventory was provided for {path}.")
        return inventory[path]

    if snapshot(selected).kind != "file":
        raise ValueError(f"The selected data file must be a regular, non-symlink file: {selected}")
    if header is not None and (save_header_text or read_only_header):
        header_kind = snapshot(header).kind
        allowed = {"file", "missing"} if save_header_text and not read_only_header else {"file"}
        if header_kind not in allowed:
            raise ValueError(f"The header text must be a regular, non-symlink file: {header}")
        if header == selected or (
            header_kind == "file" and snapshot(header).identity[:2] == snapshot(selected).identity[:2]
        ):
            raise ValueError("The data file and header text must not be aliases of the same file.")

    renames: list[PlannedRename] = []
    seen_sources: set[Path] = set()
    destinations: set[Path] = set()
    final_paths: dict[Path, Path] = {}
    if align_names:
        for _, current, expected in pairs:
            if current in seen_sources:
                continue
            seen_sources.add(current)
            current_state = snapshot(current)
            if current_state.kind == "missing":
                continue
            if current_state.kind != "file":
                raise ValueError(f"Cannot rename a non-regular file or symlink: {current}")
            if current == expected:
                continue
            if snapshot(expected).kind != "missing" or expected in destinations:
                raise FileExistsError(f"Cannot rename {current}; destination already exists or conflicts: {expected}")
            destinations.add(expected)
            final_paths[current] = expected
            renames.append(PlannedRename(current, expected))

    selected_after = final_paths.get(selected, selected)
    header_pair = next((pair for pair in pairs if pair[0] == "header_text"), None)
    header_after = header
    if header_pair is not None:
        header_current, header_expected = header_pair[1:]
        header_after = final_paths.get(header_current, header_expected if align_names and save_header_text else header_current)
    writes = [
        PlannedWrite(
            "data_header", selected, selected_after,
            selected_after.with_name(f".{selected_after.name}.{token}.tmp"),
        )
    ]
    if save_header_text:
        assert header is not None and header_after is not None
        if snapshot(header).kind == "missing" and snapshot(header_after).kind != "missing":
            raise FileExistsError(f"Header text destination already exists: {header_after}")
        writes.append(
            PlannedWrite(
                "header_text", header if snapshot(header).kind == "file" else None, header_after,
                header_after.with_name(f".{header_after.name}.{token}.tmp"),
            )
        )
    if len({write.destination for write in writes}) != len(writes):
        raise ValueError("The data and header text destinations conflict.")
    backup_sources = {rename.source for rename in renames}
    backup_sources.update(write.source for write in writes if write.source is not None)
    backups = tuple(
        PlannedBackup(path, path.with_name(f"{path.name}.bak-{timestamp}-{token}"))
        for path in sorted(backup_sources)
    )
    relevant = {selected}
    relevant.update(path for rename in renames for path in (rename.source, rename.destination))
    relevant.update(path for write in writes for path in (write.source, write.destination) if path is not None)
    read_only = (header,) if read_only_header and header is not None else ()
    relevant.update(read_only)
    return HeaderChangePlan(
        selected_after, header_after, tuple(renames), tuple(writes), backups,
        tuple((path, snapshot(path)) for path in sorted(relevant)), read_only,
    )


def describe_header_change_plan(plan: HeaderChangePlan) -> str:
    lines = ["This will overwrite the following files, or rename/create the paths listed below:", ""]
    for rename in plan.renames:
        lines.append(f"RENAME: {rename.source}\n    -> {rename.destination}")
    for write in plan.writes:
        action = "OVERWRITE" if write.source is not None else "CREATE"
        lines.append(f"{action}: {write.destination}")
    for backup in plan.backups:
        lines.append(f"BACKUP: {backup.source}\n    -> {backup.destination}")
    for path in plan.read_only:
        lines.append(f"READ ONLY: {path}")
    for write in plan.writes:
        lines.append(f"TEMPORARY (removed after writing): {write.temporary}")
    return "\n".join(lines)


def validate_header_change_plan(plan: HeaderChangePlan) -> None:
    for path, expected in plan.expected:
        if inspect_path(path) != expected:
            raise RuntimeError(f"File changed since the plan was prepared: {path}")
    for path in [*(backup.destination for backup in plan.backups), *(write.temporary for write in plan.writes)]:
        if inspect_path(path).kind != "missing":
            raise FileExistsError(f"Planned backup or temporary path already exists: {path}")
    for path in [*(rename.destination for rename in plan.renames), *(write.destination for write in plan.writes)]:
        if not path.parent.is_dir():
            raise FileNotFoundError(f"Destination directory does not exist: {path.parent}")


class HeaderChangeFailure(RuntimeError):
    def __init__(self, cause: Exception, changed: list[str], backups: list[Path], cleanup_errors: list[str]) -> None:
        self.cause = cause
        self.changed = tuple(changed)
        self.backups = tuple(backups)
        self.cleanup_errors = tuple(cleanup_errors)
        super().__init__(
            f"{type(cause).__name__}: {cause}\n"
            + "Changed paths:\n" + ("\n".join(changed) if changed else "  None")
            + "\nCreated backups:\n" + ("\n".join(str(path) for path in backups) if backups else "  None")
            + ("\nTemporary-file cleanup errors:\n" + "\n".join(cleanup_errors) if cleanup_errors else "")
        )


@dataclass(frozen=True)
class HeaderChangeResult:
    selected_path: Path
    header_path: Path | None
    changed: tuple[str, ...]
    backups: tuple[Path, ...]


def execute_header_change(
    plan: HeaderChangePlan,
    payload: dict,
    *,
    progress: Callable[[float], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> HeaderChangeResult:
    """Back up every changed file, then apply the confirmed plan."""
    changed: list[str] = []
    backups: list[Path] = []
    temporary: list[Path] = []
    failure: Exception | None = None
    cleanup_errors: list[str] = []
    expected = dict(plan.expected)
    effective_payload = copy.deepcopy(payload)
    try:
        validate_header_change_plan(plan)
        total = len(plan.backups) + len(plan.writes) + len(plan.renames) + len(plan.writes)
        completed = 0

        def step(message: str) -> None:
            nonlocal completed
            completed += 1
            if log is not None:
                log(message)
            if progress is not None:
                progress(100 * completed / max(total, 1))

        for backup in plan.backups:
            if inspect_path(backup.source) != expected[backup.source]:
                raise RuntimeError(f"File changed before backup: {backup.source}")
            created = False
            try:
                with backup.source.open("rb") as source, backup.destination.open("xb") as target:
                    created = True
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
            except Exception:
                if created:
                    try:
                        backup.destination.unlink()
                    except OSError as exc:
                        cleanup_errors.append(f"Incomplete backup {backup.destination}: {exc}")
                raise
            backups.append(backup.destination)
            step(f"Backup created: {backup.destination}")

        for write in plan.writes:
            if write.source is not None and inspect_path(write.source) != expected[write.source]:
                raise RuntimeError(f"File changed before staging: {write.source}")
            with write.temporary.open("xb") as target:
                temporary.append(write.temporary)
                if write.kind == "data_header":
                    assert write.source is not None
                    with write.source.open("rb") as source:
                        first = json.loads(source.readline().decode("utf-8"))
                        if first.get("type") != "header":
                            raise ValueError(f"First record is not a header: {write.source}")
                        existing = first.get("payload", {})
                        if isinstance(existing, str):
                            existing = json.loads(existing)
                        if (
                            isinstance(existing, dict)
                            and isinstance(existing.get("startTime"), str)
                            and existing["startTime"].strip()
                            and (
                                not isinstance(effective_payload.get("startTime"), str)
                                or not effective_payload["startTime"].strip()
                            )
                        ):
                            effective_payload["startTime"] = existing["startTime"]
                        first["payload"] = effective_payload
                        target.write((json.dumps(first, ensure_ascii=False) + "\n").encode("utf-8"))
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                elif write.kind == "header_text":
                    elapsed = ""
                    if write.source is not None:
                        for line in write.source.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                            if line.startswith("Time Elapsed:"):
                                elapsed = line
                                break
                    target.write(format_header_text(effective_payload, elapsed).encode("utf-8"))
                else:
                    raise ValueError(f"Unknown header write: {write.kind}")
                target.flush()
                os.fsync(target.fileno())
            step(f"Staged: {write.destination}")

        for rename in plan.renames:
            if inspect_path(rename.source) != expected[rename.source]:
                raise RuntimeError(f"File changed before rename: {rename.source}")
            if inspect_path(rename.destination).kind != "missing":
                raise FileExistsError(f"Rename destination appeared: {rename.destination}")
            os.rename(rename.source, rename.destination)
            changed.append(f"RENAMED {rename.source} -> {rename.destination}")
            step(changed[-1])

        for write in plan.writes:
            if write.source is None:
                if inspect_path(write.destination).kind != "missing":
                    raise FileExistsError(f"Create destination appeared: {write.destination}")
                os.link(write.temporary, write.destination)
                changed.append(f"CREATED {write.destination}")
                write.temporary.unlink()
            else:
                if inspect_path(write.destination) != expected[write.source]:
                    raise RuntimeError(f"File changed before overwrite: {write.destination}")
                os.replace(write.temporary, write.destination)
                changed.append(f"OVERWROTE {write.destination}")
            step(changed[-1])
    except Exception as exc:
        failure = exc
    finally:
        for path in temporary:
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                cleanup_errors.append(f"{path}: {exc}")
    if failure is not None:
        raise HeaderChangeFailure(failure, changed, backups, cleanup_errors) from failure
    if cleanup_errors:
        raise HeaderChangeFailure(RuntimeError("Could not remove temporary files."), changed, backups, cleanup_errors)
    return HeaderChangeResult(plan.selected_after, plan.header_after, tuple(changed), tuple(backups))
