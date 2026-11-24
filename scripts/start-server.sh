#!/bin/sh
# Starts the plugin's MCP server on macOS and Linux, without anything to install beyond Anki.
# 1. uv, also where apps started from the Dock do not look (their PATH lacks Homebrew and ~/.local/bin).
# 2. Otherwise the Python that Anki 25.07+ installs for itself: a venv in the plugin's data folder,
#    filled once from requirements.txt (pinned versions with hashes, prebuilt wheels only).
# Everything but the MCP protocol goes to stderr: stdout belongs to Claude.

root=$(cd "$(dirname "$0")/.." && pwd)

for uv in "$(command -v uv)" /opt/homebrew/bin/uv /usr/local/bin/uv "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$uv" ]; then
        exec "$uv" run --directory "$root" --frozen --no-dev --quiet "$root/server.py"
    fi
done

for python in \
    "$HOME/Library/Application Support/AnkiProgramFiles/.venv/bin/python" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/AnkiProgramFiles/.venv/bin/python"; do
    [ -x "$python" ] || continue
    venv="${CLAUDE_PLUGIN_DATA:-$HOME/.anki-mcp}/venv"
    if ! cmp -s "$root/requirements.txt" "$venv/requirements.txt"; then
        echo "anki-mcp: installing dependencies into $venv (first start only)" >&2
        rm -rf "$venv"
        if ! "$python" -m venv "$venv" >&2 ||
            ! "$venv/bin/python" -m pip install --quiet --disable-pip-version-check --require-hashes \
                --only-binary :all: -r "$root/requirements.txt" >&2; then
            rm -rf "$venv"
            echo "anki-mcp: could not install the dependencies with Anki's Python. Install uv instead." >&2
            exit 1
        fi
        cp "$root/requirements.txt" "$venv/requirements.txt"
    fi
    PYTHONPATH="$root/src" exec "$venv/bin/python" "$root/server.py"
done

echo "anki-mcp: found neither uv nor Anki's own Python. Install Anki 25.07 or newer, or uv." >&2
exit 1
