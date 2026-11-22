"""Field content as text: for search results, the chat preview, formatting checks, repairs and Markdown."""

import html
import re

from anki_mcp.mathjax_names import ENVIRONMENTS, MACROS

_IMAGE = re.compile(r'<img\b[^>]*?\bsrc="([^"]*)"[^>]*>', re.IGNORECASE)
_ANY_IMAGE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_BREAK = re.compile(r"<br\s*/?>|</(?:div|p|li|ul|ol|pre)>", re.IGNORECASE)
_ITEM = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_CLOZE = re.compile(r"\{\{c(\d+)::")
_MATH = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.DOTALL)
_CODE = re.compile(r"<(pre|code)\b.*?</\1>", re.DOTALL | re.IGNORECASE)


def strip_html(value: str) -> str:
    """One line of plain text."""
    text = _ANY_IMAGE.sub(" [image] ", value)
    text = _TAG.sub("", _BREAK.sub(" ", text))
    return " ".join(html.unescape(text).split())


def readable(value: str) -> str:
    """Field content for the chat: line breaks kept, images as [image: name], other markup removed."""
    text = _IMAGE.sub(lambda m: f"\n[image: {m[1]}]\n", value)
    text = _ITEM.sub("\n- ", text)
    text = _TAG.sub("", _BREAK.sub("\n", text))
    lines = (_SPACE.sub(" ", line).strip() for line in html.unescape(text).splitlines())
    return "\n".join(line for line in lines if line)


def prose(value: str) -> str:
    """Plain text with every formula reduced to one word, for counting words and commas."""
    return strip_html(_MATH.sub(" [formula] ", value))


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def cloze_ords(fields: dict[str, str]) -> list[int]:
    return sorted({int(n) for value in fields.values() for n in _CLOZE.findall(value)})


# --- repairs -------------------------------------------------------------------------

# A LaTeX command written with one backslash in a JSON string loses it if it starts with b, f, n, r or t:
# "\text" arrives as a tab and "ext", "\frac" as a form feed and "rac". Other letters make the JSON invalid.
_LOST = {"\x08": "b", "\x0c": "f", "\n": "n", "\r": "r", "\t": "t"}
_CONTROL = re.compile(r"[\x08\x0c\n\r\t]([a-zA-Z]*)")
_RAW_LT = re.compile(r"<(?!br\s*/?>)", re.IGNORECASE)
_LONE_LT = re.compile(r"<(?![a-zA-Z/!])")  # cannot start a tag, so it is meant as a character


def repair(value: str) -> tuple[str, list[str]]:
    """Give formulas back the backslashes JSON took, and escape a '<' that HTML would misread.

    Returns the field and what was repaired.
    """
    repaired: list[str] = []

    def restore(m: re.Match[str]) -> str:
        name = _LOST[m[0][0]] + m[1]
        # A real line break can start a line of a long formula: there only names of three letters or more count.
        if name in MACROS and (m[0][0] != "\n" or len(name) >= 3):
            repaired.append("\\" + name)
            return "\\" + name
        return m[0]

    def escape(pattern: re.Pattern[str], text: str) -> str:
        if pattern.search(text):
            repaired.append("< as &lt;")
            text = pattern.sub("&lt;", text)
        return text

    parts, pos = [], 0
    for m in _MATH.finditer(value):
        parts += [escape(_LONE_LT, value[pos : m.start()]), escape(_RAW_LT, _CONTROL.sub(restore, m[0]))]
        pos = m.end()
    parts.append(escape(_LONE_LT, value[pos:]))
    return "".join(parts), list(dict.fromkeys(repaired))


# --- formatting checks ---------------------------------------------------------------

_LOOSE_LATEX = re.compile(r"\\[a-zA-Z]+|[_^]\{")
_DOLLAR_MATH = re.compile(r"\$\$?[^$\s\d][^$]*\$|\[/?\$\$?\]|\[/?latex\]")
_TOKEN = re.compile(r"\\(?:([a-zA-Z]+)|.)", re.DOTALL)
_DEFINED = re.compile(r"\\(?:(?:re)?newcommand\s*\{?|def\s*|DeclareMathOperator\*?\s*\{)\s*\\([a-zA-Z]+)")
_ENVIRONMENT = re.compile(r"\\(begin|end)\s*\{([^}]*)\}")
_LEFT_RIGHT = re.compile(r"\\(left|right)(?![a-zA-Z])")
_ONE_BACKSLASH = re.compile(r"(?<!\\)\\(?=\s)")
_CONTROL_LEFT = re.compile(r"[\x08\x0c\r\t]")
_HTML_TAG = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>")
_ALLOWED_TAGS = ("br", "b", "i", "ul", "li", "pre", "code", "img")
_DASH = re.compile(r"—| – ")
_SINGLE_ROW = {"equation", "equation*"}

