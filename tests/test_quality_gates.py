import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_requirements_dev_pins_tooling():
    req_dev = ROOT_DIR / "requirements-dev.txt"
    assert req_dev.is_file(), "requirements-dev.txt must exist"
    content = req_dev.read_text(encoding="utf-8")
    assert "pytest==" in content, "pytest version must be pinned"
    assert "pytest-asyncio==" in content, "pytest-asyncio version must be pinned"
    assert "ruff==" in content, "ruff version must be pinned"
    assert "mypy==" in content, "mypy version must be pinned"
    assert "PyYAML==" in content, "YAML structure parsing dependency must be pinned"


def test_pyproject_toml_configuration():
    pyproject = ROOT_DIR / "pyproject.toml"
    assert pyproject.is_file(), "pyproject.toml must exist"
    content = pyproject.read_text(encoding="utf-8")
    assert "[tool.ruff]" in content, "Ruff configuration missing in pyproject.toml"
    assert "[tool.mypy]" in content, "Mypy configuration missing in pyproject.toml"
    assert "backend.models.*" in content, "Strict typing for backend.models missing"
    assert "backend.core.*" in content, "Strict typing for backend.core missing"
    assert "backend.repositories.*" in content, "Strict typing for backend.repositories missing"


def test_frontend_quality_gates_configuration():
    pkg_json_path = ROOT_DIR / "frontend" / "package.json"
    assert pkg_json_path.is_file(), "frontend/package.json must exist"
    data = json.loads(pkg_json_path.read_text(encoding="utf-8"))

    scripts = data.get("scripts", {})
    assert "lint:types" in scripts, "Missing lint:types script in package.json"
    assert "lint:eslint" in scripts, "Missing lint:eslint script in package.json"
    assert "lint" in scripts, "Missing unified lint script in package.json"
    assert "test" in scripts, "Missing unified test script in package.json"

    dev_deps = data.get("devDependencies", {})
    assert "eslint" in dev_deps and not dev_deps["eslint"].startswith("^"), "eslint version must be pinned"
    assert "typescript" in dev_deps and not dev_deps["typescript"].startswith("^"), "typescript version must be pinned"
    assert "typescript-eslint" in dev_deps and not dev_deps["typescript-eslint"].startswith("^"), "typescript-eslint must be pinned"

    eslint_cfg = ROOT_DIR / "frontend" / "eslint.config.js"
    assert eslint_cfg.is_file(), "frontend/eslint.config.js must exist"


