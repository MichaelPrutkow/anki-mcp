# Formulas on cards

Anki renders formulas with MathJax 3, which never breaks a formula across lines. What does not fit the screen runs off the card, and on a phone that happens fast.

## Getting formulas through intact

- Send cards with LaTeX as `cards_text`. In `cards`, which is JSON, every backslash has to be doubled, and a single one before b, f, n, r or t silently turns `\text` into a tab and `ext`. The tools repair those and say so.
- A new row in `aligned` or `cases` is `\\`. Written in JSON with too few backslashes it arrives as `\` and the rows run together; the tools warn but cannot repair it. In `cards_text`, `\\` is simply `\\`.
- `draft_add` names every macro MathJax in Anki does not know. The usual ones: `\land` instead of `\and`, `\rightarrow` instead of `\rarr`, `\mathbb{R}` instead of `\R`, `\lvert x \rvert` instead of `\abs{x}`, `\operatorname*{argmin}` instead of `\argmin`. These work: `\ce{}`, `\set{}`, `\cancel{}`, `\coloneqq`, `\mathscr{}`, `\Join`.

## Fitting a phone

- A formula longer than a short line goes into display math `\[...\]`, broken with `\begin{aligned} ... \end{aligned}`: one condition or one step per line, aligned at `&`.
- A line that starts with an operator needs `{}` in front of it, or the operator loses its spacing: `&{}\land \exists p \in P`.
- A dot between names is punctuation to MathJax and gets a gap after it: write `s{.}\text{MatrNr}`. The same for a decimal comma: `4{,}0`.
- Words inside a formula go into `\text{...}`.
- If the user studies on a phone, offer `math_css` once (see the check-setup skill). A formula that is still too wide then scrolls sideways instead of running off the card. Breaking long formulas stays worth it, for reading.

## Checking the content

A formula, query or piece of code on a card is checked by evaluating it: compute the example, run the query on the example data from the lecture, run the code. Slides contain errors, and a card trains whatever it says.
