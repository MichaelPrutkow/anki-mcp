"""Smoke test against the real AnkiConnect, for changes in AnkiConnect or Anki that the fake cannot show.

    ANKI_LIVE=1 uv run pytest tests/test_live_anki.py -v

Anki must be open. The test only reads: drafts go to a temporary folder, nothing is committed, synced or styled.
"""

import os
import re
from collections.abc import AsyncGenerator

import pytest
from mcp.client import Client

from anki_mcp import collection, drafts, images, stats, youtube  # noqa: F401  importing registers the tools
from anki_mcp.server import mcp

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not os.environ.get("ANKI_LIVE"), reason="set ANKI_LIVE=1 with Anki open"),
]


@pytest.fixture
async def live(monkeypatch: pytest.MonkeyPatch, tmp_path) -> AsyncGenerator[Client, None]:
    monkeypatch.setenv("HOME", str(tmp_path))  # drafts, journal and images go to a temporary folder
    async with Client(mcp) as c:
        yield c


async def text_of(client: Client, tool: str, **args) -> str:
    result = await client.call_tool(tool, args)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    assert not result.is_error, text
    return text


async def test_reading_tools_work_against_the_real_anki(live: Client) -> None:
    overview = await text_of(live, "overview")
    assert "Decks (full name: cards including subdecks" in overview, overview
    assert "Note types (name [kind]: fields in order):" in overview
    first_deck = re.search(r"^(.+?): \d+ cards", overview, re.MULTILINE)
    if first_deck:
        assert "cards" in await text_of(live, "overview", deck=first_deck[1])
        await text_of(live, "search_notes", query=f'"deck:{first_deck[1]}"', limit=3)
    assert "Did you mean" in await text_of(
        live, "overview", deck="Some Parent::" + (first_deck[1] if first_deck else "X")
    )
    assert "Scope:" in await text_of(live, "stats", days=30, weak_limit=3)


async def test_a_draft_is_checked_but_never_committed(live: Client) -> None:
    card = {"fields": {"Front": "Smoke test \\(\text{x}\\) <- ignore", "Back": "\\(a<b\\)"}}
    text = await text_of(live, "draft_add", cards=[card], deck="Smoke Test Deck", note_type="Basic", echo=False)
    assert "Repaired" in text and "New deck, created by draft_commit: Smoke Test Deck" in text, text
    draft = re.search(r"d_[0-9a-f]{6}", text)
    assert draft
    gone = await text_of(live, "draft_edit", draft_id=draft[0], edits=[{"card": 1, "remove": True}])
    assert "no cards left and was deleted" in gone
