"""Drafts: cards that are checked against Anki but not yet added. The user approves them in the chat,
then draft_commit adds them."""

import asyncio
import os
import re
from collections import Counter
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from mcp.server.mcpserver import Image as McpImage
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from anki_mcp.anki import AnkiError, NoteType, deck_query, similar_decks
from anki_mcp.images import downscale, local_images, png_bytes, replace_images, upload_images
from anki_mcp.occlusion import Mask, build_field, draw_masks, find_label, parse_field
from anki_mcp.server import ADDS, BATCH_PREFIX, CREATED_TAG, DRAFT, READ_ONLY, App, Ctx, app, tool
from anki_mcp.stats import content_flags
from anki_mcp.text import cloze_ords, comparable, line_breaks_to_html, lint, readable, repair, strip_html, truncate

MAX_AGE = timedelta(days=14)
MAX_CARDS = 50
MAX_COMPARED = 1500  # newest notes per deck that new cards are compared with
SIMILAR = 0.85  # difflib ratio from which a card counts as a near-duplicate


class CardIn(BaseModel):
    fields: dict[str, str] = Field(description="Field name -> content (HTML), names exactly as overview lists them")
    tags: list[str] = Field(default=[], description="Tags for this card, on top of the call's tags")
    note_type: str | None = Field(default=None, description="Only if it differs from the call's note type")
    deck: str | None = Field(default=None, description="Only if it differs from the call's deck")


class DraftCard(BaseModel):
    n: int = 0
    deck: str
    note_type: str
    fields: dict[str, str]
    tags: list[str] = []  # every tag the note gets, apart from the plugin's own
    allow_duplicate: bool = False
    error: str | None = None  # why the last draft_commit of this card failed


class Draft(BaseModel):
    id: str
    title: str | None = None
    deck: str
    note_type: str
    tags: list[str] = []  # given to every card added to the draft
    updated: datetime
    next_n: int = 1
    cards: list[DraftCard] = []
    version: int = 1  # 2: every card holds all its tags. Before, the draft's tags were added at commit.


def _now() -> datetime:
    return datetime.now(UTC)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _merge_tags(*groups: list[str]) -> list[str]:
    """Tags in order, without repeats. Anki tags cannot contain spaces, so 'a b' is two tags."""
    return list(dict.fromkeys(tag for group in groups for item in group for tag in item.split()))


def _upgrade(draft: Draft) -> Draft:
    if draft.version < 2:
        for card in draft.cards:
            card.tags = _merge_tags(draft.tags, card.tags)
        draft.version = 2
    return draft


