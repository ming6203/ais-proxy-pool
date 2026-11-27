#!/usr/bin/env python3
"""Apply the named-proxy-pool upgrade to an installed aistudio-api (stdlib only).

Prerequisite: aistudio-api is installed (`.venv` + built waa-signer) and the
Mooece/ais-pg-upgrade patch has already been applied. This package only carries
the proxy-pool delta, never the application, configuration or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
UPSTREAM = "https://github.com/DeconstructedCube/aistudio-api"
BASE = "a28a6c5b0790c4efa4495de8393631bf1ae814b1"
PREVIOUS_PATCH = "Mooece/ais-pg-upgrade"
PREVIOUS_RELEASE = "20261123-full-reply-tools-8c371879"
MARKERS = (
    "main.py",
    "pyproject.toml",
    "src/aistudio_api/main.py",
    "src/aistudio_api/domain/models.py",
    "waa-signer/go.mod",
)
# Files introduced by the prerequisite patch; their presence pins the baseline.
PREVIOUS_MARKERS = (
    "src/aistudio_api/api/routes_openai.py",
    "src/aistudio_api/api/analytics.py",
    "src/aistudio_api/api/reply_cache.py",
    "src/aistudio_api/application/anti_truncation.py",
)


class UpgradeError(Exception):
    pass


def digest(data: bytes, *, raw: bool = False) -> str:
    return hashlib.sha256(data if raw else data.replace(b"\r\n", b"\n")).hexdigest()


def plain_path(path: Path) -> Path:
    """Reject redirected paths, including Windows junctions and dangling links."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise UpgradeError(f"Symlink/junction is not allowed: {part}")
    return path


def safe_relative(value: object) -> str:
    if not isinstance(value, str) or "\\" in value or ":" in value:
        raise UpgradeError(f"Invalid patch path: {value!r}")
    parts = value.split("/")
    if any(p in ("", ".", "..") or p.endswith((" ", ".")) for p in parts):
        raise UpgradeError(f"Invalid patch path: {value!r}")
    if any(
        re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p, re.IGNORECASE)
        for p in parts
    ):
        raise UpgradeError(f"Reserved patch path: {value!r}")
    if PurePosixPath(value).is_absolute():
        raise UpgradeError(f"Absolute patch path: {value}")
    blocked = {".env", ".git", ".venv", "config", "data", "cookies", "cookie"}
    if any(p.lower() in blocked or p.lower().startswith(".env.") for p in parts):
        raise UpgradeError(f"Protected patch path: {value}")
    if not value.startswith(
        ("src/aistudio_api/", "tests/", "web/", "waa-signer/cmd/waa-signer/")
    ):
        raise UpgradeError(f"Path outside patch allowlist: {value}")
    return value


def read_json(path: Path) -> dict:
    plain_path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpgradeError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise UpgradeError(f"Expected JSON object: {path}")
    return value


