# Privacy policy

*Anki MCP, last updated 24 November 2026*

Anki MCP is a Claude plugin and MCP server that runs on your own computer. It has no account, no
analytics and no telemetry. It sends nothing to me or to anyone else for tracking.

## Your Anki collection

The server talks to your running Anki through the AnkiConnect add-on on `http://127.0.0.1:8765`, or
the address you set in `ANKI_CONNECT_URL`. Your cards and your review history stay on your computer.
The plugin only changes your collection when Claude calls one of its writing tools, and it only
deletes notes it created itself.

## Files on your computer

- **Drafts**, cards that are not in Anki yet: `~/.anki-mcp/drafts`. A draft is deleted when all its
  cards are added, or after 14 days.
- **Undo journal**: `~/.anki-mcp/journal.jsonl`. For every change it keeps the note ids and the fields
  before and after, and for deleted notes their content, so the change can be undone.
- **Pictures** for cards: `~/Pictures/Anki MCP`. Anki gets a copy when a card that uses one is added.
- **Exports**: a Markdown file, only when you ask for one and only at the path you name.
- **Dependencies**: if uv is not installed, a Python environment in the plugin's data folder.

To remove everything, uninstall the plugin and delete `~/.anki-mcp` and `~/Pictures/Anki MCP`. The
cards it added carry the tag `mcp::created` in Anki.

## Network

The plugin connects to the internet only in these cases:

- **First start**: uv or pip downloads the plugin's dependencies from the Python Package Index
  (pypi.org). The same happens once for matplotlib if Claude draws a plot and it is not installed.
- **YouTube**: when you ask for a video, `youtube_transcript` sends the video's id to YouTube to get
  its transcript.
- **Image URLs**: when you give an image by its web address, `stage_image` downloads it from there.
- **AnkiWeb**: when you ask for it, `sync` makes Anki sync with AnkiWeb under your own Anki account.

## Claude

What the tools return, for example your cards, your review statistics or text from a PDF, becomes part
of your conversation with Claude. Anthropic handles that conversation under its own
[privacy policy](https://www.anthropic.com/legal/privacy).

## Contact

Open an issue at https://github.com/MichaelPrutkow/anki-mcp/issues or write to
[michael.prutkow@tum.de](mailto:michael.prutkow@tum.de).
