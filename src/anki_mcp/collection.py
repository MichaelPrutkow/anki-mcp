import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from anki_mcp.anki import AnkiError, AnkiTimeout, similar_decks
from anki_mcp.images import dot_command, local_images, replace_images, upload_images
from anki_mcp.server import BATCH_PREFIX, CREATED_TAG, OVERWRITES, READ_ONLY, STYLES, SYNC, App, Ctx, app, tool
from anki_mcp.text import lint, repair, strip_html, to_markdown, truncate

MAX_EXPORT = 2000
EXPORT_MARK = "<!-- Exported from Anki by anki-mcp."
OLD_EXPORT_MARK = "<!-- Exported from Anki by anki-for-claude."  # before version 3
EDIT_SLACK = 60  # seconds between adding a note and a change that counts as the user's edit


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class Journal:
    """Append-only log of commits, updates and undos, so batches can be reverted."""

    def __init__(self, path: Path):
        self._path = path

    def append(self, entry: dict[str, Any]) -> None:
        line = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **entry}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


@tool("Decks and note types", READ_ONLY)
async def overview(
    ctx: Ctx, deck: Annotated[str | None, Field(description="Only this deck and its subdecks")] = None
) -> str:
    """The decks with their card counts and the note types with their exact field names. Call it before drafting."""
    a = app(ctx)
    ids: dict[str, int] = await a.anki.invoke("deckNamesAndIds")
    note = ""
    if deck:
        want = deck.strip().strip(":").lower()
        # Every deck whose name contains it, anywhere in the tree: "GDB" finds "TUM::GDB" and its subdecks,
        # "Analysis" finds "Math::Analysis" and "TUM::Analysis 1".
        matches = {n: i for n, i in ids.items() if want in n.lower()}
        if not any(n.lower() == want or n.lower().endswith("::" + want) for n in matches):
            note = f"No deck is named '{deck}'."
        if not matches and (similar := similar_decks(deck, ids)):
            note += " Did you mean " + " or ".join(f"'{s}'" for s in similar) + "?"
            matches = {n: i for n, i in ids.items() if any(n == s or n.startswith(s + "::") for s in similar)}
        elif not matches:
            # Never fail here: an error makes Claude guess deck names again and again. Show what exists instead.
            note += f" These are all decks: pick one, or draft_add creates '{deck}' ('Parent::{deck}' for a subdeck)."
            matches = ids
        elif note:
            note += f" These decks contain '{deck}' in their name:"
        ids = matches
    # getDeckStats is keyed by deck id and counts only the deck itself, without its subdecks.
    # One call per deck: Anki hides an empty "Default" deck from its tree, and that must not fail everything.
    try:
        results = await a.anki.multi([("getDeckStats", {"decks": [name]}) for name in ids])
    except AnkiError as exc:
        results = [exc] * len(ids)
    by_name: dict[str, Any] = {}
    for name, deck_id, result in zip(ids, ids.values(), results, strict=True):
        by_name[name] = None if isinstance(result, AnkiError) else result.get(str(deck_id), {})

    lines = [note, ""] if note else []
    if all(stats is None for stats in by_name.values()):
        lines.append("Decks (AnkiConnect gave no card counts): " + ", ".join(sorted(by_name, key=str.lower)))
    else:
        lines.append("Decks (full name: cards including subdecks, due today, new today):")
        empty: list[str] = []
        for name in sorted(by_name, key=str.lower):
            tree = [s or {} for n, s in by_name.items() if n == name or n.startswith(name + "::")]
            total = sum(s.get("total_in_deck", 0) for s in tree)
            if total == 0:
                if name != "Default":
                    empty.append(name)
                continue
            s = by_name[name] or {}
            due = s.get("learn_count", 0) + s.get("review_count", 0)
            lines.append(f"{name}: {total} cards, {due} due, {s.get('new_count', 0)} new")
        if empty:
            lines.append("Empty decks: " + ", ".join(empty))

    lines += ["", "Note types (name [kind]: fields in order):"]
    for nt in sorted(await a.note_types.all(), key=lambda n: n.name.lower()):
        lines.append(f"{nt.name} [{nt.label}]: " + " | ".join(nt.fields))
    if not dot_command():
        lines += ["", "Graphviz is not installed, so render_graph does not work (macOS: brew install graphviz)."]
    return "\n".join(lines)


