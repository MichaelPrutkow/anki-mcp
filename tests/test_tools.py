import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fake_anki import FakeAnki
from mcp import types
from mcp.client import Client
from PIL import Image, ImageDraw

from anki_mcp.server import mcp
from anki_mcp.text import lint, readable

pytestmark = pytest.mark.anyio

IMAGES = Path("Pictures/Anki MCP")


async def call(client: Client, tool: str, **args: Any) -> str:
    result = await client.call_tool(tool, args)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    assert not result.is_error, text
    return text


async def fails(client: Client, tool: str, **args: Any) -> str:
    result = await client.call_tool(tool, args)
    assert result.is_error
    return "\n".join(c.text for c in result.content if c.type == "text")


def draft_id(text: str) -> str:
    match = re.search(r"d_[0-9a-f]{6}", text)
    assert match, text
    return match[0]


def batch_id(text: str) -> str:
    match = re.search(r'undo\("([0-9a-f]{8})"\)', text)
    assert match, text
    return match[1]


BASIC = {"fields": {"Front": "Warum ist \\(Q\\) invertierbar?", "Back": "Aus \\(Q^TQ = I\\) folgt es"}}
CLOZE = {
    "fields": {"Text": "Eine Äquivalenzrelation ist {{c1::reflexiv}} und {{c2::symmetrisch}}"},
    "note_type": "Cloze",
}


async def test_overview_lists_decks_and_note_types(client: Client, anki: FakeAnki) -> None:
    anki.add_user_note("a", "b")
    text = await call(client, "overview")
    assert "Math: 1 cards" in text
    assert "Empty decks: Math::Analysis" in text
    assert "Basic [basic]: Front | Back" in text
    assert "Image Occlusion [image occlusion]: Occlusion | Image | Header | Back Extra | Comments" in text


async def test_overview_finds_a_deck_by_its_short_name(client: Client, anki: FakeAnki) -> None:
    anki.decks |= {"TUM::GDB": 10, "TUM::GDB::Übung": 11, "TUM::Analysis 1": 12}
    text = await call(client, "overview", deck="gdb")
    assert "TUM::GDB" in text and "TUM::GDB::Übung" in text
    assert "Analysis" not in text and "No deck" not in text


async def test_overview_never_fails_on_an_unknown_deck(client: Client, anki: FakeAnki) -> None:
    anki.decks |= {"TUM::Analysis 1": 12}
    text = await call(client, "overview", deck="Analysis")
    assert "No deck" not in text and "TUM::Analysis 1" in text and "Math::Analysis" in text

    text = await call(client, "overview", deck="analy")
    assert "No deck is named 'analy'. These decks contain" in text and "TUM::Analysis 1" in text

    text = await call(client, "overview", deck="Datenbanken")
    assert "These are all decks" in text and "TUM::Analysis 1" in text and "Math::Analysis" in text
    assert "Basic [basic]: Front | Back" in text


async def test_draft_edit_and_commit_in_steps(client: Client, anki: FakeAnki) -> None:
    text = await call(client, "draft_add", cards=[BASIC, CLOZE], deck="Math::Analysis", note_type="Basic")
    draft = draft_id(text)
    assert "added #1-#2" in text and "none of them is in Anki yet" in text
    assert "#1 Basic\nFront: Warum ist \\(Q\\) invertierbar?" in text
    assert "#2 Cloze (c1, c2)" in text
    assert not anki.notes

    text = await call(
        client, "draft_edit", draft_id=draft, edits=[{"card": 1, "fields": {"Back": "Weil \\(Q^T = Q^{-1}\\)"}}]
    )
    assert "changed #1" in text and "Back: Weil" in text and "#2" not in text

    text = await call(client, "draft_commit", draft_id=draft, cards=[1])
    assert "Added 1 card to Anki (#1, deck Math::Analysis)" in text
    assert "Not committed yet, still in draft" in text and "#2" in text
    [note] = anki.notes.values()
    assert note["fields"]["Back"]["value"] == "Weil \\(Q^T = Q^{-1}\\)"
    assert "mcp::created" in note["tags"]

    text = await call(client, "draft_commit", draft_id=draft)
    assert "is finished and was deleted" in text
    assert len(anki.notes) == 2
    assert await call(client, "draft_show") == "No open drafts."

    text = await call(client, "undo", batch_id=batch_id(text))
    assert "deleted 1 note" in text
    assert len(anki.notes) == 1