class DraftStore:
    """One JSON file per draft, so drafts survive restarts. Drafts untouched for 14 days are removed."""

    def __init__(self, root: Path):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}
        for draft in self.all():
            if not draft.cards or draft.updated < _now() - MAX_AGE:
                self.delete(draft.id)

    def create(self, **values: Any) -> Draft:
        draft = Draft(id="d_" + uuid4().hex[:6], updated=_now(), version=2, **values)
        self._save(draft)
        return draft

    def load(self, draft_id: str) -> Draft:
        path = self._path(draft_id)
        if not path.exists():
            raise ToolError(f"Draft '{draft_id}' does not exist. draft_show without an id lists the open drafts.")
        return _upgrade(Draft.model_validate_json(path.read_text(encoding="utf-8")))

    @asynccontextmanager
    async def edit(self, draft_id: str) -> AsyncGenerator[Draft, None]:
        async with self._locks.setdefault(draft_id, asyncio.Lock()):
            draft = self.load(draft_id)
            yield draft
            if draft.cards:
                draft.updated = _now()
                self._save(draft)
            else:
                self.delete(draft_id)

    def all(self) -> list[Draft]:
        drafts = []
        for path in self._root.glob("d_*.json"):
            try:
                drafts.append(_upgrade(Draft.model_validate_json(path.read_text(encoding="utf-8"))))
            except ValidationError:
                continue
        return sorted(drafts, key=lambda d: d.updated, reverse=True)

    def delete(self, draft_id: str) -> None:
        self._path(draft_id).unlink(missing_ok=True)

    def _path(self, draft_id: str) -> Path:
        if not re.fullmatch(r"d_[0-9a-f]{6}", draft_id):
            raise ToolError(f"'{draft_id}' is not a draft id. Draft ids look like 'd_1a2b3c'.")
        return self._root / f"{draft_id}.json"

    def _save(self, draft: Draft) -> None:
        path = self._path(draft.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(draft.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, path)


# --- cards as plain text -------------------------------------------------------------

CARDS_TEXT = (
    "Instead of 'cards': the cards as plain text, where LaTeX needs no doubled backslashes. Each card starts with "
    "a line '## <note type>', optionally '| deck: <name> | tags: <a b>' after it ('##' alone: the call's note "
    "type). Then 'Field: content' lines; a field runs until the next field name or '##', its line breaks become <br>"
)
_CARD_START = re.compile(r"^##(?!#)(.*)$")
_FIELD_LINE = re.compile(r"^\s*([^:\n]{1,80}?)\s*:[ \t]?(.*)$")


async def _parse_cards_text(a: App, text: str, note_type: str | None) -> list[CardIn]:
    types = {nt.name.lower(): nt for nt in await a.note_types.all()}
    blocks: list[tuple[int, str, list[tuple[int, str]]]] = []
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if m := _CARD_START.match(line):
            blocks.append((number, m[1], []))
        elif blocks:
            blocks[-1][2].append((number, line))
        elif line.strip():
            problems.append(f"line {number}: text before the first card. Each card starts with '## <note type>'")
    if not blocks and not problems:
        problems.append("no card. Each card starts with a line '## <note type>'")

    cards: list[CardIn] = []
    for index, (number, head, body) in enumerate(blocks, start=1):
        label = f"card {index} (line {number})"
        name, deck, tags = None, None, []
        for part in head.split("|"):
            key, colon, value = part.partition(":")
            if not colon:
                name = part.strip() or name
            elif key.strip().lower() == "deck":
                deck = value.strip()
            elif key.strip().lower() == "tags":
                tags = value.split()
            else:
                problems.append(f"{label}: '{part.strip()}' is not 'deck: <name>' or 'tags: <a b>'")
        nt = types.get((name or note_type or "").lower())
        if nt is None:
            wanted = f"no note type '{name or note_type}'" if name or note_type else "no note type"
            problems.append(f"{label}: {wanted}. Note types: {', '.join(sorted(t.name for t in types.values()))}")
            continue
        lookup = {field.lower(): field for field in nt.fields}
        fields: dict[str, str] = {}
        current = None
        for line_number, line in body:
            m = _FIELD_LINE.match(line)
            if m and m[1].strip().lower() in lookup:
                current = lookup[m[1].strip().lower()]
                if current in fields:
                    problems.append(f"{label}: {current} appears twice, again in line {line_number}")
                fields[current] = m[2]
            elif current:
                fields[current] += "\n" + line
            elif line.strip():
                problems.append(
                    f"{label}: line {line_number} is not 'Field: content'. {nt.name} has: {', '.join(nt.fields)}"
                )
                break
        if not fields:
            problems.append(f"{label}: no fields. {nt.name} has: {', '.join(nt.fields)}")
            continue
        cards.append(
            CardIn(
                fields={k: line_breaks_to_html(v.strip()) for k, v in fields.items()},
                tags=tags,
                note_type=nt.name if name else None,
                deck=deck,
            )
        )
    if problems:
        raise ToolError("Nothing was added. Fix these in cards_text and send it again:\n" + "\n".join(problems))
    if len(cards) > MAX_CARDS:
        raise ToolError(f"cards_text has {len(cards)} cards. Send at most {MAX_CARDS}, the rest with the draft_id.")
    return cards


# --- checks --------------------------------------------------------------------------


async def _check(
    a: App, cards: list[tuple[str, DraftCard]], others: list[DraftCard]
) -> tuple[list[str], dict[str, str | None]]:
    """Check new or changed cards against Anki and the rest of the draft. Normalizes field names in place.

    Returns the errors, and the decks that do not exist yet with an existing deck the name may have meant.
    """
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for other in others:
        nt = await a.note_types.get(other.note_type)
        seen.add((other.note_type, strip_html(other.fields.get(nt.fields[0], "")).lower()))

    decks = set(await a.anki.invoke("deckNames"))
    to_ask: list[tuple[str, DraftCard, NoteType]] = []
    for label, card in cards:
        if card.deck not in decks:
            # A bare subdeck name would silently create a new top-level deck.
            similar = [d for d in decks if d.lower().endswith("::" + card.deck.lower())]
            if similar:
                errors.append(f"{label}: there is no deck '{card.deck}'. Did you mean '{similar[0]}'?")
                continue
        try:
            nt = await a.note_types.get(card.note_type)
        except AnkiError as exc:
            errors.append(f"{label}: {exc}")
            continue
        fields, unknown = nt.normalize(card.fields)
        if unknown:
            errors.append(f"{label}: unknown fields {unknown}. {card.note_type} has: {', '.join(nt.fields)}")
            continue
        card.fields = fields
        missing = [name for value in fields.values() for name in local_images(value) if not a.images.has(name)]
        if missing:
            errors.append(f"{label}: no image {', '.join(missing)} in {a.images.folder}. Create it first.")
            continue
        key = (card.note_type, strip_html(fields.get(nt.fields[0], "")).lower())
        if key in seen and not card.allow_duplicate:
            errors.append(f"{label}: another card in this draft has the same {nt.fields[0]}")
            continue
        seen.add(key)
        to_ask.append((label, card, nt))

    if to_ask:
        # Decks that do not exist yet are created by draft_commit. Anki's duplicate check is collection-wide anyway.
        notes = [
            {
                "deckName": card.deck if card.deck in decks else "Default",
                "modelName": card.note_type,
                "fields": card.fields,
                "tags": card.tags,
                "options": {"allowDuplicate": card.allow_duplicate},
            }
            for _, card, _ in to_ask
        ]
        results = await a.anki.invoke("canAddNotesWithErrorDetail", notes=notes)
        for (label, _, nt), result in zip(to_ask, results, strict=True):
            if not result["canAdd"]:
                message = result["error"]
                if nt.kind == "cloze" and "unknown reason" in message:
                    message += " (a cloze card needs at least one {{c1::...}})"
                errors.append(f"{label}: {message}")
    new_decks = {}
    for deck in sorted({card.deck for _, card in cards} - decks):
        similar = similar_decks(deck, decks)
        new_decks[deck] = similar[0] if similar else None
    return errors, new_decks


def _repair(cards: list[DraftCard]) -> list[list[str]]:
    """Repair the fields of the cards in place. Returns, per card, what was repaired in which field."""
    repaired = []
    for card in cards:
        done = []
        for name, value in list(card.fields.items()):
            card.fields[name], what = repair(value)
            if what:
                done.append(f"{name} {', '.join(what)}")
        repaired.append(done)
    return repaired


def _repair_lines(cards: list[DraftCard], repaired: list[list[str]]) -> list[str]:
    return [f"#{card.n} " + "; ".join(done) for card, done in zip(cards, repaired, strict=True) if done]


REPAIRED = "Repaired (LaTeX that lost its backslash in JSON, a '<' HTML would misread):"


def _warnings(cards: list[DraftCard], note_types: dict[str, NoteType]) -> list[str]:
    lines = []
    for card in cards:
        nt = note_types.get(card.note_type)
        if nt and nt.kind != "io":
            lines.extend(f"#{card.n} {problem}" for problem in lint(card.fields))
    return lines


_RULES = {
    "LONG_ANSWER": "the answer has more than 15 words: keep it to a phrase, or split the card",
    "LIST_LIKE": "the answer reads like a list: split it, a list becomes cloze deletions",
    "MANY_CLOZES": "more than five cloze numbers on one note: split it",
}


def _rule_hints(cards: list[DraftCard], note_types: dict[str, NoteType]) -> list[str]:
    lines = []
    for card in cards:
        nt = note_types.get(card.note_type)
        if nt and nt.kind != "io":
            ordered = {name: card.fields[name] for name in nt.fields if name in card.fields}
            lines.extend(f"#{card.n} {_RULES[flag]}" for flag in content_flags(ordered, nt.kind == "cloze"))
    return lines


_WORD = re.compile(r"\w{4,}")


async def _similar(
    a: App, cards: list[DraftCard], others: list[DraftCard], note_types: dict[str, NoteType]
) -> list[str]:
    """Cards whose first field reads almost like that of a note in their deck or of another card in the draft.
    Anki itself only rejects exact copies."""

    def first(card: DraftCard) -> str:
        nt = note_types.get(card.note_type)
        return card.fields.get(nt.fields[0], "") if nt and nt.kind != "io" else ""

    pool: list[tuple[str, str, str]] = []  # label, text to compare, text to show
    for deck in sorted({card.deck for card in cards}):
        try:
            ids = sorted(await a.anki.invoke("findNotes", query=deck_query(deck)), reverse=True)[:MAX_COMPARED]
            infos = await a.anki.invoke("notesInfo", notes=ids) if ids else []
        except AnkiError:
            continue
        for info in infos:
            if info and info.get("fields"):
                value = min(info["fields"].values(), key=lambda f: f["order"])["value"]
                pool.append((f"note {info['noteId']}", comparable(value), value))
    pool += [(f"#{card.n} of this draft", comparable(first(card)), first(card)) for card in others if first(card)]

    index: dict[str, list[int]] = {}

    def add(i: int) -> None:
        for word in set(_WORD.findall(pool[i][1])):
            index.setdefault(word, []).append(i)

    for i in range(len(pool)):
        add(i)

    hints = []
    for card in cards:
        text = comparable(first(card))
        if len(text) >= 12 and not card.allow_duplicate:
            shared = Counter(i for word in set(_WORD.findall(text)) for i in index.get(word, ()))
            best, ratio = None, SIMILAR
            for i, _ in shared.most_common(30):
                matcher = SequenceMatcher(None, text, pool[i][1])
                if matcher.real_quick_ratio() >= ratio and matcher.quick_ratio() >= ratio and matcher.ratio() >= ratio:
                    best, ratio = i, matcher.ratio()
            if best is not None:
                hints.append(f"#{card.n} reads like {pool[best][0]}: '{truncate(strip_html(pool[best][2]), 70)}'")
        if text:
            pool.append((f"#{card.n}", text, first(card)))
            add(len(pool) - 1)
    return hints


# Topics that exams usually show as a drawing. German compounds ("Binärbaum", "Zustandsdiagramm") match too,
# words like "automatisch", "Kryptographie" or "Biographie" do not.
_DRAWN = re.compile(
    r"(?<!para)(?<!photo)graph(?!ie|y\b|ic)|\b[bd]fs\b|dijkstra|kruskal|prim's|\bheap|baum|\btrees?\b|\bavl\b|"
    r"rot-schwarz|red-black|automat(?!is|ic|io)|\b[dn]fa\b|\bnea\b|\bdea\b|state machine|zustands|schaltung|"
    r"circuit|petri|\buml\b|diagram|\bplot|skizz|sketch",
    re.IGNORECASE,
)


def _picture_hints(cards: list[DraftCard]) -> list[str]:
    """Text cards about something usually drawn. Claude rarely thinks of pictures unless reminded on the spot."""
    hints = []
    for card in cards:
        text = " ".join(card.fields.values())
        if "<img" not in text and (match := _DRAWN.search(strip_html(text))):
            hints.append(f"#{card.n} ({match[0].lower()})")
    return hints


def _section(title: str, items: list[str]) -> list[str]:
    return [title, *items] if items else []


# --- how cards look in the chat ------------------------------------------------------


def _header(draft: Draft) -> str:
    title = f' "{draft.title}"' if draft.title else ""
    return f"Draft {draft.id}{title}, deck {draft.deck}"


def _card_text(card: DraftCard, nt: NoteType | None, deck: str, common: set[str]) -> str:
    head = f"#{card.n} {card.note_type}"
    fields = dict(card.fields)
    if nt and nt.kind == "cloze":
        head += " (" + ", ".join(f"c{n}" for n in cloze_ords(fields)) + ")"
    elif nt and nt.kind == "io" and nt.io_fields:
        masks, hide_all = parse_field(fields.pop(nt.io_fields.get("occlusion", ""), ""))
        groups = len({m.group for m in masks})
        mode = "all hidden, one asked" if hide_all else "one hidden at a time"
        head += f" ({_count(len(masks), 'mask')}, {_count(groups, 'card')}, {mode})"
        images = local_images(fields.get(nt.io_fields.get("image", ""), ""))
        if images:
            head += f", masks drawn in {Path(images[0]).stem}-masks.png"
    if card.deck != deck:
        head += f", deck {card.deck}"

    lines = [head]
    for name, value in fields.items():
        first, *rest = readable(value).split("\n")
        if first:
            lines.append(f"{name}: {first}")
            lines.extend(f"  {line}" for line in rest)
    own = [tag for tag in card.tags if tag not in common]
    if own:
        lines.append("Tags: " + " ".join(own))
    if card.error:
        lines.append(f"Last draft_commit failed: {card.error}")
    return "\n".join(lines)


async def _cards_text(a: App, draft: Draft, cards: list[DraftCard]) -> list[str]:
    """The cards as text for the chat, plus where their images are."""
    note_types = {nt.name: nt for nt in await a.note_types.all()}
    common = set.intersection(*(set(card.tags) for card in cards)) if len(cards) > 1 else set()
    blocks = []
    if common:
        blocks.append("Tags of every card below: " + " ".join(tag for tag in cards[0].tags if tag in common))
    blocks += [_card_text(card, note_types.get(card.note_type), draft.deck, common) for card in cards]
    if any(local_images(v) for card in cards for v in card.fields.values()):
        blocks.append(f"The images are in {a.images.folder}.")
    return blocks


def _numbers(cards: list[DraftCard] | list[int]) -> str:
    """'#1-#3, #5' for cards 1, 2, 3 and 5."""
    numbers = sorted(c if isinstance(c, int) else c.n for c in cards)
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return ", ".join(f"#{run[0]}" if len(run) == 1 else f"#{run[0]}-#{run[-1]}" for run in runs)


def _new_decks(new_decks: dict[str, str | None]) -> list[str]:
    lines = []
    for deck, similar in new_decks.items():
        line = f"New deck, created by draft_commit: {deck}"
        if similar:
            line += f". '{similar}' exists: if that was meant, move the cards there with draft_edit (deck)"
        lines.append(line)
    return lines


# --- tools ---------------------------------------------------------------------------


async def _append(a: App, draft_id: str | None, cards: list[DraftCard], title: str | None, **new: Any) -> Draft:
    if not draft_id:
        draft_id = a.drafts.create(title=title, **new).id
    async with a.drafts.edit(draft_id) as draft:
        if title:
            draft.title = title
        for card in cards:
            card.n = draft.next_n
            draft.next_n += 1
            draft.cards.append(card)
    return draft


def _added(draft: Draft, cards: list[DraftCard], new_decks: dict[str, str | None]) -> list[str]:
    total = _count(len(draft.cards), "card")
    lines = [f"{_header(draft)}: added {_numbers(cards)}. The draft has {total}, none of them is in Anki yet."]
    return lines + _new_decks(new_decks)


NEXT_STEP = "Show the cards to the user. Apply their changes with draft_edit; when they approve, call draft_commit."
QUIET_STEP = (
    "The cards are not shown (echo=false); draft_show shows them. Call draft_commit once the user has approved them, "
    "or right away if they asked for the cards to be added without seeing them."
)
ECHO = (
    "false: reply with card numbers, repairs and warnings only, not the cards. For when the user said to add the "
    "cards without seeing them, or when nobody reads them"
)


@tool("Add cards to a draft", DRAFT)
async def draft_add(
    ctx: Ctx,
    cards: Annotated[list[CardIn] | None, Field(min_length=1, max_length=MAX_CARDS)] = None,
    cards_text: Annotated[str | None, Field(description=CARDS_TEXT)] = None,
    draft_id: Annotated[str | None, Field(description="Add to this draft. Without it a new draft is created")] = None,
    deck: Annotated[
        str | None, Field(description="Deck of these cards, full name, e.g. 'Math::Analysis'. A new draft needs it")
    ] = None,
    note_type: Annotated[
        str | None, Field(description="Note type of these cards, e.g. 'Basic'. A new draft needs it")
    ] = None,
    tags: Annotated[
        list[str] | None, Field(description="Tags for these cards. A new draft also gives them to later cards")
    ] = None,
    title: Annotated[str | None, Field(description="A short name for the draft")] = None,
    allow_duplicate: Annotated[bool, Field(description="Allow cards whose first field already exists")] = False,
    echo: Annotated[bool, Field(description=ECHO)] = True,
) -> str:
    """Check cards against Anki and add them to a draft. Nothing is written to Anki.

    Pass 'cards', or 'cards_text' for cards with LaTeX. LaTeX that lost a backslash in JSON is repaired.
    Returns the cards as text to show the user (no HTML, &amp; shows as &). If any card has a problem,
    none is added and every problem is listed.
    """
    a = app(ctx)
    if cards is not None and cards_text is not None:
        raise ToolError("Pass the cards as 'cards' or as 'cards_text', not both.")
    others: list[DraftCard] = []
    base_tags: list[str] = []
    if draft_id:
        draft = a.drafts.load(draft_id)
        others, base_tags = draft.cards, draft.tags
        deck, note_type = deck or draft.deck, note_type or draft.note_type
    if cards_text is not None:
        items = await _parse_cards_text(a, cards_text, note_type)
    elif cards is not None:
        items = cards
    else:
        raise ToolError("Pass the cards as 'cards' or as 'cards_text'.")

    def label(i: int) -> str:
        return f"card {i + 1}" if cards_text is not None else f"cards[{i}]"

    lacking = [label(i) for i, c in enumerate(items) if not (c.deck or deck) or not (c.note_type or note_type)]
    if lacking:
        raise ToolError(
            "A new draft needs 'deck' and 'note_type', for the call or for each card. Missing for "
            + ", ".join(lacking[:5])
            + ". To add to an existing draft, pass its draft_id."
        )
    new = [
        DraftCard(
            deck=c.deck or deck or "",
            note_type=c.note_type or note_type or "",
            fields=c.fields,
            tags=_merge_tags(base_tags, tags or [], c.tags),
            allow_duplicate=allow_duplicate,
        )
        for c in items
    ]
    repaired = _repair(new)
    errors, new_decks = await _check(a, [(label(i), card) for i, card in enumerate(new)], others)
    if errors:
        raise ToolError("Nothing was added. Fix these and send all cards again:\n" + "\n".join(errors))
    defaults = {
        "deck": deck or new[0].deck,
        "note_type": note_type or new[0].note_type,
        "tags": _merge_tags(tags or []),
    }
    draft = await _append(a, draft_id, new, title, **defaults)

    note_types = {nt.name: nt for nt in await a.note_types.all()}
    lines = _added(draft, new, new_decks)
    lines += _section(REPAIRED, _repair_lines(new, repaired))
    lines += _section("Possible formatting problems, fix the real ones with draft_edit:", _warnings(new, note_types))
    lines += _section("Possibly against the card rules:", _rule_hints(new, note_types))
    lines += _section(
        "Close to cards that exist, check whether they are near-duplicates:",
        await _similar(a, new, others, note_types),
    )
    hints = _picture_hints(new)
    if hints:
        lines.append(
            "Cards about something usually drawn, without a picture: " + ", ".join(hints) + ". If the exam shows it "
            "as a drawing, add one before showing the cards (visuals skill: render_graph, pdf_figures, occlusion)."
        )
    if not echo:
        return "\n".join([*lines, QUIET_STEP])
    return "\n\n".join(["\n".join(lines), *await _cards_text(a, draft, new), NEXT_STEP])


class MaskIn(BaseModel):
    label: str | None = Field(default=None, description="Text on the image (a PDF word or a graph node) to hide")
    region: list[float] | None = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="Area to hide instead of a label: [left, top, right, bottom] as fractions (0-1) of the image",
    )
    group: int | None = Field(default=None, description="Masks with the same group are asked together on one card")