def test_ci_workflows_enforce_quality_gates():
    build_yml = ROOT_DIR / ".github" / "workflows" / "build.yml"
    ci_yml = ROOT_DIR / ".github" / "workflows" / "ci.yml"

    assert build_yml.is_file(), ".github/workflows/build.yml must exist"
    assert ci_yml.is_file(), ".github/workflows/ci.yml must exist"

    build = yaml.load(build_yml.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    ci = yaml.load(ci_yml.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    # CI workflow (PR gate) must trigger on PR and push to main
    assert "pull_request" in ci["on"], "CI workflow must run on pull_request"
    assert "push" in ci["on"], "CI workflow must run on push"
    assert {"backend-gate", "frontend-gate"} <= ci["jobs"].keys()
    assert "updater-gate" not in ci["jobs"], "Updater tests already run in the full backend suite"
    assert "python -m pytest tests/ -q" in ci["jobs"]["backend-gate"]["steps"][-1]["run"]

    jobs = build["jobs"]
    required_jobs = {
        "quality-gate-backend", "quality-gate-frontend", "build-windows",
        "build-linux", "build-flatpak", "release",
    }
    assert required_jobs <= jobs.keys(), "Build and Release must retain all required gates and package jobs"
    assert not {"test-updater", "distribution-license-files"} & jobs.keys()
    for job in jobs.values():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        assert not {"test-updater", "distribution-license-files"} & set(needs)

    for job_name in ("build-windows", "build-linux", "build-flatpak"):
        needs = jobs[job_name]["needs"]
        needs = {needs} if isinstance(needs, str) else set(needs)
        assert {"quality-gate-backend", "quality-gate-frontend"} <= needs, (
            f"{job_name} must wait for both quality gates"
        )
        assert not {"test-updater", "distribution-license-files"} & needs

    backend = jobs["quality-gate-backend"]
    assert backend["outputs"]["licenses_complete"] == "${{ steps.distribution-license-files.outputs.complete }}"
    assert "python -m pytest tests/ -q" in next(
        step["run"] for step in backend["steps"]
        if step.get("name") == "Run Backend Pytest Suite"
    )
    license_step = next(step for step in backend["steps"] if step.get("id") == "distribution-license-files")
    assert "scripts/check_distribution_licenses.py" in license_step["run"]

    windows_runs_update_tests = any(
        "tests/test_update_helpers.py" in step.get("run", "")
        and "tests/test_updater.py" in step.get("run", "")
        for step in jobs["build-windows"]["steps"]
    )
    assert windows_runs_update_tests, "Windows updater integration tests must run before packaging"
    windows_steps = jobs["build-windows"]["steps"]
    updater_test_index = next(
        index for index, step in enumerate(windows_steps)
        if "tests/test_update_helpers.py" in step.get("run", "")
    )
    packaging_indices = [
        index for index, step in enumerate(windows_steps)
        if step.get("name", "").startswith(("Build Portable", "Build Installer"))
    ]
    assert packaging_indices and updater_test_index < min(packaging_indices)

    approval = "vars.PIRATE_CINEMA_CODEC_REDISTRIBUTION_APPROVED == 'true'"
    license_gate = "needs.quality-gate-backend.outputs.licenses_complete == 'true'"
    for job_name in ("build-windows", "build-linux", "build-flatpak"):
        uploads = [
            step for step in jobs[job_name]["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact")
            and step.get("name") != "Upload Linux size reports"
        ]
        assert uploads, f"{job_name} must retain artifact outputs"
        assert all(license_gate in step.get("if", "") and approval in step.get("if", "") for step in uploads)

    release = jobs["release"]
    release_needs = release["needs"]
    release_needs = {release_needs} if isinstance(release_needs, str) else set(release_needs)
    assert required_jobs - {"release"} <= release_needs
    release_condition = release["if"]
    assert "startsWith(github.ref, 'refs/tags/v')" in release_condition
    assert license_gate in release_condition
    assert approval in release_condition
    assert "workflow_dispatch" in build["on"]
    assert "github.event_name == 'workflow_dispatch'" not in release_condition

    linux_steps = jobs["build-linux"]["steps"]
    runtime_key = next(step for step in linux_steps if step.get("id") == "runtime-cache-key")["run"]
    assert "TYPE2_RUNTIME_COMMIT" in runtime_key
    assert "docker version" in runtime_key
    assert "scripts/build_runtime.py" in runtime_key
    runtime_cache = next(step for step in linux_steps if step.get("id") == "runtime-cache")
    assert runtime_cache["uses"] == "actions/cache@v4"
    runtime_verify = next(step for step in linux_steps if step.get("name") == "Verify or build AppImage runtime with FUSE fallback")["run"]
    assert "verify_runtime_magic" in runtime_verify
    assert "runtime-x86_64.sha256" in runtime_verify

    media_cache_key = next(step for step in linux_steps if step.get("id") == "media-cache-key")["run"]
    assert "dpkg-query -W" in media_cache_key
    assert "scripts/bundle_linux_mpv.py" in media_cache_key
    assert "scripts/bundle_linux_ffmpeg.py" in media_cache_key
    linux_install = next(step for step in linux_steps if step.get("name") == "Install dependencies")["run"]
    assert "https://archive.ubuntu.com" in linux_install
    assert "apt-mirrors.txt" in linux_install
    assert "timeout 5m sudo apt-get" in linux_install
    assert "Acquire::http::Timeout=20" in linux_install

    flatpak_steps = jobs["build-flatpak"]["steps"]
    flatpak_install = next(step for step in flatpak_steps if step.get("name") == "Install Flatpak and smoke test tools")["run"]
    assert "https://archive.ubuntu.com" in flatpak_install
    assert "timeout 5m sudo apt-get" in flatpak_install
    flatpak_sdk_install = next(step for step in flatpak_steps if step.get("name") == "Validate manifest and install the SDK")["run"]
    assert "flatpak update --user --noninteractive --appstream" in flatpak_sdk_install
    flatpak_cache_key = next(step for step in flatpak_steps if step.get("id") == "flatpak-ccache-key")["run"]
    for required_input in ("org.kde.Sdk", "org.kde.Platform", "com.riverbankcomputing.PyQt.BaseApp", "mpv-install-rpath.patch"):
        assert required_input in flatpak_cache_key
    assert "awk '/^  - name: pirate-cinema$/ { exit }" in flatpak_cache_key
    flatpak_build = next(step for step in flatpak_steps if step.get("name") == "Build and export the Flatpak")["run"]
    assert "--ccache" in flatpak_build and "--force-clean" in flatpak_build


def test_mypy_detects_backend_type_regression(tmp_path):
    """Verify that mypy active checks block type regressions."""
    bad_code = """
from backend.models.playback import PlayCommand

def bad_function() -> int:
    cmd = PlayCommand(hash=123, file_id="not-an-int", file_name=None)  # type error
    return "not-an-int"  # type error
"""
    test_file = tmp_path / "bad_test.py"
    test_file.write_text(bad_code, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "mypy", str(test_file), "--config-file", str(ROOT_DIR / "pyproject.toml")],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode != 0, "Mypy must detect type regressions and fail"
    assert "Incompatible return value type" in result.stdout or "error" in result.stdout