async def test_draft_add_reports_every_problem_and_adds_nothing(client: Client, anki: FakeAnki) -> None:
    anki.add_user_note("Warum ist \\(Q\\) invertierbar?", "x")
    cards = [
        BASIC,
        {"fields": {"Question": "x"}},
        {"fields": {"Front": "y"}, "deck": "Analysis"},
        {"fields": {"Text": "no gap"}, "note_type": "Cloze"},
        {"fields": {"Front": "z", "Back": '<img src="missing.png">'}},
    ]
    text = await fails(client, "draft_add", cards=cards, deck="Math", note_type="Basic")
    assert "Nothing was added" in text
    assert "cards[0]: cannot create note because it is a duplicate" in text
    assert "cards[1]: unknown fields ['Question']" in text
    assert "cards[2]: there is no deck 'Analysis'. Did you mean 'Math::Analysis'?" in text
    assert "cards[3]: cannot create note for unknown reason (a cloze card needs" in text
    assert "cards[4]: no image missing.png" in text
    assert await call(client, "draft_show") == "No open drafts."


async def test_new_deck_is_created_on_commit(client: Client, anki: FakeAnki) -> None:
    text = await call(client, "draft_add", cards=[BASIC], deck="Physics::Optics", note_type="Basic")
    assert "New deck, created by draft_commit: Physics::Optics" in text
    await call(client, "draft_commit", draft_id=draft_id(text))
    assert "Physics::Optics" in anki.decks


async def test_formatting_slips_are_reported(client: Client) -> None:
    card = {"fields": {"Front": "Was ist D_{C,B}?", "Back": "{{c1::x}}}"}}
    text = await call(client, "draft_add", cards=[card], deck="Math", note_type="Basic")
    assert "#1 Front: LaTeX outside \\( \\): 'D_{C,B}?'" in text


async def test_cards_about_drawn_topics_get_a_picture_hint(client: Client) -> None:
    dfs = {"fields": {"Front": "Welchen Knoten besucht DFS ab A als zweiten?", "Back": "B"}}
    paragraph = {"fields": {"Front": "Was ist ein Paragraph?", "Back": "Ein Absatz"}}
    text = await call(client, "draft_add", cards=[dfs, paragraph], deck="Math", note_type="Basic")
    assert "usually drawn, without a picture: #1 (dfs)." in text
    text = await call(client, "draft_add", cards=[paragraph], deck="Math", note_type="Basic")
    assert "usually drawn" not in text


async def test_failed_card_stays_in_draft(client: Client, anki: FakeAnki) -> None:
    text = await call(
        client, "draft_add", cards=[BASIC, {"fields": {"Front": "other", "Back": "b"}}], deck="Math", note_type="Basic"
    )
    draft = draft_id(text)
    anki.add_user_note("other", "b")  # becomes a duplicate after the draft was checked
    text = await call(client, "draft_commit", draft_id=draft)
    assert "Added 1 card" in text
    assert "#2: cannot create note because it is a duplicate" in text
    shown = await call(client, "draft_show", draft_id=draft)
    assert "Last draft_commit failed: cannot create note because it is a duplicate" in shown


async def test_images_are_named_shown_and_copied_on_commit(client: Client, anki: FakeAnki, tmp_path: Path) -> None:
    picture = Image.new("RGB", (300, 200), "white")
    ImageDraw.Draw(picture).rectangle((50, 50, 250, 150), fill="black")
    picture.save(tmp_path / "slide.png")

    text = await call(client, "stage_image", source=str(tmp_path / "slide.png"), name="Mitralklappe Übersicht")
    assert 'Put <img src="Mitralklappe-Ubersicht.png"> into a card field' in text
    assert (tmp_path / IMAGES / "Mitralklappe-Ubersicht.png").exists()

    card = {"fields": {"Front": "Was zeigt das Bild?", "Back": 'Das Herz<br><img src="Mitralklappe-Ubersicht.png">'}}
    text = await call(client, "draft_add", cards=[card], deck="Math", note_type="Basic")
    assert "Back: Das Herz\n  [image: Mitralklappe-Ubersicht.png]" in text
    assert f"The images are in {tmp_path / IMAGES}" in text

    await call(client, "draft_commit", draft_id=draft_id(text))
    assert "Mitralklappe-Ubersicht.png" in anki.media


