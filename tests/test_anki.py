import json
from typing import Any

import httpx
import pytest

from anki_mcp import anki as anki_module
from anki_mcp.anki import AnkiClient, AnkiError

pytestmark = pytest.mark.anyio


def answering(seen: list[dict[str, Any]], error: str | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"result": 6, "error": error})

    return httpx.MockTransport(handle)


async def test_a_missing_api_key_explains_the_fix() -> None:
    async with httpx.AsyncClient(transport=answering([], error="valid api key must be provided")) as http:
        with pytest.raises(AnkiError, match="clear apiKey"):
            await AnkiClient(http, "http://127.0.0.1:8765").invoke("deckNames")


async def test_anki_on_another_computer_is_not_started(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async def never(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("must not start a program")

    monkeypatch.setattr(anki_module.asyncio, "create_subprocess_exec", never)
    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as http:
        with pytest.raises(AnkiError, match="does not answer at http://192.168.1.5:8765"):
            await AnkiClient(http, "http://192.168.1.5:8765").invoke("deckNames")


async def test_anki_is_started_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if not started:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"result": ["Default"], "error": None})

    async def start(program: str, **kwargs: Any) -> None:
        assert kwargs["stdout"] == anki_module.asyncio.subprocess.DEVNULL
        started.append(program)

    monkeypatch.setattr(anki_module.sys, "platform", "linux")
    monkeypatch.setattr(anki_module.shutil, "which", lambda name: "/usr/bin/anki")
    monkeypatch.setattr(anki_module.asyncio, "create_subprocess_exec", start)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        assert await AnkiClient(http, "http://127.0.0.1:8765").invoke("deckNames") == ["Default"]
    assert started == ["/usr/bin/anki"]


async def test_note_types_load_right_after_the_computer_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        models = [{"name": "Basic", "type": 0, "flds": [{"name": "Front", "ord": 0}, {"name": "Back", "ord": 1}]}]
        result = ["Basic"] if body["action"] == "modelNames" else models
        return httpx.Response(200, json={"result": result, "error": None})

    monkeypatch.setattr(anki_module.time, "monotonic", lambda: 12.0)  # twelve seconds since boot, like a CI runner
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        note_types = anki_module.NoteTypes(AnkiClient(http, "http://127.0.0.1:8765"))
        assert [nt.name for nt in await note_types.all()] == ["Basic"]