@tool("Search notes", READ_ONLY)
async def search_notes(
    ctx: Ctx,
    query: Annotated[str, Field(description="Anki search, e.g. 'deck:GAD tag:heap' or 'nid:1234'")],
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    fields: Annotated[list[str] | None, Field(description="Only show these fields")] = None,
    max_chars: Annotated[int, Field(ge=20, le=2000, description="Characters shown per field")] = 120,
    save_to: Annotated[
        str | None,
        Field(
            description="Instead of listing: write every match (up to 2000) in full as Markdown to this file, "
            "an absolute path ending in .md, e.g. for notes or a summary"
        ),
    ] = None,
) -> str:
    """Find notes with Anki's search syntax. One line per note, newest first, or all of them into a Markdown file."""
    a = app(ctx)
    ids = sorted(await a.anki.invoke("findNotes", query=query), reverse=True)
    if not ids:
        return f"No notes match '{query}'. If you expected hits, check the search syntax."
    if save_to:
        return await _export(a, query, ids, save_to)

    shown = ids[:limit]
    wanted = {f.lower() for f in fields} if fields else None
    lines = [f"{len(ids)} notes match '{query}', showing the newest {len(shown)}:"]
    for note in await a.anki.invoke("notesInfo", notes=shown):
        if not note:
            continue
        parts = []
        for name, field in sorted(note["fields"].items(), key=lambda kv: kv[1]["order"]):
            text = truncate(strip_html(field["value"]), max_chars)
            if text and (not wanted or name.lower() in wanted):
                parts.append(f"{name}: {text}")
        line = f"{note['noteId']} [{note['modelName']}] " + " | ".join(parts)
        tags = [t for t in note["tags"] if not t.startswith(BATCH_PREFIX)]
        if tags:
            line += " | tags: " + " ".join(tags)
        lines.append(line)
    return "\n".join(lines)


def _export_path(save_to: str) -> Path:
    path = Path(save_to).expanduser()
    if not path.is_absolute() or path.suffix.lower() != ".md":
        raise ToolError(f"'{save_to}': save_to needs an absolute path on the user's computer ending in .md.")
    if not path.parent.is_dir():
        raise ToolError(f"The folder {path.parent} does not exist.")
    ours = (EXPORT_MARK, OLD_EXPORT_MARK)
    if path.exists() and not path.read_text(encoding="utf-8", errors="replace").startswith(ours):
        raise ToolError(f"{path} exists and was not written by this tool. Pick another file name.")
    return path