async def test_same_name_different_picture_gets_a_number(client: Client, tmp_path: Path) -> None:
    for i, colour in enumerate(["red", "blue"]):
        Image.new("RGB", (100, 100), colour).save(tmp_path / f"p{i}.png")
    first = await call(client, "stage_image", source=str(tmp_path / "p0.png"), name="plot")
    second = await call(client, "stage_image", source=str(tmp_path / "p1.png"), name="plot")
    again = await call(client, "stage_image", source=str(tmp_path / "p0.png"), name="plot")
    assert "is not an absolute path" in await fails(client, "stage_image", source="p0.png", name="plot")
    assert "Saved plot.png" in first and "Saved plot-2.png" in second and "Saved plot.png" in again


async def test_files_outside_the_computer_get_a_clear_error(client: Client) -> None:
    text = await fails(client, "stage_image", source="/mnt/user-data/uploads/slides.pdf", name="x", page=1)
    assert "is not on the user's computer" in text
    text = await fails(client, "stage_image", source="/etc/passwd", name="x")
    assert "only .gif, .jpeg, .jpg, .png, .webp files can be opened" in text


@pytest.mark.skipif(not shutil.which("dot") and not Path("/opt/homebrew/bin/dot").exists(), reason="needs Graphviz")
async def test_graph_and_occlusion(client: Client, tmp_path: Path) -> None:
    text = await call(client, "render_graph", dot="digraph { Vorhof -> Kammer -> Aorta }", name="herz")
    assert "Saved herz.png" in text and "text labels" in text

    masks = [{"label": "Kammer"}, {"label": "Aorta", "group": 5}, {"region": [0.1, 0.1, 0.3, 0.2], "group": 5}]
    text = await call(client, "draft_add_occlusion", image="herz.png", masks=masks, header="Blutfluss", deck="Math")
    assert "Image Occlusion (3 masks, 2 cards, all hidden, one asked), masks drawn in herz-masks.png" in text
    assert "Header: Blutfluss" in text and "Occlusion:" not in text
    assert (tmp_path / IMAGES / "herz-masks.png").exists()

    text = await fails(client, "draft_add_occlusion", image="herz.png", masks=[{"label": "Lunge"}], deck="Math")
    assert "label 'Lunge' not found. Labels on the image: Aorta, Kammer, Vorhof" in text


async def test_user_notes_are_protected(client: Client, anki: FakeAnki) -> None:
    nid = anki.add_user_note("Frage", "Antwort")
    text = await fails(client, "update_notes", updates=[{"note_id": nid, "fields": {"Back": "neu"}}])
    assert "the user wrote this note" in text
    text = await fails(client, "delete_notes", note_ids=[nid])
    assert "Written by the user" in text

    text = await call(client, "update_notes", updates=[{"note_id": nid, "fields": {"back": "neu"}}], force=True)
    assert anki.notes[nid]["fields"]["Back"]["value"] == "neu"
    await call(client, "undo", batch_id=batch_id(text))
    assert anki.notes[nid]["fields"]["Back"]["value"] == "Antwort"


async def test_old_batches_without_journal_can_be_undone(client: Client, anki: FakeAnki) -> None:
    nid = anki.add_user_note("old", "card")
    anki.notes[nid]["tags"] += ["mcp::created", "mcp::batch::0badc0de"]
    assert "deleted 1 note" in await call(client, "undo", batch_id="0badc0de")
    assert "already undone" in await fails(client, "undo", batch_id="0badc0de")


def test_readable_turns_html_into_chat_text() -> None:
    html = 'Erst<br>dann <b>fett</b><ul><li>a &amp; b</li><li>c</li></ul><img src="x.png" width="200">'
    assert readable(html) == "Erst\ndann fett\n- a & b\n- c\n[image: x.png]"


def test_lint_finds_formatting_slips() -> None:
    assert lint({"Front": "$x^2$"}) == ["Front: '$x^2$' does not render in Anki, use \\( \\) or \\[ \\]"]
    assert lint({"Front": "\\(x"}) == ["Front: unbalanced \\( \\) or \\[ \\]"]
    assert lint({"Text": "{{c1::\\frac{1}{2}}}"})[-1].startswith("Text: '}}}' ends the cloze too early")
    assert (
        lint({"Front": "costs $5 and $10, \\(\\frac{1}{2}\\)<br>\\(a \\lt b\\)", "Back": "<pre><code>\\n</code></pre>"})
        == []
    )


