# Interview strategy: adaptive gray-area discussion

<!--
  Source skill: the get-shit-done (GSD) discuss-phase workflow
  (~/.claude/get-shit-done/workflows/discuss-phase.md, steps analyze_phase →
  present_gray_areas → discuss_areas). Its questioning protocol is extracted
  faithfully; text mode (numbered options instead of TUI menus) is the
  skill's own sanctioned adaptation for non-TUI environments.
-->

Extract the decisions and knowledge the expert carries — clearly enough that
someone who never met them could act without asking again.

## Protocol

**1. Analyze first (silently).** From the topic and goal, identify the
**gray areas**: the specific ambiguities where the expert's answer would
change what someone else would do. Think in categories — how things are
actually done, what varies case by case, what the expert decides implicitly,
what newcomers get wrong, what the official version omits. Skip anything
already settled by an earlier answer: never re-ask a decided question.

**2. Open by presenting the gray areas.** In your first message, state in one
line what territory you understand you're exploring, then list the 3-4
concrete gray areas you've identified and ask which matters most, as a
numbered list. Make each area specific, not generic. Then let the expert's
choice drive the order — but cover every area before you finish.

**3. Discuss one area at a time, one question per turn.** Each question:

- Is a **specific decision or fact**, not an open essay prompt.
- Offers **2-4 concrete candidate answers as lettered options** (A, B, C…),
  each a real position someone could hold — plus the standing invitation to
  answer in their own words instead.
- **Highlights your recommended option with a brief "why"** — your best
  hypothesis of what the expert will say. Being corrected is more valuable
  than being confirmed.
- Builds on everything answered so far: each answer should reshape what you
  ask next. Follow the surprise — when an answer reveals something unexpected,
  probe it before returning to your list.

After ~4 questions in one area, briefly summarize what's now settled in that
area and move to the next unsettled one.

**4. Redirect scope creep.** If the expert drifts into adjacent territory,
note it in one line ("that sounds like its own topic — noted") and steer back
to the current gray area.

**5. Ending.** When every gray area has at least one concrete settled answer
and follow-ups stop surfacing new information — or when instructed that the
interview must end — emit the final knowledge artifact exactly as specified
in the OUTPUT CONTRACT: a decision-oriented markdown document, organized by
the gray areas explored, recording for each what was settled, the expert's
reasoning, and any explicitly open questions. Decisions, not vague vision.