# What KaTeX, LaTeX packages or habit offer and MathJax in Anki does not know, with what it does know.
_INSTEAD = {
    "and": r"\land",
    "or": r"\lor",
    "rarr": r"\rightarrow",
    "larr": r"\leftarrow",
    "lrarr": r"\leftrightarrow",
    "harr": r"\leftrightarrow",
    "Rarr": r"\Rightarrow",
    "rArr": r"\Rightarrow",
    "Larr": r"\Leftarrow",
    "lArr": r"\Leftarrow",
    "Lrarr": r"\Leftrightarrow",
    "lrArr": r"\Leftrightarrow",
    "hArr": r"\Leftrightarrow",
    "Harr": r"\Leftrightarrow",
    "uarr": r"\uparrow",
    "darr": r"\downarrow",
    "R": r"\mathbb{R}",
    "N": r"\mathbb{N}",
    "Z": r"\mathbb{Z}",
    "Q": r"\mathbb{Q}",
    "C": r"\mathbb{C}",
    "E": r"\mathbb{E}",
    "Reals": r"\mathbb{R}",
    "reals": r"\mathbb{R}",
    "natnums": r"\mathbb{N}",
    "Complex": r"\mathbb{C}",
    "cnums": r"\mathbb{C}",
    "abs": r"\lvert x \rvert",
    "norm": r"\lVert x \rVert",
    "eps": r"\varepsilon",
    "bm": r"\boldsymbol",
    "exist": r"\exists",
    "empty": r"\emptyset",
    "isin": r"\in",
    "infin": r"\infty",
    "plusmn": r"\pm",
    "sub": r"\subset",
    "sube": r"\subseteq",
    "supe": r"\supseteq",
    "lang": r"\langle",
    "rang": r"\rangle",
    "bull": r"\bullet",
    "tg": r"\tan",
    "ctg": r"\cot",
    "arctg": r"\arctan",
    "cosec": r"\csc",
    "defeq": r"\coloneqq",
    "textsc": r"\text",
    "mathds": r"\mathbb",
    "mathbbm": r"\mathbb",
    "argmin": r"\operatorname*{argmin}",
    "argmax": r"\operatorname*{argmax}",
} | {op: rf"\operatorname{{{op}}}" for op in ("sgn", "Tr", "tr", "rank", "diag", "Var", "Cov", "ggT", "kgV")}


def _braces_balanced(math: str) -> bool:
    depth = 0
    for m in re.finditer(r"\\.|[{}]", math, re.DOTALL):
        if m[0] == "{":
            depth += 1
        elif m[0] == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _environment_problems(math: str) -> list[str]:
    problems, stack = [], []
    for kind, raw in _ENVIRONMENT.findall(math):
        env = raw.strip()
        if kind == "begin":
            if env not in ENVIRONMENTS:
                problems.append(f"MathJax has no environment '{env}'")
            stack.append(env)
        elif not stack or stack.pop() != env:
            problems.append(f"\\end{{{env}}} does not match its \\begin")
    problems.extend(f"\\begin{{{env}}} is never closed" for env in stack)
    return problems


def _math_problems(math: str, defined: set[str]) -> list[str]:
    """What breaks one formula, inside its delimiters."""
    problems = []
    if not _braces_balanced(math):
        problems.append("unbalanced { } in a formula")
    problems += _environment_problems(math)
    sides = _LEFT_RIGHT.findall(math)
    if sides.count("left") != sides.count("right"):
        problems.append("\\left and \\right do not pair up")
    rows = [env.strip() for kind, env in _ENVIRONMENT.findall(math) if kind == "begin"]
    if any(env not in _SINGLE_ROW for env in rows) and _ONE_BACKSLASH.search(math):
        problems.append("a single '\\' before a space: a new row is '\\\\' (four backslashes in JSON)")
    if _CONTROL_LEFT.search(math):
        problems.append("a control character in a formula: a LaTeX command lost its backslash in JSON")
    unknown = sorted({name for name in _TOKEN.findall(math) if name and name not in MACROS and name not in defined})
    if unknown:
        named = ", ".join(f"\\{n} (use {_INSTEAD[n]})" if n in _INSTEAD else f"\\{n}" for n in unknown)
        problems.append(f"MathJax in Anki does not know {named}")
    return problems


