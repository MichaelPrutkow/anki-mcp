<p align="center">
  <img src=".claude-plugin/icon.png" alt="" width="96">
</p>

<h1 align="center">Anki MCP</h1>

<p align="center">
  Anki cards with real pictures, written by Claude: graphs, PDF figures, plots and image occlusion,
  straight into your collection.
</p>

<p align="center">
  <a href="https://github.com/MichaelPrutkow/anki-mcp/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/MichaelPrutkow/anki-mcp/actions/workflows/tests.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-green"></a>
  <img alt="Anki 23.10+" src="https://img.shields.io/badge/Anki-23.10%2B-orange">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB">
</p>

When I ask Claude for an `.apkg` or a `.csv`, I get text-only cards. This plugin talks to Anki
directly, so a card about a graph algorithm shows the graph and a card about a lecture figure shows
the figure. It works from slides, PDFs, YouTube videos or whatever you paste in. Nothing lands in
your collection until you say yes, unless you turn off approval and let it commit directly. That
saves output tokens and lets you automate the whole thing, e.g. with scheduled tasks, no human in
the loop.

> Unofficial. Not affiliated with Ankitects.

*Both demos are from an older version, before picture support.*

https://github.com/user-attachments/assets/68d1f24f-7f6c-480d-aa16-c312484f873b

https://github.com/user-attachments/assets/00ac5217-9e81-4b8c-8479-c9aa38729dc4

## What it does

- **Pictures.** Graphs, trees and automata (Graphviz), figures cropped from your PDF, plots, and
  image occlusion. Claude looks for spots where a picture makes the card better, like a diagram the
  exam keeps asking about. If the slides already have a good one, it just crops that.
- **Cards with rules.** One fact per card, no yes/no questions, lists become clozes. The wording
  follows [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing), so
  the cards don't read like a chatbot.
- **You approve everything.** Claude shows every card first. Change what you want, then it adds
  them. Say "commit directly" to skip that.
- **Fixes cards you keep failing.** It ranks your cards by again rate, lapses, FSRS difficulty and
  leeches, figures out why they fail and rewrites them. Review history stays.
- **Whole courses.** `/anki:exam-prep` takes slides, exercise sheets and past exams and builds a
  deck weighted by what the exams actually ask.
- **Undo.** Every change gets a batch id, `undo` reverts it.

## Setup

You need macOS or Linux, Anki with [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
(code `2055492159`, restart Anki afterwards) and Claude Code or the Claude desktop app. Anki 25.07+
needs nothing else. On older versions (23.10+) install [uv](https://docs.astral.sh/uv/).
[Graphviz](https://graphviz.org/download/) is optional, only for graphs.

Add my marketplace, [`MichaelPrutkow/anki-mcp`](https://github.com/MichaelPrutkow/anki-mcp), and
install the plugin from it.

Claude Code:

```
/plugin marketplace add MichaelPrutkow/anki-mcp
/plugin install anki@michaelprutkow
```

Desktop app: *Customize → Plugins → Add → Add marketplace*, enter `MichaelPrutkow/anki-mcp`.

Then say "check my Anki setup". The first start takes up to a minute while the dependencies
download.

It's recommended to **back up your collection first** (*File → Export → Anki Collection Package*).
This writes to your real collection.

## Other MCP clients

The server also works without the plugin (Cursor etc.). You get the tools, not the skills.

```bash
git clone https://github.com/MichaelPrutkow/anki-mcp.git
cd anki-mcp && uv sync --no-dev
```

```json
{
  "mcpServers": {
    "anki": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/anki-mcp", "--no-dev", "-m", "anki_mcp"]
    }
  }
}
```

## Settings

Most setups need none. Both are environment variables of the server:

| Variable | For |
| --- | --- |
| `ANKI_CONNECT_URL` | AnkiConnect on another address than `http://127.0.0.1:8765` |
| `ANKI_CONNECT_API_KEY` | the `apiKey` you set in AnkiConnect's config |

## Usage

> Make flashcards from this lecture for my deck Analysis 2.

| Skill | For |
| --- | --- |
| `/anki:create-cards` | cards from any material |
| `/anki:visuals` | graphs, PDF figures, plots, image occlusion |
| `/anki:improve-cards` | find and fix weak cards, search, delete, undo |
| `/anki:exam-prep` | a whole course into a prioritised deck |
| `/anki:check-setup` | check Anki, AnkiConnect, Graphviz |

Claude picks the skill itself. The slash commands force one, and `/anki:exam-prep` only runs that
way.

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
and PDFs. It changes your own notes only when you ask for that change or agree to its proposal.

## Privacy

Everything runs on your machine, nothing goes to me. It talks to AnkiConnect on `127.0.0.1`.
Drafts and the undo journal live in `~/.anki-mcp`, pictures in `~/Pictures/Anki MCP`. Only when you
ask: a video id goes to YouTube, an image URL gets fetched, Anki syncs to AnkiWeb. Full version in
[PRIVACY.md](PRIVACY.md).

## Known limits

- No Windows yet.
- Claude Code and Cowork only. A plain chat can't reach a local server.
- An open dialog in Anki blocks AnkiConnect until you close it.
- Anki starts on its own on macOS, and on Linux if the `anki` command exists.
- Near-duplicates are flagged, not blocked, and only against the newest 1500 notes of a deck.
- Undoing a delete brings the card back, not its review history. Fix wrong cards instead.
- Image occlusion is rectangles only.

## Contributing

Bug reports and ideas are welcome as [issues](https://github.com/MichaelPrutkow/anki-mcp/issues).
How to run the tests and the evals is in [CONTRIBUTING.md](CONTRIBUTING.md), changes per version in
[CHANGELOG.md](CHANGELOG.md).

## Credits

[AnkiConnect](https://git.sr.ht/~foosoft/anki-connect),
[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api),
[pdfplumber](https://github.com/jsvine/pdfplumber), [Pillow](https://python-pillow.org),
[Graphviz](https://graphviz.org), [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

MIT, by [Michael Prutkow](https://prutkow.com).