async def test_stats_runs_on_a_fresh_collection(client: Client) -> None:
    text = await call(client, "stats", scope="deck:Math")
    assert "Scope: deck:Math" in text
    assert "No weak cards" in text


async def test_tool_schemas_have_no_references(client: Client) -> None:
    # The Claude desktop app forwards only "properties" and "required" of each schema to chats.
    for tool in (await client.list_tools()).tools:
        schema = str(tool.input_schema)
        assert "$ref" not in schema and "$defs" not in schema, tool.name


# --- formulas, echo, tags and decks --------------------------------------------------

# What the server receives when Claude writes LaTeX with one backslash in a JSON array: "\t" is a tab, "\f" a form
# feed, "\n" a line break. These Python literals contain exactly those characters.
MANGLED = {"fields": {"Front": "Was enthält \\(\text{DOM}(P)\\)?", "Back": "\\(\forall t \neq s\\) und \\(a<b\\)"}}


async def test_latex_that_lost_its_backslash_is_repaired(client: Client) -> None:
    text = await call(client, "draft_add", cards=[MANGLED], deck="Math", note_type="Basic")
    assert "#1 Front \\text; Back \\forall, \\neq, < as &lt;" in text
    assert "Front: Was enthält \\(\\text{DOM}(P)\\)?" in text
    assert "Possible formatting problems" not in text


async def test_echo_false_reports_problems_but_not_the_cards(client: Client, anki: FakeAnki) -> None:
    sloppy = {"fields": {"Front": "Was ist D_{C,B}?", "Back": "Eine Matrix"}}
    text = await call(client, "draft_add", cards=[BASIC, sloppy], deck="Math", note_type="Basic", echo=False)
    assert "added #1-#2" in text and "#2 Front: LaTeX outside \\( \\)" in text
    assert "Warum ist" not in text and "echo=false" in text
    assert "Added 2 cards to Anki" in await call(client, "draft_commit", draft_id=draft_id(text))
    assert len(anki.notes) == 2


CARDS_TEXT = r"""## Basic | tags: kap3 tupelkalkuel
Front: Wie schreibt man \(\exists t \in R\,(P(t))\) ohne \(t \in R\) in der Klammer?
Back: \(\exists t\,(t \in R \land P(t))\)

## cloze | deck: Math::Analysis
Text: \(\text{DOM}(P)\) enthält alle {{c1::Konstanten aus \(P\) }}.
Back Extra: Erste Zeile
zweite Zeile
"""


async def test_cards_text_needs_no_json_escaping(client: Client, anki: FakeAnki) -> None:
    text = await call(client, "draft_add", cards_text=CARDS_TEXT, deck="Math", note_type="Basic")
    assert "added #1-#2" in text and "#2 Cloze (c1), deck Math::Analysis" in text
    assert "Back Extra: Erste Zeile\n  zweite Zeile" in text and "Tags: kap3 tupelkalkuel" in text
    await call(client, "draft_commit", draft_id=draft_id(text))
    first, second = (anki.notes[n] for n in sorted(anki.notes))
    assert first["fields"]["Back"]["value"] == r"\(\exists t\,(t \in R \land P(t))\)"
    assert second["fields"]["Back Extra"]["value"] == "Erste Zeile<br>zweite Zeile"
    assert second["deck"] == "Math::Analysis" and "kap3" not in second["tags"]

    bad = "Front: before any card\n## Basic\nQuestion: x\n## Nope\nFront: y"
    text = await fails(client, "draft_add", cards_text=bad, deck="Math")
    assert "line 1: text before the first card" in text
    assert "card 1 (line 2): line 3 is not 'Field: content'. Basic has: Front, Back" in text
    assert "card 2 (line 4): no note type 'Nope'" in text


