# Changelog

## 3.0.1 (2026-11-24)

- Fixed: in the first five minutes after the computer started, `overview` listed no note types and
  `draft_add` rejected every note type.

## 3.0.0 (2026-11-24)

The project is now called **Anki MCP**, and the repository moved to
[MichaelPrutkow/anki-mcp](https://github.com/MichaelPrutkow/anki-mcp). Old links redirect.

- `delete_notes` returns a batch id. `undo` adds the deleted notes back with their fields, tags and
  deck, without their review history.
- New settings `ANKI_CONNECT_URL` and `ANKI_CONNECT_API_KEY`, for AnkiConnect on another address or
  with an API key. A missing key gets an error message that says how to fix it.
- Anki starts on its own on Linux too, if the `anki` command exists.
- Pictures live in `~/Pictures/Anki MCP`. The old folder `~/Pictures/Anki for Claude` is renamed on
  the first start.
- Complete privacy policy, now also at [prutkow.com/anki-mcp/privacy](https://prutkow.com/anki-mcp/privacy/).
- CI on macOS and Linux, more evals, CONTRIBUTING, SECURITY and issue templates.

## 2.2.0 (2026-11-23)

- The server starts with Anki's own Python when uv is missing, so Anki 25.07+ needs nothing else.
- `echo=false` for `draft_add` and `draft_edit`, so cards committed without review are not repeated.
- Find and replace across a draft with `draft_edit`.
- Every unknown MathJax macro is named; LaTeX that lost a backslash in JSON is repaired.
- `math_css` lets long formulas scroll sideways on phones.
- `search_notes` can write all matches into a Markdown file.
- Tags per call, near-duplicate hints, more evals.

## 2.1.0 to 2.1.6 (2026-10-10 to 2026-10-11)

- The tools show up in normal chats of the Claude desktop app and in Cowork, not only in Claude Code.
- `cards_text`: cards with LaTeX as plain text, without JSON escaping.
- Icon, documentation, support and privacy links.

## 2.0.0 and 2.0.1 (2026-10-09 to 2026-10-10)

A Claude plugin with skills and agents instead of a bare MCP server.

- Drafts: cards are checked, shown in the chat and only added after approval.
- Pictures: Graphviz graphs, PDF figures, image files and image occlusion.
- `stats` finds the cards you struggle with, `update_notes` fixes them without losing their history.
- An undo journal for every change.

## 1.0.0 (2026-08-25)

The first MCP server: decks, adding, updating and deleting notes, undo by batch and YouTube
transcripts.
