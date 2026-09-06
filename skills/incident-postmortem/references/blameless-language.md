# Blameless Language

Loaded on demand — only when `render_postmortem.py` reports a
blaming-phrase warning and the sentence needs rewriting, or when the
user asks why a phrase was flagged. Each row is what the script
matches, why it matters, and a rewrite that keeps the fact and drops
the fault.

| Flagged phrase | Why it is flagged | Rewrite pattern |
|---|---|---|
| "X failed to / neglected to / forgot to …" | Locates the failure in a person; the system that let one omission cause an outage disappears from the record. | "… was not done; nothing in the deploy flow required it or surfaced its absence." |
| "should have …" | Hindsight. It states what is obvious now, not what was knowable then, and teaches responders to hide uncertainty. | "At that point the dashboard showed …, which made … the reasonable next step." |
| "careless / negligent / sloppy / lazy" | Character judgment; produces no action item and guarantees the next responder says less. | Delete. Describe the condition, not the person. |
| "human error" | Ends inquiry exactly where it should start: what made the error easy to make and hard to notice? | "The confirmation prompt showed the same text for staging and production." |
| "his / her / their fault / mistake" | Attribution; the record becomes evidence against a colleague. | "The contributing condition was …; the safeguard that would have caught it is …" |

Names may appear in the timeline as actors ("at 10:42 the on-call
engineer ran the rollback"); they must not appear as causes.