async def test_tags_show_on_every_card_and_apply_per_call(client: Client, anki: FakeAnki) -> None:
    text = await call(client, "draft_add", cards=[BASIC], deck="Math", note_type="Basic", tags=["kap3"])
    draft = draft_id(text)
    assert "Tags: kap3" in text
    later = {"fields": {"Front": "Wozu dient \\(x\\)?", "Back": "y"}, "tags": ["extra"]}
    text = await call(client, "draft_add", cards=[later], draft_id=draft, tags=["woche3"])
    assert "Tags: kap3 woche3 extra" in text
    text = await call(client, "draft_show", draft_id=draft)
    assert "Tags of every card below: kap3" in text and "Tags: woche3 extra" in text
    await call(client, "draft_commit", draft_id=draft)
    tags = sorted(t for note in anki.notes.values() for t in note["tags"] if not t.startswith("mcp::"))
    assert tags == ["extra", "kap3", "kap3", "woche3"]


async def test_drafts_from_before_keep_their_tags(client: Client, anki: FakeAnki, tmp_path: Path) -> None:
    card = {"n": 1, "deck": "Math", "note_type": "Basic", "fields": {"Front": "Alt", "Back": "a"}, "tags": ["eigen"]}
    old = {"id": "d_01d000", "deck": "Math", "note_type": "Basic", "tags": ["alt"], "next_n": 2, "cards": [card]}
    old["updated"] = datetime.now(UTC).isoformat()
    (tmp_path / ".anki-mcp" / "drafts" / "d_01d000.json").write_text(json.dumps(old))
    assert "Tags: alt eigen" in await call(client, "draft_show", draft_id="d_01d000")
    await call(client, "draft_commit", draft_id="d_01d000")
    [note] = anki.notes.values()
    assert note["tags"][:2] == ["alt", "eigen"]


async def test_a_stale_deck_path_points_to_the_deck_that_exists(client: Client, anki: FakeAnki) -> None:
    anki.decks["GDB"] = 9
    text = await call(client, "overview", deck="3 Semester::GDB")
    assert "No deck is named '3 Semester::GDB'. Did you mean 'GDB'?" in text
    text = await call(client, "draft_add", cards=[BASIC], deck="3 Semester::GDB", note_type="Basic")
    assert "New deck, created by draft_commit: 3 Semester::GDB. 'GDB' exists" in text
    text = await call(client, "draft_edit", draft_id=draft_id(text), edits=[{"card": 1, "deck": "GDB"}])
    assert "#1 Basic, deck GDB" in text and "New deck" not in text


async def test_replace_across_the_draft(client: Client) -> None:
    cards = [{"fields": {"Front": f"Frage {i} zu s. MatrNr", "Back": "s. MatrNr"}} for i in range(3)]
    draft = draft_id(await call(client, "draft_add", cards=cards, deck="Math", note_type="Basic"))
    replace = [
        {"find": "s. MatrNr", "replacement": "\\(s{.}\\text{MatrNr}\\)"},
        {"find": "nirgends", "replacement": "x"},
    ]
    text = await call(client, "draft_edit", draft_id=draft, replace=replace)
    assert "'s. MatrNr': 6 times in #1-#3" in text and "'nirgends': not found" in text
    assert "Back: \\(s{.}\\text{MatrNr}\\)" in text
    regex = {"find": r"Frage (\d)", "replacement": r"\(q_\1\)", "regex": True, "cards": [2]}
    text = await call(client, "draft_edit", draft_id=draft, replace=[regex], echo=False)
    assert "changed #2" in text and "Front:" not in text
    assert "Front: \\(q_1\\) zu" in await call(client, "draft_show", draft_id=draft, cards=[2])


async def test_undo_leaves_cards_the_user_studied_or_edited(client: Client, anki: FakeAnki) -> None:
    cards = [{"fields": {"Front": f"Frage {i}", "Back": "a"}} for i in range(3)]
    text = await call(client, "draft_add", cards=cards, deck="Math", note_type="Basic")
    batch = batch_id(await call(client, "draft_commit", draft_id=draft_id(text)))
    studied, edited, untouched = sorted(anki.notes)
    anki.notes[studied]["studied"] = True
    anki.clock += 3600
    anki.updateNoteFields({"id": edited, "fields": {"Back": "selbst geändert"}})

    text = await call(client, "undo", batch_id=batch)
    assert "deleted 1 note" in text and f"[{studied}, {edited}]" in text
    assert untouched not in anki.notes
    assert "force=true" in await fails(client, "undo", batch_id=batch)
    assert "deleted 2 notes" in await call(client, "undo", batch_id=batch, force=True)
    assert not anki.notes