@tool("Add an image occlusion card to a draft", DRAFT)
async def draft_add_occlusion(
    ctx: Ctx,
    image: Annotated[str, Field(description="Image file name from stage_image or render_graph, e.g. 'heart.png'")],
    masks: Annotated[list[MaskIn], Field(min_length=1, max_length=50)],
    header: Annotated[str, Field(description="Shown above the image, e.g. what to name")] = "",
    back_extra: Annotated[str, Field(description="Shown below the image on the back")] = "",
    hide_all: Annotated[
        bool, Field(description="True: all masks hidden, one asked. False: only the asked mask hidden")
    ] = True,
    draft_id: Annotated[str | None, Field(description="Add to this draft. Without it a new draft is created")] = None,
    deck: Annotated[str | None, Field(description="New draft: full deck name")] = None,
    tags: Annotated[
        list[str] | None, Field(description="Tags for this card. A new draft also gives them to later cards")
    ] = None,
    title: Annotated[str | None, Field(description="A short name for the draft")] = None,
) -> list[Any]:
    """Add an Image Occlusion note (Anki 23.10+) to a draft. Each mask, or each group of masks, becomes one card.

    Returns the image with the masks drawn in. Check that every mask covers exactly its label.
    """
    a = app(ctx)
    io_types = [nt for nt in await a.note_types.all() if nt.kind == "io"]
    if not io_types:
        raise ToolError(
            "There is no Image Occlusion note type. It needs Anki 23.10 or newer; "
            "then in Anki: Tools > Manage Note Types > Add > 'Add: Image Occlusion'."
        )
    nt = io_types[0]
    others: list[DraftCard] = []
    base_tags: list[str] = []
    if draft_id:
        draft = a.drafts.load(draft_id)
        deck, others, base_tags = deck or draft.deck, draft.cards, draft.tags
    elif not deck:
        raise ToolError("A new draft needs 'deck'. To add to an existing draft, pass its draft_id.")
    staged = a.images.get(image)

    resolved: list[Mask] = []
    problems = []
    next_group = max([m.group or 0 for m in masks] + [0]) + 1
    for i, m in enumerate(masks):
        if m.label:
            mask = find_label(staged.labels, m.label)
            if mask is None:
                known = (
                    ", ".join(sorted({b["text"] for b in staged.labels})[:40]) or "none, the image has no text layer"
                )
                problems.append(f"masks[{i}]: label '{m.label}' not found. Labels on the image: {known}")
                continue
        elif m.region:
            left, top, right, bottom = m.region
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                problems.append(f"masks[{i}]: region needs 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
                continue
            mask = Mask(left, top, right - left, bottom - top)
        else:
            problems.append(f"masks[{i}]: needs 'label' or 'region'")
            continue
        if m.group is None:
            mask.group, next_group = next_group, next_group + 1
        else:
            mask.group = m.group
        resolved.append(mask)
    if problems:
        raise ToolError("Nothing was added:\n" + "\n".join(problems))

    io = nt.io_fields or {}
    fields = {
        io["occlusion"]: build_field(resolved, hide_all),
        io["image"]: staged.tag(),
        io.get("header", "Header"): header,
        io.get("back_extra", "Back Extra"): back_extra,
    }
    card = DraftCard(
        deck=deck, note_type=nt.name, fields=fields, tags=_merge_tags(base_tags, tags or []), allow_duplicate=True
    )
    _repair([card])
    errors, new_decks = await _check(a, [("card", card)], others)
    if errors:
        raise ToolError("Nothing was added:\n" + "\n".join(errors))
    draft = await _append(a, draft_id, [card], title, deck=deck, note_type=nt.name, tags=_merge_tags(tags or []))

    with Image.open(staged.path) as img:
        preview = draw_masks(img.convert("RGB"), resolved)
    a.images.save_preview(preview, f"{staged.path.stem}-masks.png")
    blocks = ["\n".join(_added(draft, [card], new_decks)), *await _cards_text(a, draft, [card]), NEXT_STEP]
    text = "\n\n".join(blocks)
    return [text, McpImage(data=png_bytes(downscale(preview, 800)), format="png")]


class EditIn(BaseModel):
    card: int = Field(description="Card number in the draft, e.g. 3 for #3")
    fields: dict[str, str] | None = Field(default=None, description="Only the fields that change")
    tags: list[str] | None = Field(default=None, description="Replaces all tags of the card")
    deck: str | None = Field(default=None, description="Moves the card to this deck (full name)")
    remove: bool = Field(default=False, description="Remove the card from the draft")


class ReplaceIn(BaseModel):
    find: str = Field(min_length=1, description="Text to find; a Python regular expression with regex=true")
    replacement: str = Field(description="What replaces it. With regex=true, \\1 and \\g<name> insert a group")
    regex: bool = False
    cards: list[int] | None = Field(default=None, description="Only these card numbers. Without it: every card")
    fields: list[str] | None = Field(default=None, description="Only these fields. Without it: every field")


_GROUP_REF = re.compile(r"\\(\d+)|\\g<(\w+)>")


def _replacer(r: ReplaceIn) -> tuple[re.Pattern[str], Callable[[re.Match[str]], str]]:
    """The pattern and what to put in for each match. Only \\1 and \\g<name> are special in the replacement,
    so the backslashes of LaTeX stay as they are."""
    try:
        pattern = re.compile(r.find if r.regex else re.escape(r.find))
    except re.error as exc:
        raise ToolError(f"'{r.find}' is not a valid regular expression: {exc}") from None

    def literal(_: re.Match[str]) -> str:
        return r.replacement

    def expand(m: re.Match[str]) -> str:
        def group(g: re.Match[str]) -> str:
            try:
                return m[int(g[1]) if g[1] else g[2]] or ""
            except (IndexError, KeyError):
                raise ToolError(f"The replacement '{r.replacement}' refers to a group '{r.find}' lacks.") from None

        return _GROUP_REF.sub(group, r.replacement)

    return pattern, expand if r.regex else literal


@tool("Change cards in a draft", DRAFT)
async def draft_edit(
    ctx: Ctx,
    draft_id: str,
    edits: Annotated[list[EditIn] | None, Field(description="Changes card by card")] = None,
    replace: Annotated[
        list[ReplaceIn] | None,
        Field(max_length=20, description="Find and replace across the draft, applied before 'edits'"),
    ] = None,
    echo: Annotated[bool, Field(description="false: reply with card numbers and problems only, not the cards")] = True,
) -> str:
    """Change, move or remove cards of a draft by number, or find and replace across all its cards.

    Send only the fields that change; the others stay. Returns the changed cards as text to show the user.
    """
    if not edits and not replace:
        raise ToolError("Pass 'edits', 'replace' or both.")
    a = app(ctx)
    async with a.drafts.edit(draft_id) as draft:
        by_n = {card.n: card for card in draft.cards}
        asked = [e.card for e in edits or []] + [n for r in replace or [] for n in r.cards or []]
        missing = sorted(set(asked) - set(by_n))
        if missing:
            raise ToolError(f"Draft {draft_id} has no card {_numbers(missing)}.")

        work = {n: card.model_copy(deep=True) for n, card in by_n.items()}
        touched: set[int] = set()
        report = []
        for r in replace or []:
            pattern, replacement = _replacer(r)
            only = {name.lower() for name in r.fields} if r.fields else None
            hits: dict[int, int] = {}
            for n in r.cards or list(by_n):
                card = work[n]
                for name, value in list(card.fields.items()):
                    if only is None or name.lower() in only:
                        card.fields[name], count = pattern.subn(replacement, value)
                        if count:
                            hits[n] = hits.get(n, 0) + count
            touched |= set(hits)
            found = f"{_count(sum(hits.values()), 'time')} in {_numbers(list(hits))}" if hits else "not found"
            report.append(f"'{truncate(r.find, 40)}': {found}")

        removed = {e.card for e in edits or [] if e.remove}
        for e in edits or []:
            if e.remove:
                continue
            card = work[e.card]
            if e.fields:
                card.fields = {**card.fields, **e.fields}
            if e.tags is not None:
                card.tags = _merge_tags(e.tags)
            if e.deck:
                card.deck = e.deck
            touched.add(e.card)
        touched -= removed

        changed = [work[n] for n in sorted(touched)]
        for card in changed:
            card.error = None
        repaired = _repair(changed)
        others = [card for card in draft.cards if card.n not in touched | removed]
        errors, new_decks = await _check(a, [(f"#{card.n}", card) for card in changed], others)
        if errors:
            raise ToolError("Nothing was changed:\n" + "\n".join(errors))
        draft.cards = [work[card.n] if card.n in touched else card for card in draft.cards if card.n not in removed]

    if not draft.cards:
        return f"Draft {draft_id} has no cards left and was deleted."
    done = []
    if changed:
        done.append(f"changed {_numbers(changed)}")
    if removed:
        done.append(f"removed {_numbers(sorted(removed))}")
    left = _count(len(draft.cards), "card")
    lines = [f"Draft {draft_id}: {' and '.join(done) or 'nothing changed'}. {left} left, none of them is in Anki yet."]
    lines += _section("Replaced:", report) + _new_decks(new_decks)
    note_types = {nt.name: nt for nt in await a.note_types.all()}
    lines += _section(REPAIRED, _repair_lines(changed, repaired))
    lines += _section("Possible formatting problems:", _warnings(changed, note_types))
    lines += _section("Possibly against the card rules:", _rule_hints(changed, note_types))
    if not changed or not echo:
        return "\n".join(lines)
    return "\n\n".join(["\n".join(lines), *await _cards_text(a, draft, changed), "Show the changed cards to the user."])


@tool("Show a draft", READ_ONLY)
async def draft_show(
    ctx: Ctx,
    draft_id: Annotated[str | None, Field(description="Without it: list the open drafts")] = None,
    cards: Annotated[list[int] | None, Field(description="Only these card numbers")] = None,
) -> str:
    """Show the cards of a draft as text, or list the open drafts. Drafts survive restarts."""
    a = app(ctx)
    if draft_id is None:
        drafts = a.drafts.all()
        if not drafts:
            return "No open drafts."
        lines = ["Open drafts, newest first:"]
        for d in drafts:
            title = f' "{d.title}"' if d.title else ""
            changed = f"{d.updated:%Y-%m-%d %H:%M} UTC"
            lines.append(f"{d.id}{title}: deck {d.deck}, {_count(len(d.cards), 'card')}, last changed {changed}")
        return "\n".join(lines)

    draft = a.drafts.load(draft_id)
    shown = [card for card in draft.cards if cards is None or card.n in cards]
    header = f"{_header(draft)}: {_count(len(draft.cards), 'card')}, none of them is in Anki yet."
    return "\n\n".join([header, *await _cards_text(a, draft, shown)])


@tool("Add draft cards to Anki", ADDS)
async def draft_commit(
    ctx: Ctx,
    draft_id: str,
    cards: Annotated[
        list[int] | None, Field(min_length=1, description="Only these card numbers. Without it: all cards")
    ] = None,
) -> str:
    """Add the cards the user approved to Anki. Missing decks are created. Returns a batch id for undo.

    Cards that fail stay in the draft with the reason. The draft is deleted when no cards are left.
    """
    a = app(ctx)
    batch_id = uuid4().hex[:8]
    async with a.drafts.edit(draft_id) as draft:
        wanted = set(cards) if cards is not None else {card.n for card in draft.cards}
        missing = sorted(wanted - {card.n for card in draft.cards})
        if missing:
            raise ToolError(f"Draft {draft_id} has no card {_numbers(missing)}.")
        selected = [card for card in draft.cards if card.n in wanted]

        decks = set(await a.anki.invoke("deckNames"))
        for deck in sorted({card.deck for card in selected} - decks):
            await a.anki.invoke("createDeck", deck=deck)
        images = sorted({name for card in selected for value in card.fields.values() for name in local_images(value)})
        stored = await upload_images(a, images)

        calls, sent = [], []
        for card in selected:
            failed = [name for value in card.fields.values() for name in local_images(value) if name not in stored]
            if failed:
                card.error = f"could not copy {', '.join(failed)} to Anki"
                continue
            note = {
                "deckName": card.deck,
                "modelName": card.note_type,
                "fields": {name: replace_images(value, stored) for name, value in card.fields.items()},
                "tags": _merge_tags(card.tags, [CREATED_TAG, BATCH_PREFIX + batch_id]),
                "options": {"allowDuplicate": card.allow_duplicate},
            }
            calls.append(("addNote", {"note": note}))
            sent.append(card)

        results = await a.anki.multi(calls) if calls else []
        created: list[int] = []
        added: list[DraftCard] = []
        for card, result in zip(sent, results, strict=True):
            if isinstance(result, int):
                created.append(result)
                added.append(card)
            else:
                card.error = str(result).removeprefix("addNote: ")
        done = {card.n for card in added}
        draft.cards = [card for card in draft.cards if card.n not in done]
        failed_cards = [card for card in selected if card.n not in done]

    lines = []
    if created:
        a.journal.append({"batch_id": batch_id, "kind": "commit", "draft_id": draft_id, "created": created})
        decks_used = ", ".join(sorted({card.deck for card in added}))
        lines.append(
            f"Added {_count(len(created), 'card')} to Anki ({_numbers(added)}, deck {decks_used}). "
            f'Batch id {batch_id}: undo("{batch_id}") removes {"it" if len(created) == 1 else "them"} again.'
        )
    else:
        lines.append("Nothing was added to Anki.")
    if failed_cards:
        lines.append("Not added:")
        lines.extend(f"#{card.n}: {card.error}" for card in failed_cards)
        lines.append("They stay in the draft. Fix them with draft_edit and call draft_commit again, or remove them.")
    waiting = [card for card in draft.cards if card.n not in wanted]
    if waiting:
        lines.append(f"Not committed yet, still in draft {draft_id}: {_numbers(waiting)}.")
    if not draft.cards:
        lines.append(f"Draft {draft_id} is finished and was deleted.")
    return "\n".join(lines)
