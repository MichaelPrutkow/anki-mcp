---
name: exam-prep
description: Turns a whole course (lecture PDFs, exercise sheets, past exams, transcripts) into a prioritised Anki deck in stages - a blueprint the user approves, card writing, pictures and approval in the chat. Runs only when the user starts it with /anki:exam-prep; for cards from one source or a few topics, use create-cards.
disable-model-invocation: true
---

# Exam preparation

This is the most expensive way to make cards, and it runs on the user's usage limits. Spend effort where the exam puts its points, and start agents only for courses too big to handle yourself.

Work in a run folder `anki-run/<date>/` in the current project. Every step reads and writes files there; keep only short summaries in the conversation.

If `overview` and the other anki tools are not among your tools, call `get_device_info` (search for it if it is not loaded) and search for the anki tools again. In the Claude app, a chat reaches the tools on the user's computer reliably only if the user added a folder to it before sending the first message. If the tools are still missing, ask the user to start a new chat, add a folder with the Add folder button (for example the folder with their study material) and send the request again. Only if that does not help either, follow the `check-setup` skill.

1. **Intake.** Ask once for whatever is missing: target deck, the sources, exam date, a rough card budget, language.
2. **Plan the cost.** Count the sources and their pages, then pick a mode:
   - **Small course** (up to about 5 sources or 150 pages): no agents. Do every step yourself, one source or one topic at a time.
   - **Large course:** agents, never more than these: 3 `anki:source-analyst`, 3 `anki:card-writer`, 1 `anki:visual-designer`, 1 `anki:card-auditor`.

   Tell the user in one sentence which mode you chose and how many agents it starts, and go on only once they agree. If they want it cheaper, cut the sources down to the past exams and the lectures those exams cover.
3. **Sources.** Read the past exams first: they set the priorities. Write one inventory per source, `inventory/<source-name>.md`, in the format of `${CLAUDE_PLUGIN_ROOT}/agents/source-analyst.md`. In a large course, split the sources into at most three groups of similar size and start one `anki:source-analyst` per group, never one per source.
4. **Blueprint.** Merge the inventories into `blueprint.md`, one row per topic: `topic | priority (from past exams) | card types | picture needed | est. cards | already in deck`. Mark `picture needed` for every topic the exams or lectures show as a drawing. Check existing cards with `search_notes`. Show the blueprint as a short table and **wait for the user's approval**: this is the cheapest moment to change direction.
5. **Cards.** Follow the `create-cards` rules, one draft per topic cluster, titled with its topics. In a large course, give the clusters to at most three `anki:card-writer` agents, each with the deck, the note type, its blueprint rows and the inventory files; each reports its draft ids. Picture needs go into `visual-requests.md`: `<draft id> #<card number> | what to draw | source page or figure id`.
6. **Pictures.** Make every picture in `visual-requests.md` and for every `picture needed` row, following the `visuals` skill: yourself, or in a large course with one `anki:visual-designer`.
7. **Audit.** In a large course, start one `anki:card-auditor` with the draft ids; it writes `audit.md`. Otherwise go through the `create-cards` checklist yourself. Fix the real problems with `draft_edit` and ignore false alarms.
8. **Approval.** Go through the drafts with the user one at a time: show the cards with `draft_show`, word for word, apply changes with `draft_edit`, and add the approved cards with `draft_commit`. If the user studies on a phone, finish with `sync`.
