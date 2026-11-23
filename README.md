<p align="center">
  <img src=".claude-plugin/icon.png" alt="" width="96">
</p>

<h1 align="center">Anki for Claude</h1>

<p align="center">
  Anki cards with real pictures, written by Claude: graphs, PDF figures, plots and image occlusion,
  straight into your collection.
</p>

<p align="center">
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-green"></a>
  <img alt="Anki 23.10+" src="https://img.shields.io/badge/Anki-23.10%2B-orange">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB">
</p>

Ask Claude for an `.apkg` or a CSV and you get text, because it can't put a picture into either.
This one talks to Anki directly, so a card about a graph algorithm actually shows the graph, and a
card about a lecture figure shows the figure. Cards come from slides, PDFs, YouTube videos or
whatever you paste in. It runs locally against your Anki, and nothing touches your collection
until you say yes.

> Unofficial. Not affiliated with Ankitects.

https://github.com/user-attachments/assets/68d1f24f-7f6c-480d-aa16-c312484f873b

https://github.com/user-attachments/assets/00ac5217-9e81-4b8c-8479-c9aa38729dc4

## What it does

- **Real pictures, on the cards.** Graphs, trees and automata through Graphviz, figures cut out of
  your PDF by caption, matplotlib plots, and image occlusion with masks placed from the PDF's text
  layer instead of guessed from pixels. Claude looks for the spots where a picture makes the card
  better (a diagram the exam keeps asking about). If the slides already have a good one, it crops
  that instead of redrawing it.
- **Cards with rules.** One fact per card, no yes/no questions, lists become clozes. The wording
  follows [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing), so
  the cards don't sound like a chatbot.
- **You approve everything.** Claude shows every card, you say what to change, then it commits.
  Or tell it to commit directly and it skips printing them.
- **Fixes what you fail.** It ranks your cards by again rate, lapses, FSRS difficulty and leeches,
  works out why they fail and rewrites them without losing the review history.
- **A whole course at once.** `/anki:exam-prep` takes slides, exercise sheets and past exams and
  builds a deck weighted by what the exams actually ask.
- **Undo.** Every change returns a batch id. `undo` reverts it.

## Setup

You need macOS or Linux, Anki with [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
(code `2055492159`, restart Anki), and Claude Code or the Claude desktop app. With Anki 25.07+
there's nothing else to install. On older Anki (23.10+), get [uv](https://docs.astral.sh/uv/).
[Graphviz](https://graphviz.org/download/) is optional, for graphs.

```
/plugin marketplace add MichaelPrutkow/anki-for-claude
/plugin install anki@michaelprutkow
```

Desktop app: *Customize → Plugins → Add → Add marketplace*, enter `MichaelPrutkow/anki-for-claude`.

Then say "check my Anki setup". First start takes up to a minute while dependencies download.
In the desktop app, add a folder to the chat first, otherwise it doesn't reliably reach the server.

**Back up your collection first** (*File → Export → Anki Collection Package*). This writes to the
real thing.

## Usage

> Make flashcards from this lecture for my deck Analysis 2.

| Skill | For |
| --- | --- |
| `/anki:create-cards` | cards from any material |
| `/anki:visuals` | graphs, PDF figures, plots, image occlusion |
| `/anki:improve-cards` | find and fix weak cards, search, delete, undo |
| `/anki:exam-prep` | a whole course into a prioritised deck |
| `/anki:check-setup` | check Anki, AnkiConnect, Graphviz |

Claude picks the skill itself. The slash commands force one.

## Tools

Draft tools only touch drafts and pictures. Only the last six write to your collection.

| Tool | |
| --- | --- |
| `overview`, `search_notes`, `stats` | read decks, notes and review stats |
| `draft_add`, `draft_edit`, `draft_show`, `draft_add_occlusion` | build and review a draft |
| `stage_image`, `pdf_figures`, `render_graph` | pictures for cards |
| `youtube_transcript` | transcript or outline of a video |
| `draft_commit`, `update_notes`, `delete_notes`, `undo`, `math_css`, `sync` | write |

It never adds unapproved cards, deletes notes it didn't create, or opens anything except images
and PDFs. Edits to foreign notes need your OK.

## Privacy

Runs on your machine, nothing goes to me. It talks to AnkiConnect on `127.0.0.1`. Drafts and the
undo journal live in `~/.anki-mcp`, pictures in `~/Pictures/Anki for Claude`. Only when you ask:
a video id goes to YouTube, an image URL gets fetched, Anki syncs to AnkiWeb. Full version in
[PRIVACY.md](PRIVACY.md).

## Known limits

- An open dialog in Anki blocks AnkiConnect until you close it.
- Claude Code and Cowork only. A plain chat can't reach a local server.
- Anki only auto-starts on macOS. No Windows yet.
- Near-duplicates are flagged, not blocked, and only against the newest 1500 notes of a deck.
- Deleting can't be undone. Fix the card instead.
- Image occlusion is rectangles only.

## Other MCP clients

The server also works without the plugin (Cursor etc.). You get the tools, not the skills.

```bash
git clone https://github.com/MichaelPrutkow/anki-for-claude.git
cd anki-for-claude && uv sync --no-dev
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
uv run pytest                                   # against a fake AnkiConnect, no Anki needed
ANKI_LIVE=1 uv run pytest tests/test_live_anki.py   # read-only smoke test against real Anki
claude --plugin-dir .                           # try it in Claude Code
claude plugin eval .                            # with vs. without the plugin, mocked tools
```

After changing dependencies, regenerate `requirements.txt` (the launcher installs from it
without uv):

```bash
uv export --frozen --no-dev --no-emit-project --format requirements-txt --quiet > requirements.txt
```

## Credits

[AnkiConnect](https://git.sr.ht/~foosoft/anki-connect),
[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api),
[pdfplumber](https://github.com/jsvine/pdfplumber), [Pillow](https://python-pillow.org),
[Graphviz](https://graphviz.org), [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

MIT, by [Michael Prutkow](https://prutkow.com).
