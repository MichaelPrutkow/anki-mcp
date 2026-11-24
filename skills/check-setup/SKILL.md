---
name: check-setup
description: Checks whether the anki plugin can work on the user's computer - Anki running with the AnkiConnect add-on, the Image Occlusion note type, Graphviz, AnkiWeb sync - and tells the user exactly how to fix what is missing. Use right after the plugin is installed, when the anki tools are missing or fail, or when the user asks whether everything is set up.
---

# Checking the setup

The anki tools run in a small server on the user's computer and talk to Anki through the AnkiConnect add-on. You can test the setup through these tools, but you cannot install programs or click anything in Anki for the user. For every problem, tell the user exactly what to do. Only if you can run commands on the user's computer yourself (for example in Claude Code) may you offer to run an install command for them.

Go through the steps in order. Stop at the first one that fails, explain the fix, and continue once the user has done it.

1. **The anki tools exist.** If `overview` is not among your tools, call `get_device_info` (search for it if it is not loaded) and search for the anki tools again. If they are still missing, this chat does not reach the plugin's server on the user's computer; whether Anki is open does not matter for this. Give the user these fixes in this order, each one only if the one before did not help:
   - Check that the chat is a local session on the user's computer, not a web session. The plugin's server runs on the user's computer and a web session cannot reach it. If needed, the user starts a new local session, or tells you to work locally, and sends the request again.
   - In the Claude app, adding a folder also helps: start a new chat, add a folder with the Add folder button before sending the first message (for example the folder with the study material), then send the request again. This used to be needed for the chat to reach the tools on the user's computer; newer versions often don't need it, but it does no harm.
   - Quit the Claude app completely, open it again and start a new chat. The first start can take a minute while the plugin's dependencies download.
   - The plugin starts its server with `python3`. On macOS that needs Apple's Command Line Tools: if `python3 --version` fails in Terminal, the user runs `xcode-select --install` once and restarts the Claude app.
   - The server then runs on the Python that Anki 25.07 or newer brings along, or on uv if it is installed. On Windows the plugin does not run yet. With an older Anki, the user updates Anki (https://apps.ankiweb.net) or installs uv: `brew install uv` on macOS, otherwise as the uv installation guide describes (https://docs.astral.sh/uv/getting-started/installation/). Then restart the Claude app.
   - Update the plugin to the newest version.
2. **Anki and AnkiConnect.** Call `overview`.
   - It lists decks and note types: both work.
   - "does not answer" or "not running": Anki is closed or AnkiConnect is missing. The user opens Anki. If that is not enough, they install AnkiConnect in Anki under Tools > Add-ons > Get Add-ons... with the code `2055492159` and restart Anki.
   - "did not answer in time": a window is waiting in Anki, often the profile chooser or a sync question. The user closes it. If the profile chooser comes up every time, they can open their profile once and let Anki remember it.
   - "require an API key": the user has set an `apiKey` in AnkiConnect's config, which the plugin does not use. They clear it in Anki under Tools > Add-ons > AnkiConnect > Config and restart Anki.
3. **Image Occlusion** (only for image occlusion cards). `overview` lists a note type marked `[image occlusion]`. If there is none: it needs Anki 23.10 or newer; then the user adds it in Anki under Tools > Manage Note Types > Add > "Add: Image Occlusion".
4. **Graphviz** (only for drawn graphs). `overview` says so when Graphviz is missing. The user installs it with `brew install graphviz` on macOS or the `graphviz` package on Linux.
5. **Phone** (only if the user studies on a phone). Call `sync`. If it fails, the user logs in to AnkiWeb in Anki under Tools > Preferences > Syncing.
6. **Formulas on a phone** (only if the user's cards have formulas and they study on a phone). Anki never breaks a formula across lines, so a long one runs off a phone screen. Offer `math_css` for the note types the user writes cards with, usually Basic and Cloze as `overview` names them. It changes only their styling: a formula wider than the screen then scrolls sideways. Call it only after the user agrees; `undo` with the returned batch id removes it again.

End with a short checklist: each item ok, or the fix the user still has to do. Do not change any cards during the check.