async def test_near_duplicates_and_long_answers_get_hints(client: Client, anki: FakeAnki) -> None:
    anki.add_user_note("Was ist ein Schlüsselkandidat in SQL?", "x")
    near = {"fields": {"Front": "Was ist ein Schlüsselkandidat?", "Back": "y"}}
    long = {"fields": {"Front": "Was gilt für die Hauptstadt?", "Back": " ".join(["Wort"] * 20)}}
    formula = {"fields": {"Front": "Wie lautet die Formel?", "Back": "\\(f(a, b, c) = g(x, y)\\)"}}
    text = await call(client, "draft_add", cards=[near, long, formula], deck="Math", note_type="Basic")
    assert "#1 reads like note" in text and "Schlüsselkandidat in SQL" in text
    assert "#2 the answer has more than 15 words" in text
    assert "#2 reads like" not in text and "#3 the answer" not in text


async def test_update_notes_repairs_latex_too(client: Client, anki: FakeAnki) -> None:
    await call(
        client,
        "draft_commit",
        draft_id=draft_id(await call(client, "draft_add", cards=[BASIC], deck="Math", note_type="Basic")),
    )
    [nid] = anki.notes
    text = await call(
        client, "update_notes", updates=[{"note_id": nid, "fields": {"Back": "\\(\frac{1}{2} \\and x\\)"}}]
    )
    assert f"{nid} Back \\frac" in text and "does not know \\and (use \\land)" in text
    assert anki.notes[nid]["fields"]["Back"]["value"] == "\\(\\frac{1}{2} \\and x\\)"


async def test_notes_export_as_markdown(client: Client, tmp_path: Path) -> None:
    text = await call(client, "draft_add", cards=[BASIC, CLOZE], deck="Math", note_type="Basic", tags=["kap3"])
    await call(client, "draft_commit", draft_id=draft_id(text))
    target = tmp_path / "karten.md"
    assert "Wrote 2 notes" in await call(client, "search_notes", query="tag:kap3", save_to=str(target))
    markdown = target.read_text()
    assert "**Front:** Warum ist $Q$ invertierbar?" in markdown
    assert "**Text:** Eine Äquivalenzrelation ist **reflexiv** und **symmetrisch**" in markdown
    assert "tags kap3" in markdown and "mcp::" not in markdown
    assert "Wrote 2 notes" in await call(client, "search_notes", query="tag:kap3", save_to=str(target))
    (tmp_path / "eigen.md").write_text("meine Notizen")
    text = await fails(client, "search_notes", query="tag:kap3", save_to=str(tmp_path / "eigen.md"))
    assert "was not written by this tool" in text


async def test_math_css_is_added_once_and_undone(client: Client, anki: FakeAnki) -> None:
    text = await call(client, "math_css", note_types=["Basic", "Cloze"])
    assert "Long formulas now scroll in Basic, Cloze" in text
    assert 'mjx-container[display="true"]' in anki.css["Basic"]
    assert "Already set up: Basic" in await call(client, "math_css", note_types=["Basic"])
    await call(client, "undo", batch_id=batch_id(text))
    assert anki.css["Basic"] == ".card { font-size: 20px; }"
    assert "does not exist" in await fails(client, "math_css", note_types=["Nope"])


async def test_stats_looks_at_the_clearest_cards_first(client: Client, anki: FakeAnki) -> None:
    anki.weak_cards = list(range(1, 401))
    anki.clearest_cards = [5]
    text = await call(client, "stats", scope="deck:Math", weak_limit=3)
    assert "400 candidates, ranked the 300 with the clearest signal" in text


async def test_deleted_notes_come_back_with_undo(client: Client, anki: FakeAnki) -> None:
    text = await call(client, "draft_add", cards=[BASIC], deck="Math::Analysis", note_type="Basic", tags=["la"])
    await call(client, "draft_commit", draft_id=draft_id(text))
    (nid,) = anki.notes
    text = await call(client, "delete_notes", note_ids=[nid])
    assert not anki.notes and "without the review history" in text
    del anki.decks["Math::Analysis"]

    assert "added 1 deleted note back" in await call(client, "undo", batch_id=batch_id(text))
    (note,) = anki.notes.values()
    assert note["deck"] == "Math::Analysis"
    assert note["fields"]["Front"]["value"] == BASIC["fields"]["Front"]
    assert "la" in note["tags"] and "mcp::created" in note["tags"]
    assert "already undone" in await fails(client, "undo", batch_id=batch_id(text))


