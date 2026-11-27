"""Behavior tests use real isolated files and simulated installed component probes."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

import upgrade as u


@pytest.fixture
def installation(tmp_path, monkeypatch):
    project, package = tmp_path / "original", tmp_path / "package"
    project.mkdir()
    package.mkdir()
    installed_files = (
        *u.MARKERS,
        *u.PREVIOUS_MARKERS,
        ".venv/Scripts/python.exe",
        "waa-signer/bin/waa-signer.exe",
    )
    for name in installed_files:
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"installed\n")
    for name in (".env", "data/cookies.json", "config/settings.yaml"):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"private material\r\n")
    monkeypatch.setattr(
        u.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(
            returncode=0, stdout='{"ok": true, "mode": "ipc"}', stderr=""
        ),
    )
    return project, package, tmp_path / "backups"


def manifest(package, entries):
    (package / "patch-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "release_id": "test",
                "upstream": {"url": u.UPSTREAM, "commit": u.BASE},
                "requires": {
                    "patch": u.PREVIOUS_PATCH,
                    "release_id": u.PREVIOUS_RELEASE,
                    "commit": "bd8893d",
                },
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )


def patch(
    project,
    package,
    relative="src/aistudio_api/domain/models.py",
    before=b"installed\n",
    after=b"upgraded\n",
):
    if before is not None:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(before)
    if after is not None:
        path = package / "payload" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(after)
    return {
        "path": relative,
        "action": "delete" if after is None else "write",
        "base_sha256": u.digest(before) if before is not None else None,
        "payload_sha256": u.digest(after) if after is not None else None,
    }


def test_apply_repeat_rollback_preserves_data_and_raw_original(installation):
    project, package, root = installation
    old = b"original\r\n"
    entries = [
        patch(project, package, before=old),
        patch(project, package, "web/new.js", before=None, after=b"new\n"),
        patch(project, package, "tests/obsolete.py", after=None),
    ]
    manifest(package, entries)
    private = {
        p: p.read_bytes()
        for p in [
            project / ".env",
            project / "data/cookies.json",
            project / "config/settings.yaml",
        ]
    }
    target = project / entries[0]["path"]
    target.chmod(0o640)
    original_mode = target.stat().st_mode
    backup = u.apply(project, str(root), package)
    assert target.read_bytes() == b"upgraded\n"
    assert target.stat().st_mode == original_mode
    assert not (project / "tests/obsolete.py").exists()
    assert u.apply(project, str(root), package) is None
    assert len(list(root.iterdir())) == 1
    assert u.rollback(backup) == project
    assert target.read_bytes() == old
    assert target.stat().st_mode == original_mode
    assert not (project / "web/new.js").exists()
    assert (project / "tests/obsolete.py").read_bytes() == b"installed\n"
    assert all(path.read_bytes() == data for path, data in private.items())


def test_check_executes_installation_probes_and_does_not_write(
    installation, monkeypatch
):
    project, package, _ = installation
    manifest(package, [patch(project, package)])
    calls = []

    def probe(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            returncode=0, stdout='{"ok":true,"mode":"ipc"}', stderr=""
        )

    monkeypatch.setattr(u.subprocess, "run", probe)
    _, changes = u.preflight(project, package)
    assert len(changes) == 1 and len(calls) == 2
    assert "-I" in calls[0][0] and calls[1][0][-1] == "-check"
    assert calls[0][1]["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert (project / changes[0]["path"]).read_bytes() == b"installed\n"


def test_empty_project_refused(tmp_path):
    with pytest.raises(u.UpgradeError, match="Install the original"):
        u.preflight(tmp_path)


def test_prerequisite_patch_refused(installation):
    project, package, _ = installation
    manifest(package, [patch(project, package)])
    (project / u.PREVIOUS_MARKERS[0]).unlink()
    with pytest.raises(u.UpgradeError, match="prerequisite patch"):
        u.preflight(project, package)


@pytest.mark.parametrize(
    "component", [".venv/Scripts/python.exe", "waa-signer/bin/waa-signer.exe"]
)
def test_uninstalled_components_refused(installation, component):
    project, package, _ = installation
    (project / component).unlink()
    with pytest.raises(u.UpgradeError, match="Original installation requires"):
        u.preflight(project, package)


@pytest.mark.parametrize(
    "stdout,returncode",
    [
        ("{}", 0),
        ('{"ok":true,"mode":"http"}', 0),
        ("not json", 0),
        ('{"ok":true,"mode":"ipc"}', 1),
    ],
)
def test_bad_signer_refused(installation, monkeypatch, stdout, returncode):
    project, package, _ = installation
    monkeypatch.setattr(
        u.subprocess,
        "run",
        lambda args, **kw: SimpleNamespace(
            returncode=returncode if args[-1] == "-check" else 0,
            stdout=stdout,
            stderr="",
        ),
    )
    with pytest.raises(u.UpgradeError):
        u.preflight(project, package)


def test_manifest_requires_previous_patch(installation):
    project, package, _ = installation
    manifest(package, [patch(project, package)])
    data = json.loads((package / "patch-manifest.json").read_text(encoding="utf-8"))
    data["requires"] = {"patch": "something-else"}
    (package / "patch-manifest.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(u.UpgradeError, match="Unsupported or invalid"):
        u.preflight(project, package)


def test_dependency_failure_does_not_echo_sensitive_probe_output(
    installation, monkeypatch
):
    project, package, _ = installation
    monkeypatch.setattr(
        u.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stderr="secret", stdout=""),
    )
    with pytest.raises(u.UpgradeError) as error:
        u.preflight(project, package)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "relative",
    [
        "../main.py",
        "/tmp/evil",
        "web/../../.env",
        "web\\evil",
        "web/x:evil",
        "web/.env",
        "web/data/private",
        "waa-signer/bin/waa-signer",
        "waa-signer/internal/aistudio/signer.go",
        "scripts/evil.ps1",
        "web/NUL.js",
    ],
)
def test_unsafe_paths_refused_before_any_mutation(installation, relative):
    project, package, root = installation
    entries = [
        patch(project, package),
        {
            "path": relative,
            "action": "delete",
            "base_sha256": None,
            "payload_sha256": None,
        },
    ]
    manifest(package, entries)
    with pytest.raises(u.UpgradeError):
        u.apply(project, str(root), package)
    assert (project / entries[0]["path"]).read_bytes() == b"installed\n"
    assert not root.exists()


def test_signer_command_path_is_allowed(installation):
    project, package, root = installation
    relative = "waa-signer/cmd/waa-signer/main.go"
    entries = [patch(project, package, relative)]
    manifest(package, entries)
    u.apply(project, str(root), package)
    assert (project / relative).read_bytes() == b"upgraded\n"


def test_all_conflicts_preflight_before_any_write(installation):
    project, package, root = installation
    entries = [patch(project, package), patch(project, package, "web/index.html")]
    manifest(package, entries)
    (project / "web/index.html").write_bytes(b"user edits\n")
    with pytest.raises(u.UpgradeError, match="Unknown target changes"):
        u.apply(project, str(root), package)
    assert (project / entries[0]["path"]).read_bytes() == b"installed\n"
    assert not root.exists()


def test_corrupt_payload_refused(installation):
    project, package, root = installation
    entry = patch(project, package)
    manifest(package, [entry])
    (package / "payload" / entry["path"]).write_bytes(b"corrupt")
    with pytest.raises(u.UpgradeError, match="Corrupt payload"):
        u.apply(project, str(root), package)


def test_duplicate_casefold_path_refused(installation):
    project, package, root = installation
    entry = patch(project, package)
    manifest(package, [entry, dict(entry, path=entry["path"].upper())])
    with pytest.raises(u.UpgradeError):
        u.apply(project, str(root), package)
    assert not root.exists()


def test_symlink_target_ancestor_refused(installation):
    project, package, root = installation
    outside = root.parent / "outside"
    outside.mkdir()
    try:
        (project / "web").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not grant symlink creation")
    manifest(
        package,
        [
            {
                "path": "web/evil.js",
                "action": "delete",
                "base_sha256": None,
                "payload_sha256": None,
            }
        ],
    )
    with pytest.raises(u.UpgradeError, match="Symlink/junction"):
        u.apply(project, str(root), package)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_junction_target_ancestor_refused(installation):
    project, package, root = installation
    outside = root.parent / "outside-junction"
    outside.mkdir()
    # Run the genuine command runner because the fixture replaces installer probes only.
    with subprocess.Popen(
        ["cmd", "/c", "mklink", "/J", str(project / "web"), str(outside)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
    manifest(
        package,
        [
            {
                "path": "web/evil.js",
                "action": "delete",
                "base_sha256": None,
                "payload_sha256": None,
            }
        ],
    )
    with pytest.raises(u.UpgradeError, match="Symlink/junction"):
        u.apply(project, str(root), package)


@pytest.mark.parametrize("destination", ["original", "package"])
def test_internal_backup_root_refused(installation, destination):
    project, package, _ = installation
    manifest(package, [patch(project, package)])
    with pytest.raises(u.UpgradeError, match="Backup root must"):
        u.apply(
            project,
            str((project if destination == "original" else package) / "backup"),
            package,
        )


@pytest.mark.parametrize("corruption", ["target", "backup", "manifest"])
def test_rollback_preflights_all_files(installation, corruption):
    project, package, root = installation
    entries = [patch(project, package), patch(project, package, "web/index.html")]
    manifest(package, entries)
    backup = u.apply(project, str(root), package)
    if corruption == "target":
        (project / entries[0]["path"]).write_bytes(b"further user edits")
    elif corruption == "backup":
        (backup / "files" / entries[0]["path"]).write_bytes(b"bad backup")
    else:
        (backup / "backup-manifest.json").write_bytes(b"{}")
    with pytest.raises(u.UpgradeError):
        u.rollback(backup)
    assert (project / "web/index.html").read_bytes() == b"upgraded\n"


def test_apply_failure_automatically_restores_every_completed_file(
    installation, monkeypatch
):
    project, package, root = installation
    entries = [patch(project, package), patch(project, package, "web/index.html")]
    manifest(package, entries)
    original_write = u.atomic_write

    def fail_second(path, data, metadata=None):
        if path == project / "web/index.html" and data == b"upgraded\n":
            raise OSError("simulated disk failure")
        return original_write(path, data, metadata)

    monkeypatch.setattr(u, "atomic_write", fail_second)
    with pytest.raises(OSError, match="simulated"):
        u.apply(project, str(root), package)
    assert all(
        (project / entry["path"]).read_bytes() == b"installed\n" for entry in entries
    )
    record = json.loads(
        next(root.iterdir()).joinpath("backup-manifest.json").read_text()
    )
    assert record["status"] == "rolled_back"


def test_previous_release_hash_is_accepted_and_restored(installation):
    project, package, root = installation
    entry = patch(project, package)
    previous = b"previous release\n"
    entry["accepted_sha256"] = [u.digest(previous)]
    (project / entry["path"]).write_bytes(previous)
    manifest(package, [entry])
    backup = u.apply(project, str(root), package)
    u.rollback(backup)
    assert (project / entry["path"]).read_bytes() == previous


def test_lf_hash_accepts_git_crlf_checkout(installation):
    project, package, root = installation
    entry = patch(project, package)
    manifest(package, [entry])
    (project / entry["path"]).write_bytes(b"installed\r\n")
    (package / "payload" / entry["path"]).write_bytes(b"upgraded\r\n")
    backup = u.apply(project, str(root), package)
    u.rollback(backup)
    assert (project / entry["path"]).read_bytes() == b"installed\r\n"


def test_failed_automatic_recovery_can_be_retried(installation, monkeypatch, capsys):
    project, package, root = installation
    entries = [
        patch(project, package),
        patch(project, package, "web/a.js"),
        patch(project, package, "web/b.js"),
    ]
    manifest(package, entries)
    original_write = u.atomic_write

    def failing_write(path, data, metadata=None):
        if path == project / "web/b.js" and data == b"upgraded\n":
            raise OSError("application failure")
        if path == project / "web/a.js" and data == b"installed\n":
            raise OSError("recovery failure")
        return original_write(path, data, metadata)

    monkeypatch.setattr(u, "atomic_write", failing_write)
    with pytest.raises(u.UpgradeError, match="recovery needs retry"):
        u.apply(project, str(root), package)
    backup = next(root.iterdir())
    assert str(backup) in capsys.readouterr().out
    assert (
        json.loads((backup / "backup-manifest.json").read_text())["status"]
        == "recovery_required"
    )
    assert (project / entries[0]["path"]).read_bytes() == b"installed\n"
    assert (project / "web/a.js").read_bytes() == b"upgraded\n"
    monkeypatch.setattr(u, "atomic_write", original_write)
    u.rollback(backup)
    assert all(
        (project / entry["path"]).read_bytes() == b"installed\n" for entry in entries
    )


def test_partial_manual_rollback_can_be_retried(installation, monkeypatch):
    project, package, root = installation
    entries = [patch(project, package), patch(project, package, "web/a.js")]
    manifest(package, entries)
    backup = u.apply(project, str(root), package)
    original_write = u.atomic_write

    def failing_write(path, data, metadata=None):
        if path == project / entries[0]["path"] and data == b"installed\n":
            raise OSError("restore unavailable")
        return original_write(path, data, metadata)

    monkeypatch.setattr(u, "atomic_write", failing_write)
    with pytest.raises(OSError, match="restore unavailable"):
        u.rollback(backup)
    assert (project / "web/a.js").read_bytes() == b"installed\n"
    assert (
        json.loads((backup / "backup-manifest.json").read_text())["status"]
        == "recovery_required"
    )
    monkeypatch.setattr(u, "atomic_write", original_write)
    u.rollback(backup)
    assert all(
        (project / entry["path"]).read_bytes() == b"installed\n" for entry in entries
    )
