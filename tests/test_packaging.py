import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
EXPORT = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt", "--quiet"]


def test_requirements_match_the_lockfile() -> None:
    # server.py installs from requirements.txt when only Anki's Python is there.
    exported = subprocess.run(EXPORT, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert (ROOT / "requirements.txt").read_text() == exported, f"Run: {' '.join(EXPORT)} > requirements.txt"


def test_versions_agree() -> None:
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert f'version = "{manifest["version"]}"' in pyproject


def test_the_launcher_runs_on_old_pythons() -> None:
    # The plugin starts server.py with whatever python3 the computer has, on macOS often 3.9.
    import ast

    ast.parse((ROOT / "server.py").read_text(), feature_version=(3, 8))
