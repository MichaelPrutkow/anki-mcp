"""Starts the plugin's MCP server on macOS and Linux, with nothing to install beyond Anki.

The plugin runs this file with whatever `python3` there is (it only needs the standard library, Python 3.8 or
newer). It then starts the server again with a Python that has the server's dependencies:

1. uv, also where apps started from the Dock do not look (their PATH lacks Homebrew and ~/.local/bin).
2. Otherwise the Python that Anki 25.07+ installs for itself: a venv in the plugin's data folder, filled once
   from requirements.txt (pinned versions with hashes, prebuilt wheels only).

Everything but the MCP protocol goes to stderr: stdout belongs to Claude.
"""

import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STARTED = "ANKI_MCP_STARTED"  # set for the second start, which runs the server itself
HOME = Path.home()
UV_PLACES = [
    HOME / ".local/bin/uv",
    Path("/opt/homebrew/bin/uv"),
    Path("/usr/local/bin/uv"),
    HOME / ".cargo/bin/uv",
]
ANKI_PYTHONS = [
    HOME / "Library/Application Support/AnkiProgramFiles/.venv/bin/python",
    Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "AnkiProgramFiles/.venv/bin/python",
]


def say(message: str) -> None:
    print(f"anki-mcp: {message}", file=sys.stderr, flush=True)


def find_uv():
    on_path = shutil.which("uv")
    for uv in ([Path(on_path)] if on_path else []) + UV_PLACES:
        if uv.is_file() and os.access(uv, os.X_OK):
            return uv
    return None


def anki_venv(python: Path) -> Path:
    """A venv on Anki's Python with the server's dependencies, made once per requirements.txt."""
    venv = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or HOME / ".anki-mcp") / "venv"
    requirements = ROOT / "requirements.txt"
    installed = venv / "requirements.txt"
    if installed.is_file() and filecmp.cmp(requirements, installed, shallow=False):
        return venv
    say(f"installing dependencies into {venv} (first start only)")
    shutil.rmtree(venv, ignore_errors=True)
    pip = [str(venv / "bin/python"), "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
    pip += ["--require-hashes", "--only-binary", ":all:", "-r", str(requirements)]
    try:
        subprocess.run([str(python), "-m", "venv", str(venv)], check=True, stdout=sys.stderr)
        subprocess.run(pip, check=True, stdout=sys.stderr)
    except (OSError, subprocess.CalledProcessError):
        shutil.rmtree(venv, ignore_errors=True)
        say("could not install the dependencies with Anki's Python. Install uv instead.")
        sys.exit(1)
    shutil.copyfile(requirements, installed)
    return venv


def start_again() -> None:
    env = {**os.environ, STARTED: "1"}
    uv = find_uv()
    if uv:
        args = [str(uv), "run", "--directory", str(ROOT), "--frozen", "--no-dev", "--quiet", str(ROOT / "server.py")]
        os.execve(str(uv), args, env)
    for python in ANKI_PYTHONS:
        if python.is_file():
            venv_python = anki_venv(python) / "bin/python"
            env["PYTHONPATH"] = str(ROOT / "src")
            os.execve(str(venv_python), [str(venv_python), str(ROOT / "server.py")], env)
    say("found neither uv nor Anki's own Python. Install Anki 25.07 or newer, or uv.")
    sys.exit(1)


if __name__ == "__main__":
    if os.environ.get(STARTED) != "1":
        start_again()
    from anki_mcp import main

    main()