def installed(project: Path) -> None:
    for marker in MARKERS:
        if not plain_path(project / marker).is_file():
            raise UpgradeError(f"Install the original project first; missing {marker}")
    for marker in PREVIOUS_MARKERS:
        if not plain_path(project / marker).is_file():
            raise UpgradeError(
                "Apply the prerequisite patch first "
                f"({PREVIOUS_PATCH} release {PREVIOUS_RELEASE}); missing {marker}"
            )
    python = next(
        (
            project / p
            for p in (".venv/Scripts/python.exe", ".venv/bin/python")
            if (project / p).is_file()
        ),
        None,
    )
    signer = next(
        (
            project / p
            for p in ("waa-signer/bin/waa-signer.exe", "waa-signer/bin/waa-signer")
            if (project / p).is_file()
        ),
        None,
    )
    if python is None or signer is None:
        raise UpgradeError(
            "Original installation requires its .venv Python and built waa-signer/bin signer"
        )
    # Import third-party packages only: do not import the app, read .env, or contact Google.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    probe = (
        "import sys; assert sys.version_info >= (3,11); "
        "import fastapi,httpx,pydantic,uvicorn,dotenv,yaml,multipart,h2,socksio; "
        "assert int(pydantic.__version__.split('.')[0]) >= 2"
    )
    try:
        py = subprocess.run(
            [str(python), "-I", "-B", "-c", probe],
            check=False,
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if py.returncode:
            raise UpgradeError(
                "Original .venv fails Python >=3.11 / dependency import check"
            )
        sign = subprocess.run(
            [str(signer), "-check"],
            check=False,
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        result = json.loads(sign.stdout)
        if (
            sign.returncode
            or result.get("ok") is not True
            or result.get("mode") != "ipc"
        ):
            raise UpgradeError("Original signer -check must return ok=true, mode=ipc")
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError) as exc:
        raise UpgradeError(f"Original installation probe failed: {exc}") from exc


def preflight(project: Path, package: Path = ROOT) -> tuple[dict, list[dict]]:
    project = plain_path(project)
    package = plain_path(package)
    installed(project)
    manifest = read_json(package / "patch-manifest.json")
    requires = manifest.get("requires")
    if (
        manifest.get("schema_version") != 1
        or not manifest.get("release_id")
        or manifest.get("upstream") != {"url": UPSTREAM, "commit": BASE}
        or not isinstance(requires, dict)
        or requires.get("patch") != PREVIOUS_PATCH
        or not isinstance(manifest.get("entries"), list)
    ):
        raise UpgradeError("Unsupported or invalid patch manifest")
    changes, seen = [], set()
    for entry in manifest["entries"]:
        if not isinstance(entry, dict):
            raise UpgradeError("Invalid manifest entry")
        relative = safe_relative(entry.get("path"))
        if relative.casefold() in seen:
            raise UpgradeError(f"Duplicate patch path: {relative}")
        seen.add(relative.casefold())
        action, base, wanted = (
            entry.get(k) for k in ("action", "base_sha256", "payload_sha256")
        )
        accepted = entry.get("accepted_sha256", [])
        if (
            action not in ("write", "delete")
            or any(
                v is not None
                and (not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None)
                for v in (base, wanted)
            )
            or (action == "write" and wanted is None)
            or (action == "delete" and wanted is not None)
        ):
            raise UpgradeError(f"Invalid action/checksum: {relative}")
        if not isinstance(accepted, list) or any(
            not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None
            for v in accepted
        ):
            raise UpgradeError(f"Invalid accepted checksums: {relative}")
        target = plain_path(project / relative)
        if target.exists() and not target.is_file():
            raise UpgradeError(f"Target is not a regular file: {relative}")
        current = digest(target.read_bytes()) if target.exists() else None
        payload = None
        if action == "write":
            payload = plain_path(package / "payload" / relative).read_bytes()
            if digest(payload) != wanted:
                raise UpgradeError(f"Corrupt payload: {relative}")
            if current == wanted:
                continue
            if current != base and (current is None or current not in accepted):
                raise UpgradeError(f"Unknown target changes: {relative}")
        else:
            if current is None:
                continue
            if current != base and current not in accepted:
                raise UpgradeError(f"Unknown target changes: {relative}")
        changes.append(
            {
                "path": relative,
                "action": action,
                "before": current,
                "after": wanted,
                "payload": payload,
            }
        )
    return manifest, changes


def within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def backup_root(project: Path, package: Path, requested: str | None) -> Path:
    if requested:
        root = Path(requested)
    elif os.environ.get("AIS_PROXY_POOL_BACKUPS"):
        root = Path(os.environ["AIS_PROXY_POOL_BACKUPS"])
    else:
        root = project.parent / "ais-proxy-pool-backups"
    root = plain_path(root)
    forbidden = [project, package]
    if any(within(root, p) for p in forbidden):
        raise UpgradeError(
            "Backup root must be outside the original project and patch package"
        )
    return root


def atomic_write(path: Path, data: bytes, metadata: dict | None = None) -> None:
    plain_path(path)
    missing = []
    ancestor = path.parent
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    for directory in reversed(missing):
        owner = directory.parent.stat()
        directory.mkdir()
        if sys.platform != "win32" and hasattr(os, "chown") and os.geteuid() == 0:
            os.chown(directory, owner.st_uid, owner.st_gid)
    fd, name = tempfile.mkstemp(prefix=".ais-upgrade-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if metadata:
            os.chmod(name, metadata["mode"])
            if sys.platform != "win32" and hasattr(os, "chown"):
                info = os.stat(name)
                if (info.st_uid, info.st_gid) != (metadata["uid"], metadata["gid"]):
                    os.chown(name, metadata["uid"], metadata["gid"])
        else:
            os.chmod(name, 0o644)
            if sys.platform != "win32" and hasattr(os, "chown") and os.geteuid() == 0:
                parent = path.parent.stat()
                os.chown(name, parent.st_uid, parent.st_gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def metadata(path: Path) -> dict:
    info = path.stat()
    return {"mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid}


def save_record(backup: Path, record: dict) -> None:
    data = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode()
    atomic_write(backup / "backup-manifest.json", data)
    atomic_write(
        backup / "backup-manifest.sha256", (digest(data, raw=True) + "\n").encode()
    )


def restore_entry(project: Path, backup: Path, entry: dict) -> None:
    target = plain_path(project / entry["path"])
    if entry["before"] is None:
        if target.exists():
            target.unlink()
    else:
        atomic_write(
            target, (backup / "files" / entry["path"]).read_bytes(), entry["metadata"]
        )


def apply(
    project: Path, requested: str | None = None, package: Path = ROOT
) -> Path | None:
    project = plain_path(project)
    manifest, changes = preflight(project, package)
    root = backup_root(project, plain_path(package), requested)
    if not changes:
        return None
    backup = root / (
        datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:12]
    )
    backup.mkdir(parents=True)
    record = {
        "schema_version": 1,
        "project": str(project),
        "release_id": manifest["release_id"],
        "status": "prepared",
        "entries": [],
    }
    for change in changes:
        target = project / change["path"]
        entry = {k: v for k, v in change.items() if k != "payload"}
        entry["metadata"] = metadata(target) if target.exists() else None
        entry["backup_sha256"] = None
        if target.exists():
            data = target.read_bytes()
            entry["backup_sha256"] = digest(data, raw=True)
            atomic_write(backup / "files" / change["path"], data)
        record["entries"].append(entry)
    save_record(backup, record)  # Every original is durable before the first mutation.
    print(f"Backup prepared: {backup}", flush=True)
    applied = []
    try:
        for change, entry in zip(changes, record["entries"]):
            target = plain_path(project / change["path"])
            current = digest(target.read_bytes()) if target.exists() else None
            if current != entry["before"]:
                raise UpgradeError(f"Target changed during apply: {entry['path']}")
            if change["action"] == "write":
                atomic_write(target, change["payload"], entry["metadata"])
            else:
                target.unlink()
            applied.append(entry)
        record["status"] = "applied"
        save_record(backup, record)
    except Exception as exc:
        recovery_errors = []
        for entry in reversed(applied):
            try:
                restore_entry(project, backup, entry)
            except OSError:
                recovery_errors.append(entry["path"])
        record["status"] = "recovery_required" if recovery_errors else "rolled_back"
        save_record(backup, record)
        if recovery_errors:
            raise UpgradeError(
                f"Apply failed and recovery needs retry; backup: {backup}; "
                f"files: {', '.join(recovery_errors)}"
            ) from exc
        raise
    return backup


def rollback(backup: Path) -> Path:
    backup = plain_path(backup)
    path = backup / "backup-manifest.json"
    data = plain_path(path).read_bytes()
    if (
        digest(data, raw=True)
        != plain_path(backup / "backup-manifest.sha256").read_text().strip()
    ):
        raise UpgradeError("Backup manifest checksum mismatch")
    record = read_json(path)
    project_value = record.get("project")
    if not isinstance(project_value, str) or not Path(project_value).is_absolute():
        raise UpgradeError("Backup must bind an absolute original project path")
    project = plain_path(Path(project_value))
    recovery = record.get("status") in {"prepared", "recovery_required"}
    if (
        record.get("schema_version") != 1
        or record.get("status") not in {"applied", "prepared", "recovery_required"}
        or not isinstance(record.get("entries"), list)
    ):
        raise UpgradeError("Backup is not an applied upgrade")
    backup_root(project, ROOT, str(backup))
    seen = set()
    for entry in record["entries"]:
        if (
            not isinstance(entry, dict)
            or not {"path", "action", "before", "after", "metadata", "backup_sha256"}
            <= entry.keys()
        ):
            raise UpgradeError("Invalid backup entry")
        relative = safe_relative(entry.get("path"))
        if relative.casefold() in seen:
            raise UpgradeError("Duplicate backup path")
        seen.add(relative.casefold())
        if any(
            v is not None
            and (not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None)
            for v in (
                entry.get("before"),
                entry.get("after"),
                entry.get("backup_sha256"),
            )
        ):
            raise UpgradeError(f"Invalid backup checksum: {relative}")
        if (
            entry["action"] not in ("write", "delete")
            or (entry["action"] == "write") != (entry["after"] is not None)
            or (
                entry["before"] is None
                and (
                    entry["backup_sha256"] is not None or entry["metadata"] is not None
                )
            )
        ):
            raise UpgradeError(f"Inconsistent backup entry: {relative}")
        target = plain_path(project / relative)
        current = digest(target.read_bytes()) if target.is_file() else None
        allowed = (
            {entry.get("before"), entry.get("after")}
            if recovery
            else {entry.get("after")}
        )
        if target.exists() and not target.is_file() or current not in allowed:
            raise UpgradeError(f"Target changed after upgrade: {relative}")
        if entry.get("before") is not None:
            original = plain_path(backup / "files" / relative).read_bytes()
            if (
                digest(original, raw=True) != entry.get("backup_sha256")
                or digest(original) != entry["before"]
            ):
                raise UpgradeError(f"Backup file checksum mismatch: {relative}")
            meta = entry.get("metadata")
            if not isinstance(meta, dict) or any(
                not isinstance(meta.get(k), int) for k in ("mode", "uid", "gid")
            ):
                raise UpgradeError(f"Invalid backup metadata: {relative}")
            if not 0 <= meta["mode"] <= 0o7777 or meta["uid"] < 0 or meta["gid"] < 0:
                raise UpgradeError(f"Invalid backup permissions/owner: {relative}")
    record["status"] = "recovery_required"
    save_record(backup, record)
    for entry in reversed(record["entries"]):
        target = project / entry["path"]
        current = digest(target.read_bytes()) if target.is_file() else None
        if current != entry["before"]:
            restore_entry(project, backup, entry)
    record["status"] = "rolled_back"
    save_record(backup, record)
    return project


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "apply"):
        command = commands.add_parser(name)
        command.add_argument("--project", required=True, type=Path)
        command.add_argument("--backup-dir")
    commands.add_parser("rollback").add_argument("--backup", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check":
            _, changes = preflight(args.project)
            backup_root(plain_path(args.project), ROOT, args.backup_dir)
            print(
                f"Installation and patch checks passed; {len(changes)} files require changes. Stop the service before apply."
            )
        elif args.command == "apply":
            backup = apply(args.project, args.backup_dir)
            print(
                f"Upgrade applied. Backup: {backup}"
                if backup
                else "Upgrade already applied; no files changed."
            )
            print(
                "Now rebuild the local signer so `direct` egress is supported:\n"
                "  Windows: powershell -NoProfile -ExecutionPolicy Bypass -File <project>\\waa-signer\\build.ps1\n"
                "  Linux/macOS: bash <project>/waa-signer/build.sh",
                file=sys.stderr,
            )
        else:
            print(f"Upgrade rolled back: {rollback(args.backup)}")
        return 0
    except (UpgradeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Upgrade refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
