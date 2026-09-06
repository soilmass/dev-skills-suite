# Facilitation Guide

Loaded on demand from SKILL.md's Analyze stage — only when the
postmortem is being facilitated live with the responders, rather than
written up from existing notes and logs. The writeup path in SKILL.md
does not need this.

## Order of work

1. **Timeline first, causes never.** Reconstruct what happened minute
   by minute from artifacts (alerts, chat exports, deploy logs, command
   history) before anyone offers an explanation. Ask "what did you
   see?" and "what did you do next?", never "why?".
2. **Impact in the users' terms.** Who could not do what, for how long,
   and how many. Internal metrics come second.
3. **Contributing factors, plural.** There is no root cause. For every
   "X did Y", ask what made Y the reasonable thing to do with the
   information X had at that moment, and what would have made the
   safer action easier. Stop when the answer is "the system" rather
   than a person.
4. **What went well.** Detection, communication, a rollback that
   worked. Skipping this teaches responders that postmortems are only
   about failure.
5. **Action items with an owner and a date each.** An item without
   both is a wish. Prefer items that remove a contributing factor over
   items that add a step to a checklist.

## Questions that keep it blameless

- "What was the screen showing you at that point?"
- "Was there anything that made the safer option harder?"
- "If someone else had been on call, what would they have needed to
  know to do differently?"
- "Which alert would have made this obvious an hour earlier?"

## Signs the session is drifting

- A single name appears in the timeline more than the systems do.
- "Should have" enters the room.
- Action items are all "be more careful" / "add a review step".

When drifting, return to the artifacts: "Show me the log line."
