![Anki for Claude logo](.claude-plugin/icon.svg)

# Anki for Claude

Claude writes your Anki cards. From lecture slides, PDFs, YouTube videos or whatever's in the chat.

[![Stars](https://img.shields.io/github/stars/MichaelPrutkow/anki-for-claude?style=flat&color=yellow)](https://github.com/MichaelPrutkow/anki-for-claude/stargazers)
[![MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Claude plugin](https://img.shields.io/badge/Claude-plugin-D97757)
![Anki 23.10+](https://img.shields.io/badge/Anki-23.10%2B-orange)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB)

A Claude plugin that runs locally against your Anki. It reads your material, writes the cards,
draws the diagrams and makes native image occlusion cards. Later it goes through your review
history and fixes the cards you keep failing.

Nothing hits your collection until you say yes.

> Unofficial. Not affiliated with Ankitects Pty Ltd.

## Demo

YouTube video + lecture slides in:

https://github.com/user-attachments/assets/68d1f24f-7f6c-480d-aa16-c312484f873b

Cards out, clicked through in Anki:

https://github.com/user-attachments/assets/00ac5217-9e81-4b8c-8479-c9aa38729dc4

## What's different

Most AI flashcard tools turn a PDF into 300 cards you'll never review. This one writes fewer
cards, from your own material, and keeps fixing the ones that don't stick.

- Cards follow actual rules. One fact per card, no yes/no questions, no lists (they become
  clozes), and a theorem gets separate cards for statement, hypotheses and key idea. The wording
  rules come from [Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing),
  so the cards don't read like an LLM wrote them.
- You see every card word for word before it's added. Tell Claude what to change, approve, done. Or say
  *"commit them directly"*: Claude adds them without printing them, which saves tokens.
- Real pictures. Graphs, trees and automata via Graphviz. Figures cut out of your PDF by their
  caption (*"Fig. 3.2"*). Plots via matplotlib. Native image occlusion, with masks placed from the
  PDF's text layer or the graph's node positions instead of guessed from pixels.
- Your review history decides what gets fixed. `stats` ranks notes by again rate, lapses, FSRS
  difficulty, answer time, leeches and red flags. Flag a card red on your phone and Claude picks
  it up next time.
- A whole course in one go, only when you start it with `/anki:exam-prep`. You approve a topic
  blueprint weighted by past exams, then the cards get written, illustrated, audited and approved
  topic by topic. Small courses run without agents; large ones use at most three at a time, and
  Claude tells you how many before it starts them, so one course doesn't eat your usage limits.
- Everything is undoable. Every commit and edit returns a batch id, `undo` reverts it.

## Setup

You need:

- **macOS or Linux.** Windows isn't supported yet.
- **Anki 25.07+** with [AnkiConnect](https://ankiweb.net/shared/info/2055492159):
  *Tools → Add-ons → Get Add-ons*, code `2055492159`, restart Anki. The server runs on the Python
  that Anki brings along, so there's nothing else to install. With an older Anki (23.10+), install
  [uv](https://docs.astral.sh/uv/getting-started/installation/) (`brew install uv`); if uv is
  there, the server uses it.
- **Claude Code** or the **Claude desktop app**.
- Optional: **[Graphviz](https://graphviz.org/download/)** for graphs, trees and automata
  (`brew install graphviz`).

**Claude Code**

```
/plugin marketplace add MichaelPrutkow/anki-for-claude
/plugin install anki@michaelprutkow
```

**Desktop app:** *Customize → Plugins → Add → Add marketplace*, enter
`MichaelPrutkow/anki-for-claude`, install **Anki Flashcards**.

Then say *"check my Anki setup"*. The first start takes a few seconds up to a minute while the
dependencies download (pinned versions from PyPI, into the plugin's data folder).

In the desktop app, add a folder to the chat before your first message (your lecture folder, for
example). The server runs on your machine, and without a folder the chat doesn't reliably reach
it. Claude needs the folder for your PDFs anyway.

No config. It uses AnkiConnect on `http://127.0.0.1:8765` and launches Anki if it's closed
(macOS).

## Usage

*"Make flashcards from this lecture for my deck Analysis 2."*

Claude drafts, you review in the chat, it commits when you say yes. That's the loop.

| Skill | For |
| --- | --- |
| `/anki:create-cards` | Cards from any material |
| `/anki:visuals` | Graphs, PDF figures, plots, image occlusion |
| `/anki:improve-cards` | Find and fix weak cards, search, delete, undo |
| `/anki:exam-prep` | A whole course (slides, exercise sheets, past exams) into a prioritised deck |
| `/anki:check-setup` | Check Anki, AnkiConnect, the image occlusion note type and Graphviz |

Claude picks the skill itself. The slash commands are there to force one.

- Want it on autopilot? Schedule *"improve my weakest cards in Analysis 2"* as a task in the
  desktop app.
- PDFs and images are opened by their full path. A file you attach in the desktop app isn't on
  disk yet, so Claude saves it first or asks you for the path.

## Under the hood

- Drafts are saved to disk, so they survive restarts. Every card is checked against your note
  types and for duplicates before you see it.
- The tools catch the usual formatting slips: LaTeX outside `\( \)`, `$...$` math Anki won't
  render, braces that close a cloze too early, unbalanced braces and environments, and every macro
  Anki's MathJax doesn't know (`\and`, `\R`, `\abs`, ...), checked against the macro list of the
  MathJax 3.2.2 that Anki ships.
- They repair what JSON does to a single backslash (`\text` arrives as a tab and `ext`) and escape a
  stray `<`. Cards with formulas can also go in as plain text (`cards_text`), where backslashes need
  no escaping at all.
- New cards that read almost like one already in the deck are flagged.
- `math_css` lets long formulas scroll sideways on a phone instead of running off the card.
- Pictures land in `~/Pictures/Anki for Claude`, so you can look at them while reviewing. Image
  occlusion cards also get a `<name>-masks.png` that shows the masks.
- The card rules live in a skill, so they cost nothing in chats that aren't about Anki.
- Tool output is short plain text. Long YouTube videos come back as a timestamped outline, and
  Claude only pulls the parts it needs.
- `undo` leaves cards you studied or edited in the meantime alone, unless you tell it otherwise.
  Cards the plugin didn't create can't be deleted by it and are only edited after you agree.

## Tools

| Tool | Access | What it does |
| --- | --- | --- |
| `overview` | read | Decks, card counts, note types and their exact field names |
| `search_notes` | read | Search with Anki's query syntax, or write the matches into a Markdown file |
| `draft_add` | draft | Check cards and add them to a draft |
| `draft_add_occlusion` | draft | Image occlusion note, masks by label or region |
| `draft_edit` | draft | Change, move or remove draft cards, or find and replace across a draft |
| `draft_show` | read | Show a draft, or list the open ones |
| `stage_image` | draft | Save an image, a PDF figure or part of a PDF page for a card |
| `pdf_figures` | read | Find figures and their captions in a PDF |
| `render_graph` | draft | Draw a graph, tree or automaton with Graphviz |
| `stats` | read | Card counts, retention and the cards you struggle with |
| `youtube_transcript` | web | Transcript or outline of a YouTube video |
| `draft_commit` | **write** | Add the approved cards, create missing decks |
| `update_notes` | **write** | Fix cards without losing their review history |
| `undo` | **write** | Revert a commit, an edit or `math_css` by its batch id |
| `math_css` | **write** | Let long formulas scroll on phones (styling of the chosen note types) |
| `delete_notes` | **write** | Delete notes this plugin created |
| `sync` | **write** | Sync with AnkiWeb so the cards reach your phone |

*Draft* tools only touch drafts and pictures, never your collection.

## Safety

> **Back up first.** This writes to your real collection: *File → Export → Anki Collection Package*.

It won't:

- add cards you didn't approve in the chat
- delete a note it didn't create
- edit a note it didn't create without asking
- open anything except images and PDFs

## Privacy

Runs on your machine. Nothing is sent to me.

- **Anki:** AnkiConnect on `127.0.0.1`.
- **Stored locally:** drafts (deleted after 14 days untouched) and the undo journal in
  `~/.anki-mcp`, pictures in `~/Pictures/Anki for Claude` until you delete them.
- **Only when you ask:** the video id goes to YouTube for a transcript, an image URL you want on a
  card gets fetched, and Anki syncs your collection to AnkiWeb.
- **Programs it starts:** Anki if it's closed (macOS), and Graphviz's `dot` for graphs.
- **First start:** uv, or without uv Anki's own Python with pip, downloads the pinned dependencies
  from PyPI (`requirements.txt`, checked by hash).

Full policy: [PRIVACY.md](PRIVACY.md).

## Known limits

- An open dialog in Anki blocks AnkiConnect. Every call times out until you close it.
- Claude Code and Cowork only. The server runs locally, so a plain chat (including claude.ai in
  the browser) can't reach it.
- Anki auto-starts on macOS only. On Linux, open it yourself.
- No Windows yet: the plugin starts its server with a shell script.
- Duplicates: Anki rejects exact copies of the first field. Near-copies are only flagged, and only
  against the newest 1500 notes of the deck.
- Deleting can't be undone. Fix a card instead.
- Image occlusion is rectangles only. Masks by label need a PDF text layer or a Graphviz graph,
  otherwise Claude places them by region.
- FSRS difficulty is read from the review log, because AnkiConnect doesn't expose FSRS memory
  states. Good enough for ranking.

## Other MCP clients

The MCP server works without the plugin too, e.g. in Cursor. You get the tools, not the skills
and agents.

```bash
git clone https://github.com/MichaelPrutkow/anki-for-claude.git
cd anki-for-claude
uv sync --no-dev
```

```json
{
  "mcpServers": {
    "anki": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/anki-for-claude", "--no-dev", "-m", "anki_mcp"]
    }
  }
}
```

## Development

```bash
uv sync
uv run pytest            # tools against an in-memory fake of AnkiConnect, no Anki needed
ANKI_LIVE=1 uv run pytest tests/test_live_anki.py
                         # read-only smoke test against the real AnkiConnect, with Anki open
node scripts/mathjax_names.js <mathjax-full@3.2.2> > src/anki_mcp/mathjax_names.py
                         # when Anki ships another MathJax: the macros the lint accepts
uv export --frozen --no-dev --no-emit-project --format requirements-txt --quiet > requirements.txt
                         # after changing dependencies: the launcher installs from it without uv
claude plugin eval .     # Claude with the plugin vs. without it, against mocked tools
claude --plugin-dir .    # try it in Claude Code
```

## Credits

- [AnkiConnect](https://git.sr.ht/~foosoft/anki-connect) by foosoft
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) by jdepoix
- [pdfplumber](https://github.com/jsvine/pdfplumber), [Pillow](https://python-pillow.org) and
  [Graphviz](https://graphviz.org) for the pictures
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
