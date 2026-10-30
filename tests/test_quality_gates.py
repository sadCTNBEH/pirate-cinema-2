import json
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_requirements_dev_pins_tooling():
    req_dev = ROOT_DIR / "requirements-dev.txt"
    assert req_dev.is_file(), "requirements-dev.txt must exist"
    content = req_dev.read_text(encoding="utf-8")
    assert "pytest==" in content, "pytest version must be pinned"
    assert "pytest-asyncio==" in content, "pytest-asyncio version must be pinned"
    assert "ruff==" in content, "ruff version must be pinned"
    assert "mypy==" in content, "mypy version must be pinned"


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

    build_text = build_yml.read_text(encoding="utf-8")
    ci_text = ci_yml.read_text(encoding="utf-8")

    # CI workflow (PR gate) must trigger on PR and push to main
    assert "pull_request" in ci_text, "CI workflow must run on pull_request"
    assert "backend-gate" in ci_text, "CI workflow must have backend-gate"
    assert "frontend-gate" in ci_text, "CI workflow must have frontend-gate"

    # Build and Release workflow (Release gate) must block packaging on quality gate failure
    assert "quality-gate-backend" in build_text, "build.yml must define quality-gate-backend"
    assert "quality-gate-frontend" in build_text, "build.yml must define quality-gate-frontend"
    assert "needs: [quality-gate-backend, quality-gate-frontend, test-updater]" in build_text, (
        "Packaging jobs must depend on quality gates before starting"
    )


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