async def _export(a: App, query: str, ids: list[int], save_to: str) -> str:
    """All matching notes in full, as Markdown, oldest first: the order in which they were added."""
    path = _export_path(save_to)
    chosen = sorted(ids)[:MAX_EXPORT]
    lines = [f"{EXPORT_MARK} Search: {query} -->", ""]
    for number, info in enumerate(await a.anki.invoke("notesInfo", notes=chosen), start=1):
        if not info:
            continue
        nt = await a.note_types.get(info["modelName"])
        hidden = (nt.io_fields or {}).get("occlusion")  # the masks of an image occlusion note are not text
        lines += [f"## {number}", ""]
        for name, field in sorted(info["fields"].items(), key=lambda kv: kv[1]["order"]):
            if field["value"].strip() and name != hidden:
                lines += [f"**{name}:** {to_markdown(field['value'])}", ""]
        tags = [t for t in info["tags"] if t != CREATED_TAG and not t.startswith(BATCH_PREFIX)]
        lines += [
            f"*{info['modelName']}, note {info['noteId']}" + (f", tags {' '.join(tags)}" if tags else "") + "*",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")
    rest = (
        f" The {len(ids) - len(chosen)} newest matches are missing: narrow the search."
        if len(ids) > len(chosen)
        else ""
    )
    return f"Wrote {_count(len(chosen), 'note')} matching '{query}' to {path}.{rest}"


class UpdateIn(BaseModel):
    note_id: int
    fields: dict[str, str] = Field(description="Only the fields that change, with their full new content")


@tool("Update notes", OVERWRITES)
async def update_notes(
    ctx: Ctx,
    updates: Annotated[list[UpdateIn], Field(min_length=1, max_length=50)],
    force: Annotated[
        bool, Field(description="Needed for notes the user wrote: only for a change the user asked for")
    ] = False,
) -> str:
    """Change fields of existing notes. Keeps the review history, so prefer it over deleting and re-adding.

    Notes not created by this plugin need force=true: only for a change the user asked for, otherwise ask them
    first. Returns a batch id for undo.
    """
    a = app(ctx)
    infos = await a.anki.invoke("notesInfo", notes=[u.note_id for u in updates])

    errors: list[str] = []
    repairs: list[str] = []
    warnings: list[str] = []
    planned: list[tuple[int, dict[str, str], dict[str, str]]] = []
    for update, info in zip(updates, infos, strict=True):
        if not info:
            errors.append(f"{update.note_id}: there is no such note")
            continue
        if CREATED_TAG not in info["tags"] and not force:
            errors.append(
                f"{update.note_id}: the user wrote this note. If they asked for this change, call again with "
                "force=true; otherwise ask them first"
            )
            continue
        nt = await a.note_types.get(info["modelName"])
        fields, unknown = nt.normalize(update.fields)
        if unknown:
            errors.append(f"{update.note_id}: unknown fields {unknown}. {nt.name} has: {', '.join(nt.fields)}")
            continue
        done = []
        for name, value in list(fields.items()):
            fields[name], what = repair(value)
            if what:
                done.append(f"{name} {', '.join(what)}")
        if done:
            repairs.append(f"{update.note_id} " + "; ".join(done))
        if nt.kind != "io":
            warnings += [f"{update.note_id} {problem}" for problem in lint(fields)]
        before = {name: info["fields"][name]["value"] for name in fields}
        planned.append((update.note_id, fields, before))
    if errors:
        raise ToolError("Nothing was changed:\n" + "\n".join(errors))

    # Images new to a note come from the images folder; images it already had are in Anki already.
    new_images = sorted(
        {
            name
            for _, fields, before in planned
            for value in fields.values()
            for name in local_images(value)
            if a.images.has(name) and not any(name in local_images(old) for old in before.values())
        }
    )
    stored = await upload_images(a, new_images)
    if len(stored) < len(new_images):
        raise ToolError("Nothing was changed: could not copy " + ", ".join(sorted(set(new_images) - set(stored))))
    planned = [(nid, {k: replace_images(v, stored) for k, v in f.items()}, before) for nid, f, before in planned]

    results = await a.anki.multi(
        [("updateNoteFields", {"note": {"id": nid, "fields": fields}}) for nid, fields, _ in planned]
    )
    after = await a.anki.invoke("notesInfo", notes=[nid for nid, _, _ in planned])

    applied: list[dict[str, Any]] = []
    problems: list[str] = []
    for (nid, fields, before), result, info in zip(planned, results, after, strict=True):
        if isinstance(result, AnkiError):
            problems.append(f"{nid}: {result}")
        elif all(info["fields"][name]["value"] == value for name, value in fields.items()):
            applied.append({"note_id": nid, "before": before, "after": fields, "mod_after": info["mod"]})
        else:
            problems.append(f"{nid}: not saved. Is the note open in Anki's browser or editor?")

    lines = []
    if applied:
        batch_id = uuid4().hex[:8]
        a.journal.append({"batch_id": batch_id, "kind": "update", "updated": applied})
        noun = "note" if len(applied) == 1 else "notes"
        lines.append(f'Updated {len(applied)} {noun}. Batch id {batch_id}: undo("{batch_id}") restores them.')
    if problems:
        lines += ["Not updated:", *problems]
    if repairs:
        lines += ["Repaired (LaTeX that lost its backslash in JSON, a '<' HTML would misread):", *repairs]
    if warnings:
        lines += ["Possible formatting problems, fix the real ones with update_notes:", *warnings]
    return "\n".join(lines)


@tool("Delete notes", OVERWRITES)
async def delete_notes(
    ctx: Ctx,
    note_ids: Annotated[list[int], Field(min_length=1, max_length=100)],
) -> str:
    """Delete notes created by this plugin. Their review history is lost for good.

    Only for cards that should not exist at all; fix wrong cards with update_notes instead. Returns a batch id:
    undo adds the notes back with their fields, tags and deck, but without the review history.
    """
    a = app(ctx)
    infos = await a.anki.invoke("notesInfo", notes=note_ids)
    missing = [nid for nid, info in zip(note_ids, infos, strict=True) if not info]
    foreign = [nid for nid, info in zip(note_ids, infos, strict=True) if info and CREATED_TAG not in info["tags"]]
    if missing or foreign:
        lines = ["Nothing was deleted."]
        if missing:
            lines.append(f"No such notes: {missing}")
        if foreign:
            lines.append(f"Written by the user, so this plugin does not delete them: {foreign}")
        raise ToolError("\n".join(lines))
    # Keep what undo needs to add the notes back: fields, tags and the deck of each note's first card.
    first_cards = [info["cards"][0] if info.get("cards") else None for info in infos]
    card_infos = await a.anki.invoke("cardsInfo", cards=[c for c in first_cards if c is not None])
    deck_of = {card["cardId"]: card["deckName"] for card in card_infos if card}
    deleted = [
        {
            "note_id": info["noteId"],
            "deck": deck_of.get(card, "Default"),
            "note_type": info["modelName"],
            "fields": {name: field["value"] for name, field in info["fields"].items()},
            "tags": info["tags"],
        }
        for info, card in zip(infos, first_cards, strict=True)
    ]
    await a.anki.invoke("deleteNotes", notes=note_ids)
    batch_id = uuid4().hex[:8]
    a.journal.append({"batch_id": batch_id, "kind": "delete", "deleted": deleted})
    return (
        f'Deleted {_count(len(note_ids), "note")}. Batch id {batch_id}: undo("{batch_id}") adds '
        f"{'it' if len(note_ids) == 1 else 'them'} back, without the review history."
    )


async def _undo_commit(a: App, batch_id: str, force: bool, known: bool) -> tuple[str, list[int]]:
    """Delete the notes of a commit, except those the user studied or edited since (unless forced)."""
    batch = f"tag:{BATCH_PREFIX}{batch_id}"
    ids = await a.anki.invoke("findNotes", query=batch)
    if not ids and not known:
        raise ToolError(f"There is no batch '{batch_id}'.")
    kept: list[int] = []
    if ids and not force:
        studied = set(await a.anki.invoke("findNotes", query=f"{batch} -is:new"))
        # A note id is the time the note was added, in milliseconds; mod is the time of its last change, in seconds.
        infos = await a.anki.invoke("notesInfo", notes=ids)
        edited = {info["noteId"] for info in infos if info and info["mod"] > info["noteId"] // 1000 + EDIT_SLACK}
        kept = sorted(studied | edited)
    delete = [nid for nid in ids if nid not in kept]
    if delete:
        await a.anki.invoke("deleteNotes", notes=delete)
    message = f"Undid batch {batch_id}: deleted {_count(len(delete), 'note')}."
    if kept:
        message += (
            f" Left alone because the user studied or edited them since: {kept}. undo with force=true deletes them "
            "too, review history included: ask the user first."
        )
    return message, kept


async def _undo_delete(a: App, batch_id: str, entry: dict[str, Any]) -> str:
    """Add deleted notes back as new notes: same fields, tags and deck, but no review history."""
    notes = entry["deleted"]
    decks = set(await a.anki.invoke("deckNames"))
    for deck in sorted({note["deck"] for note in notes} - decks):
        await a.anki.invoke("createDeck", deck=deck)
    calls = [
        (
            "addNote",
            {
                "note": {
                    "deckName": note["deck"],
                    "modelName": note["note_type"],
                    "fields": note["fields"],
                    "tags": note["tags"],
                    "options": {"allowDuplicate": True},
                }
            },
        )
        for note in notes
    ]
    results = await a.anki.multi(calls)
    added = [result for result in results if isinstance(result, int)]
    message = f"Undid batch {batch_id}: added {_count(len(added), 'deleted note')} back, without review history."
    failed = [
        f"{note['note_id']}: {result}"
        for note, result in zip(notes, results, strict=True)
        if not isinstance(result, int)
    ]
    if failed:
        message += " Could not add back: " + "; ".join(failed)
    return message


async def _undo_styling(a: App, batch_id: str, entry: dict[str, Any]) -> str:
    restored, changed = [], []
    for item in entry["styled"]:
        try:
            current = (await a.anki.invoke("modelStyling", modelName=item["note_type"]))["css"]
        except AnkiError:
            continue
        if current != item["after"]:
            changed.append(item["note_type"])
            continue
        await a.anki.invoke("updateModelStyling", model={"name": item["note_type"], "css": item["before"]})
        restored.append(item["note_type"])
    message = f"Undid batch {batch_id}: removed the formula CSS from {', '.join(restored) or 'no note type'}."
    if changed:
        message += f" Left alone because their styling was changed since: {', '.join(changed)}."
    return message


@tool("Undo a batch", OVERWRITES)
async def undo(
    ctx: Ctx,
    batch_id: str,
    force: Annotated[
        bool,
        Field(description="Commits only: also delete notes studied or edited since, with their history. Ask first"),
    ] = False,
) -> str:
    """Revert a draft_commit, update_notes, delete_notes or math_css by its batch id: added notes are deleted,
    changed fields and styling restored, deleted notes added back without their review history.

    Notes the user studied or edited since are left alone and listed.
    """
    a = app(ctx)
    entries = a.journal.entries()
    entry = next((e for e in reversed(entries) if e.get("batch_id") == batch_id and e["kind"] != "undo"), None)
    is_commit = entry is None or entry["kind"] == "commit"
    undone = [e for e in entries if e.get("undo_of") == batch_id]
    if undone and not (force and is_commit):
        message = f"Batch {batch_id} was already undone."
        if is_commit and undone[-1].get("kept"):
            message += " Some notes were left alone then; undo with force=true deletes them too (ask the user first)."
        raise ToolError(message)

    kept: list[int] = []
    if is_commit:
        message, kept = await _undo_commit(a, batch_id, force, known=entry is not None or bool(undone))
    elif entry["kind"] == "styling":
        message = await _undo_styling(a, batch_id, entry)
    elif entry["kind"] == "delete":
        message = await _undo_delete(a, batch_id, entry)
    else:
        updates = entry["updated"]
        infos = await a.anki.invoke("notesInfo", notes=[u["note_id"] for u in updates])
        restore, conflicts = [], []
        for update, info in zip(updates, infos, strict=True):
            if not info:
                continue
            if info["mod"] != update["mod_after"]:
                conflicts.append(update["note_id"])
            else:
                restore.append(("updateNoteFields", {"note": {"id": update["note_id"], "fields": update["before"]}}))
        if restore:
            await a.anki.multi(restore)
        message = f"Undid batch {batch_id}: restored {len(restore)} {'note' if len(restore) == 1 else 'notes'}."
        if conflicts:
            message += f" Left alone because they were edited since: {conflicts}."

    a.journal.append({"batch_id": uuid4().hex[:8], "kind": "undo", "undo_of": batch_id, "kept": kept})
    return message


MATH_CSS_MARK = "/* anki-mcp: long formulas"
OLD_MATH_CSS_MARK = "/* anki-for-claude: long formulas"  # before version 3
MATH_CSS = f"""
{MATH_CSS_MARK} scroll sideways instead of running off the card on a phone */
mjx-container[display="true"] {{
  overflow-x: auto;
  overflow-y: hidden;
  max-width: 100%;
  padding: 0.5em 0;
  margin: 0.5em 0 !important; /* half of MathJax's 1em moves inside, so tall formulas are not cut off */
}}
/* end anki-mcp */
"""


@tool("Let long formulas scroll on phones", STYLES)
async def math_css(
    ctx: Ctx,
    note_types: Annotated[list[str], Field(min_length=1, description="Note types to style, e.g. ['Basic', 'Cloze']")],
) -> str:
    """Add CSS to note types so that a display formula wider than the screen scrolls sideways on a phone instead
    of running off the card. Only their styling changes. Returns a batch id for undo."""
    a = app(ctx)
    for name in note_types:
        await a.note_types.get(name)  # fails with the list of note types if one does not exist
    styled, already = [], []
    for name in note_types:
        before = (await a.anki.invoke("modelStyling", modelName=name))["css"]
        if MATH_CSS_MARK in before or OLD_MATH_CSS_MARK in before:
            already.append(name)
            continue
        await a.anki.invoke("updateModelStyling", model={"name": name, "css": before.rstrip() + "\n" + MATH_CSS})
        after = (await a.anki.invoke("modelStyling", modelName=name))["css"]
        styled.append({"note_type": name, "before": before, "after": after})
    lines = []
    if styled:
        batch_id = uuid4().hex[:8]
        a.journal.append({"batch_id": batch_id, "kind": "styling", "styled": styled})
        names = ", ".join(item["note_type"] for item in styled)
        lines.append(f'Long formulas now scroll in {names}. Batch id {batch_id}: undo("{batch_id}") removes it.')
    if already:
        lines.append(f"Already set up: {', '.join(already)}.")
    return " ".join(lines)


@tool("Sync with AnkiWeb", SYNC)
async def sync(ctx: Ctx) -> str:
    """Sync the collection with AnkiWeb, so new cards reach the user's phone and reviews from the phone count."""
    try:
        await app(ctx).anki.invoke("sync", timeout=50)
    except AnkiTimeout:
        return "The sync is taking longer than usual and continues in Anki."
    return "Synced with AnkiWeb."
