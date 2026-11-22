from anki_mcp.drafts import DraftCard, _picture_hints
from anki_mcp.text import line_breaks_to_html, lint, repair, to_markdown
from anki_mcp.youtube import choose


def test_repair_gives_formulas_their_backslashes_back() -> None:
    # Each control character below is what JSON makes of a backslash and the letter after it.
    value, repaired = repair("\\(\text{DOM} \frac{1}{2} \beta \rho \to\\) und \\(x =\n u_1 \neq y\\)")
    assert value == "\\(\\text{DOM} \\frac{1}{2} \\beta \\rho \\to\\) und \\(x =\n u_1 \\neq y\\)"
    assert repaired == ["\\text", "\\frac", "\\beta", "\\rho", "\\to", "\\neq"]


def test_repair_leaves_real_line_breaks_and_text_alone() -> None:
    # "\nu" and "\ne" are macros, but a formula line may just as well start with u or e: too short to guess.
    assert repair("\\[a\nu_1 + b\ne\\]") == ("\\[a\nu_1 + b\ne\\]", [])
    assert repair("Tab\tim Text, a < b") == ("Tab\tim Text, a &lt; b", ["< as &lt;"])
    assert repair("\\(a<b\\) <b>fett</b> x<y") == ("\\(a&lt;b\\) <b>fett</b> x<y", ["< as &lt;"])


def test_lint_knows_what_mathjax_in_anki_knows() -> None:
    problems = lint({"Front": "\\(\\and \\rarr \\R \\argmin_x \\frca{1}{2}\\)"})
    expected = (
        "Front: MathJax in Anki does not know \\R (use \\mathbb{R}), \\and (use \\land), \\argmin "
        "(use \\operatorname*{argmin}), \\frca, \\rarr (use \\rightarrow)"
    )
    assert problems == [expected]
    assert lint({"Front": "\\(\\set{x} \\ce{H2O} \\degree \\Join \\coloneqq \\mathscr{A} \\cancel{x}\\)"}) == []
    assert lint({"Front": "\\(\\newcommand{\\R}{\\mathbb{R}} \\R^n\\)"}) == []


def test_lint_finds_broken_formulas() -> None:
    assert lint({"F": "\\(\\frac{1}{2\\)"}) == ["F: unbalanced { } in a formula"]
    assert lint({"F": "\\(\\left( x\\)"}) == ["F: \\left and \\right do not pair up"]
    assert lint({"F": "\\[\\begin{aligned} a \\end{align}\\]"})[0] == "F: \\end{align} does not match its \\begin"
    assert lint({"F": "\\(\\begin{tabular}x\\end{tabular}\\)"}) == ["F: MathJax has no environment 'tabular'"]
    rows = lint({"F": "\\[\\begin{aligned} a &= 1 \\ b &= 2 \\end{aligned}\\]"})
    assert rows == ["F: a single '\\' before a space: a new row is '\\\\' (four backslashes in JSON)"]
    assert lint({"F": "\\[\\begin{aligned} a &= 1 \\\\ b &= 2 \\end{aligned}\\]"}) == []
    assert lint({"F": "\\(\text{x}\\)"})[-1].startswith("F: a control character in a formula")


def test_lint_finds_markup_and_wording_slips() -> None:
    assert lint({"F": "Text <span>x</span><div>y</div>"}) == ["F: <div>, <span> (keep to br b i ul li pre code img)"]
    assert lint({"F": "Ein Satz — und noch einer"}) == [
        "F: a dash used as a pause, use a comma, a colon or two sentences"
    ]
    assert lint({"F": "Seiten 3–5, <b>fett</b><br><ul><li>a</li></ul><pre><code>x</code></pre>"}) == []


def test_line_breaks_become_br_outside_formulas_and_code() -> None:
    text = "Zeile 1\nZeile 2<br>\nZeile 3\n<ul>\n<li>a</li>\n</ul>\n\\[a\nb\\]\n<pre><code>x\ny</code></pre>"
    assert line_breaks_to_html(text) == (
        "Zeile 1<br>Zeile 2<br>Zeile 3<ul><li>a</li></ul>\\[a\nb\\]<pre><code>x\ny</code></pre>"
    )


def test_markdown_uses_dollar_math_and_shows_cloze_answers() -> None:
    field = (
        "Was ist \\(a &lt; b\\)?<br>{{c1::Antwort::Hinweis}} und <b>fett</b>"
        "\\[\\frac{1}{2}\\]<ul><li>x</li></ul><pre><code>a &lt; b</code></pre>"
    )
    assert to_markdown(field) == (
        "Was ist $a < b$?  \n**Antwort** und **fett**\n\n$$\n\\frac{1}{2}\n$$\n\n- x\n\n```\na < b\n```"
    )
    assert to_markdown("\\({{c1::x}} = 1\\) <img src='a.png'>") == "$x = 1$"


class Transcript:
    """What youtube_transcript_api lists per language."""

    def __init__(self, code: str, generated: bool, translatable: bool = True) -> None:
        self.language_code, self.language, self.is_generated, self.is_translatable = code, code, generated, translatable

    def translate(self, code: str) -> "Transcript":
        return Transcript(code, self.is_generated)


def test_youtube_reads_a_video_in_its_own_language() -> None:
    english, spoken, german = Transcript("en", False), Transcript("de", True), Transcript("de", False)
    assert choose([english, spoken], None) == (spoken, False)
    assert choose([english, german, spoken], None) == (german, False)
    assert choose([english, spoken], "en") == (english, False)
    assert choose([Transcript("en-US", False)], "en")[1] is False
    translated, machine = choose([spoken], "fr")
    assert machine and translated.language_code == "fr"


def test_picture_hints_skip_words_that_only_look_like_drawings() -> None:
    texts = ["Was passiert automatisch beim COMMIT?", "Was ist Kryptographie?", "Wer schrieb die Biographie?"]
    texts += ["Zeichne den B-Baum nach Einfügen von 7", "Welche Kanten hat der Graph?", "Was akzeptiert der Automat?"]
    cards = [DraftCard(n=i, deck="d", note_type="Basic", fields={"Front": t}) for i, t in enumerate(texts, 1)]
    assert _picture_hints(cards) == ["#4 (baum)", "#5 (graph)", "#6 (automat)"]
