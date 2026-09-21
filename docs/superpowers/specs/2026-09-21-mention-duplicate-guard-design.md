# Mention duplicate guard

Date: 2026-09-21

## Problem

Reddit sometimes keeps returning a username-mention inbox item as unread for
hours even though the bot calls `mark_read` on it every loop with no error.
The bot has no idempotency on the mention path, so each 30-second loop created
a new reminder and sent a new confirmation PM for the same comment.

Five users were hit between 2026-09-09 and 2026-09-20, with 78 to 617 copies
each (1,747 duplicate reminders and PMs total). The duplicate rows have been
deleted from prod. Mentions went live 2026-05-28; no earlier incident is
visible, but incidents whose target dates have passed would already be gone.

Nothing on the affected comments explains why Reddit stuck: different
subreddits, some replies to comments and one to a post, some with a bot reply
and some without. We treat the stuck-unread behavior as external and make the
bot tolerate it.

## Scope

- Only the inbox mention path in `messages.process_messages` (the branch that
  builds a `MinimalComment` and calls `comments.process_comment`).
- Mentions that contain a bang command are already skipped here and handled by
  the ingest path; they are out of scope.
- Regular messages could in theory be redelivered the same way. There is no
  evidence of that, so they are out of scope.

## Design

Two layers, checked in order, before `process_comment` is called. Memory first
because it is free; the database only on the first sighting of an id.

### Helper

`comments.duplicate_mention_reason(minimal, database)` returns `"memory"`,
`"database"`, or `None`. It also owns the memory bookkeeping described below.
`messages.py` calls it right after building the `MinimalComment`.

### Memory layer

A module-level `OrderedDict` in `comments.py` keyed by inbox comment id, value
is the number of times the id has been seen again after its first processing.
Capped at 500 entries; when full, the oldest entry is evicted. A successfully
processed mention is recorded with count 0. On a repeat sighting the count is
incremented and the reason is `"memory"`.

The stuck item is redelivered every ~30 seconds, so the cap only has to exceed
the number of distinct mentions arriving between two redeliveries. 500 is
generous. The dict is lost on restart; the database layer covers that.

### Database layer

New query `Database.get_reminder_by_user_source(user_name, source)` in
`src/database/_reminders.py`: the first pending reminder joined on `users.name`
with an exact match on `reminders.source`. `source` is built exactly as
`parse_comment` builds it: `utils.reddit_link(minimal.permalink)`. If a row
exists the reason is `"database"`.

Known gap, accepted: a short reminder that fires while the item is still stuck
has its row deleted, so a post-restart redelivery would create one more copy.
This needs a restart during an incident and a reminder shorter than the
incident, which is rare enough to ignore.

### Behavior on duplicate

`process_comment` is not called: no reminder, no comment reply, no PM. The
existing mark-read at the end of the loop still runs.

### Metric

Reuse `counters.mentions` (`bot_mentions`, label `type`). Add `duplicate` as a
third value alongside `with_command` and `mention_only`. Exactly one increment
per inbox item, so the duplicate check runs before the existing increment and
the existing increment is skipped when the check trips. The dashboard panel
already keyed on this counter shows the new series without changes.

### Logging

Duplicates found by the memory layer log a WARNING (which is forwarded to
Discord) on the first repeat and then on every 60th repeat (roughly every 30
minutes at the 30-second loop cadence). Every other repeat logs at INFO. The
line includes the inbox id, the author, the running count, and the permalink.

Duplicates found by the database layer always log a WARNING; they only occur
after a restart mid-incident and are rare.

## Files

- `src/comments.py`: memory dict, `duplicate_mention_reason`, recording of
  processed mention ids.
- `src/messages.py`: call the helper, branch on the result, metric and log.
- `src/database/_reminders.py`: `get_reminder_by_user_source`.
- `test/comment_test.py`, `test/message_test.py`: tests below.

No change to `praw_wrapper`.

## Tests

- The same mention delivered on two consecutive `process_messages` calls
  creates one reminder and sends one confirmation; the second sighting is
  counted as `duplicate` and the item is still marked read.
- With the memory dict cleared and a matching reminder row present, the mention
  is skipped with reason `database`.
- With the memory dict cleared and no matching row, the mention is processed
  normally (fresh restart, first sighting).
- Eviction: after 500 other mention ids, an id seen 501 entries ago is no
  longer in memory.
- Warning cadence: repeats 1 and 60 log WARNING, repeat 2 logs INFO.
- A mention with a bang command is unaffected (still skipped by this branch,
  never recorded in memory).

## Out of scope

- A persistent processed-inbox-items table.
- Any handling for regular messages.
- Changing how or when the inbox item is marked read.