def lint(fields: dict[str, str]) -> list[str]:
    """Formatting slips that Anki accepts but renders wrong."""
    problems = []
    for name, value in fields.items():
        if value.count("\\(") != value.count("\\)") or value.count("\\[") != value.count("\\]"):
            problems.append(f"{name}: unbalanced \\( \\) or \\[ \\]")
            continue
        outside = _TAG.sub(" ", _MATH.sub(" ", _CODE.sub(" ", value)))
        if m := _DOLLAR_MATH.search(outside):
            problems.append(f"{name}: '{m[0][:30]}' does not render in Anki, use \\( \\) or \\[ \\]")
        elif loose := next((word for word in outside.split() if _LOOSE_LATEX.search(word)), None):
            problems.append(f"{name}: LaTeX outside \\( \\): '{loose}'")
        if _CONTROL_LEFT.search(_MATH.sub(" ", _CODE.sub(" ", value))):
            problems.append(f"{name}: a control character (tab, form feed): text that lost a backslash in JSON?")

        defined = set(_DEFINED.findall(value))
        seen: list[str] = []
        for math in _MATH.findall(value):
            seen += [p for p in _math_problems(math[2:-2], defined) if p not in seen]
        problems += [f"{name}: {p}" for p in seen]

        if "{{c" in value and "}}}" in value:
            problems.append(f"{name}: '}}}}}}' ends the cloze too early, put a space before the closing braces")
        tags = sorted({t.lower() for t in _HTML_TAG.findall(_MATH.sub(" ", value))} - set(_ALLOWED_TAGS))
        if tags:
            problems.append(f"{name}: <{'>, <'.join(tags)}> (keep to {' '.join(_ALLOWED_TAGS)})")
        if _DASH.search(_MATH.sub(" ", _CODE.sub(" ", value))):
            problems.append(f"{name}: a dash used as a pause, use a comma, a colon or two sentences")
    return problems


# --- plain text in, Markdown out -----------------------------------------------------

_BLOCK_TAG = r"</?(?:ul|ol|li|div|p|pre|table|thead|tbody|tr|td|th|hr|br)\b[^>]*>"
_PROTECTED = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]|<pre\b.*?</pre>", re.DOTALL | re.IGNORECASE)


def line_breaks_to_html(value: str) -> str:
    """Line breaks typed in plain text become <br>. Formulas, code and the space around list tags keep theirs."""
    value = re.sub(rf"[ \t]*\n\s*(?={_BLOCK_TAG})", "", value, flags=re.IGNORECASE)
    value = re.sub(rf"({_BLOCK_TAG})[ \t]*\n\s*", r"\1", value, flags=re.IGNORECASE)
    parts, pos = [], 0
    for m in _PROTECTED.finditer(value):
        parts += [value[pos : m.start()].replace("\n", "<br>"), m[0]]
        pos = m.end()
    parts.append(value[pos:].replace("\n", "<br>"))
    return "".join(parts)


_CLOZE_DELETION = re.compile(r"\{\{c\d+::(.*?)(?:::(?:(?!\}\}).)*)?\}\}", re.DOTALL)


def comparable(value: str) -> str:
    """Lower-case plain text without cloze markup, for finding near-duplicates."""
    return strip_html(_CLOZE_DELETION.sub(r"\1", value)).lower()


_PRE = re.compile(r"<pre\b[^>]*>(?:\s*<code\b[^>]*>)?(.*?)(?:</code>\s*)?</pre>", re.DOTALL | re.IGNORECASE)


def to_markdown(value: str) -> str:
    """Field content as Markdown: formulas between $ or $$, cloze answers in bold, code fenced."""
    blocks: list[str] = []

    def keep(text: str) -> str:
        blocks.append(text)
        return f"\x00{len(blocks) - 1}\x00"

    def formula(m: re.Match[str]) -> str:
        math = html.unescape(_BREAK.sub("\n", m[0][2:-2])).strip()
        math = _CLOZE_DELETION.sub(r"\1", math)
        return keep(f"\n\n$$\n{math}\n$$\n\n" if m[0].startswith("\\[") else f"${math}$")

    text = _PRE.sub(lambda m: keep(f"\n\n```\n{html.unescape(_TAG.sub('', m[1])).strip()}\n```\n\n"), value)
    text = _MATH.sub(formula, text)
    text = _CLOZE_DELETION.sub(r"**\1**", text)
    text = _IMAGE.sub(lambda m: f"![]({m[1]})", text)
    text = re.sub(r"</?b\b[^>]*>", "**", text, flags=re.IGNORECASE)
    text = re.sub(r"</?i\b[^>]*>", "*", text, flags=re.IGNORECASE)
    text = _ITEM.sub("\n- ", text)
    text = re.sub(r"<br\s*/?>", "  \n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:ul|ol|div|p)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = html.unescape(_TAG.sub("", text)).replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\x00(\d+)\x00", lambda m: blocks[int(m[1])], text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
