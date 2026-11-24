from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from mcp.server import MCPServer
from mcp.server.elicitation import render_elicitation_schema
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INTERNAL_ERROR,
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    InputRequiredResult,
    Tool,
    ToolAnnotations,
)
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from anki_mcp.anki import AnkiClient, NoteTypes
    from anki_mcp.collection import Journal
    from anki_mcp.drafts import DraftStore
    from anki_mcp.images import ImageStore

INSTRUCTIONS = """\
Tools for the user's own Anki collection. They run on the user's computer and can only open files there.
New cards (follow the 'create-cards' skill): overview -> draft_add -> show the returned cards to the user ->
draft_edit until they approve -> draft_commit. Nothing reaches Anki before draft_commit.
Existing cards: search_notes, update_notes (keeps the review history), stats for the cards the user struggles with.
Every change to the collection returns a batch id that undo reverts.
"""

CREATED_TAG = "mcp::created"
BATCH_PREFIX = "mcp::batch::"

logging.getLogger("httpx").setLevel(logging.WARNING)


def _annotations(read_only: bool, destructive: bool, idempotent: bool, web: bool = False) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=web,
    )


READ_ONLY = _annotations(True, False, True)
DRAFT = _annotations(True, False, False)  # changes drafts and images, never the collection
ADDS = _annotations(False, False, False)
OVERWRITES = _annotations(False, True, True)
STYLES = _annotations(False, False, True)  # adds CSS to note types, undo removes it
WEB_READ = _annotations(True, False, True, web=True)
SYNC = _annotations(False, False, True, web=True)


DEFAULT_ANKI_CONNECT_URL = "http://127.0.0.1:8765"


@dataclass
class App:
    anki: AnkiClient
    note_types: NoteTypes
    drafts: DraftStore
    journal: Journal
    images: ImageStore
    no_dialog: set[str] = field(default_factory=set)  # kinds of change the user said not to be asked about again


Ctx = Context[App]


def app(ctx: Ctx) -> App:
    return ctx.request_context.lifespan_context


class Confirmation(BaseModel):
    dont_ask_again: bool = Field(default=False, title="Don't ask again in this session")


def _can_ask(ctx: Ctx) -> bool:
    caps = ctx.request_context.session.client_capabilities
    elicitation = caps.elicitation if caps else None
    # A bare "elicitation: {}" from clients before 2025-11-25 means form mode.
    return elicitation is not None and (elicitation.form is not None or elicitation.url is None)


class _AskFirst(MCPError):
    """Ends the tool call with an InputRequiredResult: the client shows the dialog and calls the tool again."""

    def __init__(self, result: InputRequiredResult):
        super().__init__(INTERNAL_ERROR, "confirmation dialog")
        self.result = result


async def confirm(ctx: Ctx, kind: str, message: str) -> None:
    """Ask the user in a dialog of their client before a change; raise ToolError unless they accept.

    The server cannot see the chat, so this is the one approval that does not depend on the model. Clients
    without form elicitation show no dialog, and neither does a kind the user ticked "don't ask again" for.
    Call it before the first change of a tool call: from protocol 2026-07-28 on, the call ends here and the
    client calls the tool again with the user's answer, so everything before it runs twice.
    """
    a = app(ctx)
    if kind in a.no_dialog or not _can_ask(ctx):
        return
    if ctx.request_context.session.can_send_request:  # before 2026-07-28: the server asks the client directly
        try:
            result = await ctx.elicit(message, Confirmation)
        except Exception as e:  # the client failed to show it: better nothing changes than a change nobody saw
            raise ToolError(f"The confirmation dialog could not be shown ({e}). Nothing was changed.") from e
        accepted = result.data if result.action == "accept" else None
    else:
        response = (ctx.input_responses or {}).get(kind)
        if response is None:
            params = ElicitRequestFormParams(message=message, requested_schema=render_elicitation_schema(Confirmation))
            raise _AskFirst(InputRequiredResult(input_requests={kind: ElicitRequest(params=params)}))
        accepted = (
            Confirmation.model_validate(response.content or {})
            if getattr(response, "action", None) == "accept"
            else None
        )
    if accepted is None:
        raise ToolError(
            "The user did not confirm in the dialog, so nothing was changed. Do not call this again unless the "
            "user asks for it."
        )
    if accepted.dont_ask_again:
        a.no_dialog.add(kind)


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncGenerator[App, None]:
    from anki_mcp.anki import AnkiClient, NoteTypes
    from anki_mcp.collection import Journal
    from anki_mcp.drafts import DraftStore
    from anki_mcp.images import ImageStore

    data_dir = Path.home() / ".anki-mcp"
    data_dir.mkdir(parents=True, exist_ok=True)
    pictures = Path.home() / "Pictures" / "Anki MCP"
    old_pictures = Path.home() / "Pictures" / "Anki for Claude"  # the folder's name before version 3
    if old_pictures.is_dir() and not pictures.exists():
        old_pictures.rename(pictures)
    async with httpx.AsyncClient(timeout=30.0) as http:
        anki = AnkiClient(http, os.environ.get("ANKI_CONNECT_URL") or DEFAULT_ANKI_CONNECT_URL)
        yield App(
            anki=anki,
            note_types=NoteTypes(anki),
            drafts=DraftStore(data_dir / "drafts"),
            journal=Journal(data_dir / "journal.jsonl"),
            images=ImageStore(pictures),
        )


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace every $ref with the definition it points to and drop $defs."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {**target, **{k: resolve(v) for k, v in node.items() if k != "$ref"}}
        return {k: resolve(v) for k, v in node.items() if k != "$defs"}

    return resolve(schema)


class AnkiServer(MCPServer):
    async def list_tools(self) -> list[Tool]:
        # The Claude desktop app passes only "properties" and "required" of a tool schema on to chats,
        # so a $ref into "$defs" would point nowhere there.
        return [t.model_copy(update={"input_schema": inline_refs(t.input_schema)}) for t in await super().list_tools()]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[App, Any] | None = None
    ) -> CallToolResult | InputRequiredResult:
        try:
            return await super().call_tool(name, arguments, context)
        except _AskFirst as ask:
            return ask.result


def _version() -> str:
    try:
        return version("anki-mcp")
    except PackageNotFoundError:
        # Started from the source folder by server.py with Anki's Python, not installed by uv.
        with (Path(__file__).parents[2] / "pyproject.toml").open("rb") as f:
            return tomllib.load(f)["project"]["version"]


mcp = AnkiServer("anki", version=_version(), instructions=INSTRUCTIONS, lifespan=lifespan)


def tool(title: str, annotations: ToolAnnotations):
    """Register a tool that returns plain text (or text and images)."""
    return mcp.tool(title=title, annotations=annotations, structured_output=False)