async def test_the_old_pictures_folder_is_taken_over(anki: FakeAnki, tmp_path: Path) -> None:
    old = tmp_path / "Pictures" / "Anki for Claude"
    old.mkdir(parents=True)
    (old / "herz.png").write_bytes(b"png")
    async with Client(mcp) as client:
        await client.list_tools()
    assert (tmp_path / IMAGES / "herz.png").read_bytes() == b"png"
    assert not old.exists()


# 2026-07-28 answers with input_required and the client calls again; before it, the server asks the client directly.
BOTH_PROTOCOLS = pytest.mark.parametrize("mode", ["auto", "legacy"])


class Dialog:
    """A client's confirmation dialog: answers with the queued actions and records the messages."""

    def __init__(self, *answers: tuple[str, bool]) -> None:
        self.answers = list(answers)
        self.messages: list[str] = []

    async def __call__(self, context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
        self.messages.append(params.message)
        action, dont_ask_again = self.answers.pop(0)
        content = {"dont_ask_again": dont_ask_again} if action == "accept" else None
        return types.ElicitResult(action=action, content=content)


@BOTH_PROTOCOLS
async def test_commit_asks_in_a_dialog_unless_told_not_to(anki: FakeAnki, mode: str) -> None:
    dialog = Dialog(("decline", False), ("accept", False))
    async with Client(mcp, elicitation_callback=dialog, mode=mode) as client:
        draft = draft_id(await call(client, "draft_add", cards=[BASIC, CLOZE], deck="Math", note_type="Basic"))
        assert "did not confirm" in await fails(client, "draft_commit", draft_id=draft)
        assert not anki.notes and "2 cards" in await call(client, "draft_show", draft_id=draft)
        await call(client, "draft_commit", draft_id=draft, cards=[1])
        await call(client, "draft_commit", draft_id=draft, confirm=False)
    assert len(anki.notes) == 2 and not dialog.answers
    assert dialog.messages[1].startswith(f"Add 1 card from draft {draft} to Anki (deck Math)?")


@BOTH_PROTOCOLS
async def test_delete_asks_until_the_user_says_not_again(anki: FakeAnki, mode: str) -> None:
    dialog = Dialog(("cancel", False), ("accept", True))
    async with Client(mcp, elicitation_callback=dialog, mode=mode) as client:
        cards = [{"fields": {"Front": f"<b>Frage</b> {i}", "Back": "a"}} for i in range(7)]
        text = await call(client, "draft_add", cards=cards, deck="Math", note_type="Basic")
        await call(client, "draft_commit", draft_id=draft_id(text), confirm=False)
        first, *rest = sorted(anki.notes)
        assert "nothing was changed" in await fails(client, "delete_notes", note_ids=sorted(anki.notes))
        assert len(anki.notes) == 7
        await call(client, "delete_notes", note_ids=rest)
        await call(client, "delete_notes", note_ids=[first])  # no dialog any more
    assert not anki.notes and not dialog.answers
    assert "- Frage 0\n" in dialog.messages[0] and "and 2 more" in dialog.messages[0]


@BOTH_PROTOCOLS
async def test_force_undo_asks_only_for_studied_cards(anki: FakeAnki, mode: str) -> None:
    dialog = Dialog(("decline", False), ("accept", False))
    async with Client(mcp, elicitation_callback=dialog, mode=mode) as client:
        text = await call(client, "draft_add", cards=[BASIC, CLOZE], deck="Math", note_type="Basic")
        batch = batch_id(await call(client, "draft_commit", draft_id=draft_id(text), confirm=False))
        studied, _ = sorted(anki.notes)
        anki.notes[studied]["studied"] = True
        assert "deleted 1 note" in await call(client, "undo", batch_id=batch)
        assert list(anki.notes) == [studied] and dialog.messages == []  # nothing studied was deleted, no dialog

        await fails(client, "undo", batch_id=batch, force=True)
        assert studied in anki.notes
        assert "deleted 1 note" in await call(client, "undo", batch_id=batch, force=True)
    assert not anki.notes and dialog.messages[0].startswith("Delete 1 card you studied")
