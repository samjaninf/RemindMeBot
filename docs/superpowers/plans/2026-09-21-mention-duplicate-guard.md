# Mention Duplicate Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the bot from creating a new reminder and PM every 30 seconds when Reddit keeps redelivering the same username-mention inbox item as unread.

**Architecture:** Two guard layers checked before a mention is processed: an in-memory bounded dict of recently processed inbox ids (catches the redelivery loop) and a database lookup for an existing reminder with the same user and source (catches the post-restart case). The mention branch of `process_messages` is extracted into `process_mention` so it can be unit tested with a mock inbox item. Duplicates are counted on the existing `bot_mentions` counter with `type="duplicate"` and logged as a WARNING on the first repeat and every 60th after that.

**Tech Stack:** Python 3.9, SQLAlchemy over SQLite, prometheus_client, pytest with the `praw_wrapper.reddit_test` mock. Spec: `docs/superpowers/specs/2026-09-21-mention-duplicate-guard-design.md`.

**How to run tests:** from the repo root, `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test -q`. Baseline before this work: 55 passed.

**Conventions:** tabs for indentation in `src/` and `test/`. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File map

- `src/database/_reminders.py` — add `get_reminder_by_user_source(user_name, source)`.
- `src/comments.py` — add the memory dict and helpers: `record_processed_mention`, `duplicate_mention_reason`, `should_warn_duplicate`, plus `reset_mention_memory` for tests.
- `src/messages.py` — extract `process_mention`, `minimal_comment_from_mention` and `log_mention_seen` from `process_messages`; wire the guard, metric, and logging into `process_mention`.
- `test/comment_test.py` — tests for the database query and the memory helpers.
- `test/message_test.py` — tests for `process_mention` end to end against the mock.

---

### Task 1: Database lookup by user and source

**Files:**
- Modify: `src/database/_reminders.py` (add a method after `user_has_cakeday_reminder`, around line 106)
- Test: `test/comment_test.py`

- [ ] **Step 1: Write the failing test**

Append to `test/comment_test.py`:

```python
def test_get_reminder_by_user_source(database):
	source = "https://www.reddit.com/r/test/comments/abc123/_/def456/"
	assert database.get_reminder_by_user_source("Watchful1", source) is None

	database.add_reminder(Reminder(
		source=source,
		message="msg",
		user=database.get_or_add_user("Watchful1"),
		requested_date=utils.parse_datetime_string("2019-01-01 04:00:00"),
		target_date=utils.parse_datetime_string("2019-01-05 04:00:00")
	))
	database.commit()

	assert database.get_reminder_by_user_source("Watchful1", source) is not None
	assert database.get_reminder_by_user_source("Watchful1", source + "x") is None
	assert database.get_reminder_by_user_source("SomeoneElse", source) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test/comment_test.py::test_get_reminder_by_user_source -q`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'get_reminder_by_user_source'`

- [ ] **Step 3: Add the query**

In `src/database/_reminders.py`, directly after the `user_has_cakeday_reminder` method (it ends with `return reminder is not None`), add:

```python
	def get_reminder_by_user_source(self, user_name, source):
		log.debug(f"Fetching reminder for u/{user_name} from source: {source}")

		return self.session.query(Reminder)\
			.join(User)\
			.filter(User.name == user_name)\
			.filter(Reminder.source == source)\
			.first()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test/comment_test.py::test_get_reminder_by_user_source -q`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/database/_reminders.py test/comment_test.py
git commit -m "Add reminder lookup by user and source

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Memory layer and duplicate helpers in comments.py

**Files:**
- Modify: `src/comments.py` (imports at top, new block after the `MinimalComment` dataclass, around line 29)
- Test: `test/comment_test.py`

- [ ] **Step 1: Write the failing tests**

Append to `test/comment_test.py`:

```python
def _minimal(comment_id, username="Watchful1"):
	thread_id = reddit_test.random_id()
	return comments.MinimalComment(
		id=comment_id,
		author=username,
		subreddit="test",
		created_utc=int(utils.datetime_now().timestamp()),
		permalink=f"/r/test/comments/{thread_id}/_/{comment_id}/",
		link_id="t3_"+thread_id,
		body=f"u/{static.ACCOUNT_NAME} 1 day",
	)


def test_duplicate_mention_unknown_id_is_not_duplicate(database):
	comments.reset_mention_memory()
	assert comments.duplicate_mention_reason(_minimal(reddit_test.random_id()), database) is None


def test_duplicate_mention_memory_counts_repeats(database):
	comments.reset_mention_memory()
	comment_id = reddit_test.random_id()
	minimal = _minimal(comment_id)
	comments.record_processed_mention(comment_id)

	assert comments.duplicate_mention_reason(minimal, database) == ("memory", 1)
	assert comments.duplicate_mention_reason(minimal, database) == ("memory", 2)
	assert comments.duplicate_mention_reason(minimal, database) == ("memory", 3)


def test_duplicate_mention_database_hit_after_memory_cleared(database):
	comments.reset_mention_memory()
	minimal = _minimal(reddit_test.random_id())
	database.add_reminder(Reminder(
		source=utils.reddit_link(minimal.permalink),
		message="msg",
		user=database.get_or_add_user(minimal.author),
		requested_date=utils.parse_datetime_string("2019-01-01 04:00:00"),
		target_date=utils.parse_datetime_string("2019-01-05 04:00:00")
	))
	database.commit()

	assert comments.duplicate_mention_reason(minimal, database) == ("database", 0)


def test_duplicate_mention_database_ignores_other_user(database):
	comments.reset_mention_memory()
	minimal = _minimal(reddit_test.random_id())
	database.add_reminder(Reminder(
		source=utils.reddit_link(minimal.permalink),
		message="msg",
		user=database.get_or_add_user("SomeoneElse"),
		requested_date=utils.parse_datetime_string("2019-01-01 04:00:00"),
		target_date=utils.parse_datetime_string("2019-01-05 04:00:00")
	))
	database.commit()

	assert comments.duplicate_mention_reason(minimal, database) is None


def test_mention_memory_evicts_oldest(database):
	comments.reset_mention_memory()
	first_id = reddit_test.random_id()
	comments.record_processed_mention(first_id)
	for _ in range(comments.MENTION_MEMORY_SIZE):
		comments.record_processed_mention(reddit_test.random_id())

	assert comments.duplicate_mention_reason(_minimal(first_id), database) is None


def test_should_warn_duplicate_cadence():
	assert comments.should_warn_duplicate("memory", 1) is True
	assert comments.should_warn_duplicate("memory", 2) is False
	assert comments.should_warn_duplicate("memory", 59) is False
	assert comments.should_warn_duplicate("memory", 60) is True
	assert comments.should_warn_duplicate("memory", 61) is False
	assert comments.should_warn_duplicate("memory", 120) is True
	assert comments.should_warn_duplicate("database", 0) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test/comment_test.py -q -k "duplicate_mention or mention_memory or should_warn"`
Expected: 6 failures, each with `AttributeError: module 'comments' has no attribute ...`

- [ ] **Step 3: Add the memory dict and helpers**

In `src/comments.py`, change the import block at the top so it reads:

```python
import discord_logging
import traceback
from collections import OrderedDict
from dataclasses import dataclass
```

Then, directly after the `MinimalComment` dataclass (after the line `body: str` and its blank lines, before `def database_set_seen`), insert:

```python
# Guard against Reddit redelivering the same username-mention inbox item as
# unread. Maps inbox comment id -> number of times it was seen again after it
# was first processed. Bounded; oldest entry is evicted first.
MENTION_MEMORY_SIZE = 500
MENTION_WARN_EVERY = 60
_processed_mentions = OrderedDict()


def reset_mention_memory():
	_processed_mentions.clear()


def record_processed_mention(comment_id):
	_processed_mentions[comment_id] = 0
	_processed_mentions.move_to_end(comment_id)
	while len(_processed_mentions) > MENTION_MEMORY_SIZE:
		_processed_mentions.popitem(last=False)


def duplicate_mention_reason(comment, database):
	"""Returns ("memory", repeat_count) if this inbox id was already processed
	by this process, ("database", 0) if the user already has a pending reminder
	from this comment, or None if the mention is new."""
	if comment.id in _processed_mentions:
		_processed_mentions[comment.id] += 1
		_processed_mentions.move_to_end(comment.id)
		return "memory", _processed_mentions[comment.id]

	source = utils.reddit_link(comment.permalink)
	if database.get_reminder_by_user_source(comment.author, source) is not None:
		return "database", 0

	return None


def should_warn_duplicate(reason, count):
	"""Database hits are rare (restart mid-incident) and always warn. Memory
	hits warn on the first repeat and then every MENTION_WARN_EVERY repeats,
	so a multi-hour incident produces a Discord line about every 30 minutes
	instead of one per loop."""
	if reason == "database":
		return True
	return count == 1 or count % MENTION_WARN_EVERY == 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test/comment_test.py -q -k "duplicate_mention or mention_memory or should_warn"`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/comments.py test/comment_test.py
git commit -m "Add in-memory and database duplicate checks for inbox mentions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Extract process_mention from process_messages (no behavior change)

**Files:**
- Modify: `src/messages.py` (the `else:` branch inside `process_messages`, currently lines 365 to 405, plus three new functions above `process_messages`)
- Test: `test/message_test.py`

- [ ] **Step 1: Write the failing tests**

Append to `test/message_test.py`:

```python
def _make_mention(reddit, username, body):
	"""Register a comment with the mock and build the matching inbox item the
	way PRAW delivers a username mention: subject, context, no permalink."""
	comment_id = reddit_test.random_id()
	thread_id = reddit_test.random_id()
	created = utils.datetime_now()
	registered = reddit_test.RedditObject(
		body=body,
		author=username,
		created=created,
		id=comment_id,
		link_id="t3_"+thread_id,
		permalink=f"/r/test/comments/{thread_id}/_/{comment_id}/",
		subreddit="test"
	)
	reddit.add_comment(registered)

	inbox_item = reddit_test.RedditObject(
		body=body,
		author=username,
		created=created,
		id=comment_id,
		prefix="t1"
	)
	inbox_item.subject = "username mention"
	inbox_item.context = f"/r/test/comments/{thread_id}/_/{comment_id}/?context=3"
	inbox_item.subreddit = "test"
	return registered, inbox_item


def test_process_mention_creates_reminder_and_replies(database, reddit, monkeypatch):
	monkeypatch.setattr(static, "MENTION_REMINDERS_ENABLED", True)
	username = "Watchful1"
	registered, inbox_item = _make_mention(reddit, username, f"u/{static.ACCOUNT_NAME} 1 day")

	assert messages.process_mention(inbox_item, reddit, database, "1/1") is True

	reminders = database.get_all_user_reminders(username)
	assert len(reminders) == 1
	assert reminders[0].source == utils.reddit_link(registered.permalink)
	assert len(registered.children) == 1
	assert "CLICK THIS LINK" in registered.get_first_child().body
	assert len(reddit.sent_messages) == 0


def test_process_mention_with_command_is_left_to_ingest(database, reddit, monkeypatch):
	monkeypatch.setattr(static, "MENTION_REMINDERS_ENABLED", True)
	username = "Watchful1"
	registered, inbox_item = _make_mention(reddit, username, f"u/{static.ACCOUNT_NAME} {static.TRIGGER}! 1 day")

	assert messages.process_mention(inbox_item, reddit, database, "1/1") is True

	assert len(database.get_all_user_reminders(username)) == 0
	assert len(registered.children) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test/message_test.py -q -k process_mention`
Expected: 2 failures with `AttributeError: module 'messages' has no attribute 'process_mention'`

- [ ] **Step 3: Extract the functions**

In `src/messages.py`, insert the following three functions directly above `def process_messages(reddit, database):`:

```python
def minimal_comment_from_mention(message):
	# PRAW's inbox payload omits permalink and link_id, but `context`
	# carries the full permalink URL — strip the query string and parse
	# the post id out of the path. Build a MinimalComment so downstream
	# code never sees the lazy PRAW object.
	permalink_path = message.context.split('?', 1)[0]
	post_id_match = re.match(r'/r/[^/]+/comments/([^/]+)/', permalink_path)
	return comments.MinimalComment(
		id=message.id,
		author=message.author.name,
		subreddit=str(message.subreddit),
		created_utc=message.created_utc,
		permalink=permalink_path,
		link_id=f"t3_{post_id_match.group(1)}",
		body=message.body,
	)


def log_mention_seen(author, message_id, permalink):
	if static.MENTION_DETECTION_WARN:
		log.warning(f"Username mention from u/{author}: {message_id} : {permalink}")
	else:
		log.info(f"Username mention from u/{author}: {message_id} : {permalink}")


def process_mention(message, reddit, database, count_string):
	"""Handle one username-mention inbox item. Returns True if the item should
	be marked read, False if a transient error means Reddit should redeliver it."""
	author = utils.author_name(message.author)
	has_command = comments.body_contains_command(message.body)
	mention_type = 'with_command' if has_command else 'mention_only'
	counters.mentions.labels(type=mention_type).inc()
	try:
		permalink = utils.reddit_link(message.permalink)
	except AttributeError:
		permalink = f"comment {message.id}"
	log_mention_seen(author, message.id, permalink)

	if not static.MENTION_REMINDERS_ENABLED or has_command:
		return True

	mark_read = True
	try:
		minimal = minimal_comment_from_mention(message)
		comments.process_comment(minimal, reddit, database, count_string)
	except Exception as err:
		mark_read = not utils.process_error(
			f"Error processing mention: {message.id} : u/{author}",
			err, traceback.format_exc()
		)
	finally:
		database.commit()
	return mark_read
```

Then replace the whole `else:` branch of the `if reddit.is_message(message):` inside `process_messages`. The current branch starts at `is_mention = message.subject == "username mention"` and ends at `log.info(f"Object not message, skipping: {message.id}")`. Replace it with:

```python
		else:
			is_mention = message.subject == "username mention"
			if is_mention and (static.MENTION_DETECTION_ENABLED or static.MENTION_REMINDERS_ENABLED):
				mark_read = process_mention(message, reddit, database, f"{i}/{len(messages)}")
			else:
				log.info(f"Object not message, skipping: {message.id}")
```

The `if mark_read:` block after it and the `return len(messages)` stay as they are.

- [ ] **Step 4: Run the whole suite to verify nothing changed**

Run: `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test -q`
Expected: `64 passed` (55 baseline + 1 from Task 1 + 6 from Task 2 + 2 from this task)

- [ ] **Step 5: Commit**

```bash
git add src/messages.py test/message_test.py
git commit -m "Extract process_mention from process_messages

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Wire the duplicate guard, metric, and logging into process_mention

**Files:**
- Modify: `src/messages.py` (`process_mention`, added in Task 3)
- Test: `test/message_test.py`

- [ ] **Step 1: Write the failing tests**

Add `import comments` and `import counters` to the imports at the top of `test/message_test.py` (after `import messages`). Then append:

```python
def _duplicate_count():
	return counters.mentions.labels(type='duplicate')._value.get()


def test_process_mention_redelivered_is_processed_once(database, reddit, monkeypatch):
	monkeypatch.setattr(static, "MENTION_REMINDERS_ENABLED", True)
	comments.reset_mention_memory()
	username = "Watchful1"
	registered, inbox_item = _make_mention(reddit, username, f"u/{static.ACCOUNT_NAME} 1 day")
	before = _duplicate_count()

	assert messages.process_mention(inbox_item, reddit, database, "1/1") is True
	assert messages.process_mention(inbox_item, reddit, database, "1/1") is True
	assert messages.process_mention(inbox_item, reddit, database, "1/1") is True

	assert len(database.get_all_user_reminders(username)) == 1
	assert len(registered.children) == 1
	assert len(reddit.sent_messages) == 0
	assert _duplicate_count() == before + 2


def test_process_mention_redelivered_after_restart_uses_database(database, reddit, monkeypatch):
	monkeypatch.setattr(static, "MENTION_REMINDERS_ENABLED", True)
	comments.reset_mention_memory()
	username = "Watchful1"
	registered, inbox_item = _make_mention(reddit, username, f"u/{static.ACCOUNT_NAME} 1 day")
	before = _duplicate_count()

	assert messages.process_mention(inbox_item, reddit, database, "1/1") is True
	comments.reset_mention_memory()  # simulate a process restart
	assert messages.process_mention(inbox_item, reddit, database, "1/1") is True

	assert len(database.get_all_user_reminders(username)) == 1
	assert len(registered.children) == 1
	assert len(reddit.sent_messages) == 0
	assert _duplicate_count() == before + 1


def test_process_mention_failure_is_not_recorded(database, reddit, monkeypatch):
	monkeypatch.setattr(static, "MENTION_REMINDERS_ENABLED", True)
	comments.reset_mention_memory()
	registered, inbox_item = _make_mention(reddit, "Watchful1", f"u/{static.ACCOUNT_NAME} 1 day")
	del inbox_item.context  # building the MinimalComment now raises

	# Non-transient error: still marked read, but nothing was processed so
	# nothing should be remembered as processed.
	assert messages.process_mention(inbox_item, reddit, database, "1/1") is True
	assert inbox_item.id not in comments._processed_mentions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test/message_test.py -q -k process_mention`
Expected: `test_process_mention_redelivered_is_processed_once` and `test_process_mention_redelivered_after_restart_uses_database` FAIL on `assert len(...) == 1` (3 and 2 reminders respectively). `test_process_mention_failure_is_not_recorded` passes already; that is fine, it pins the behavior for the next step.

- [ ] **Step 3: Replace process_mention with the guarded version**

In `src/messages.py`, replace the entire `process_mention` function from Task 3 with:

```python
def process_mention(message, reddit, database, count_string):
	"""Handle one username-mention inbox item. Returns True if the item should
	be marked read, False if a transient error means Reddit should redeliver it.

	Reddit sometimes keeps returning the same mention as unread for hours even
	though mark_read succeeds, so before doing anything we check whether this
	mention was already handled (in this process, or by a pending reminder in
	the database) and skip it if so."""
	author = utils.author_name(message.author)
	has_command = comments.body_contains_command(message.body)
	try:
		permalink = utils.reddit_link(message.permalink)
	except AttributeError:
		permalink = f"comment {message.id}"

	if not static.MENTION_REMINDERS_ENABLED or has_command:
		counters.mentions.labels(type='with_command' if has_command else 'mention_only').inc()
		log_mention_seen(author, message.id, permalink)
		return True

	mark_read = True
	try:
		minimal = minimal_comment_from_mention(message)

		duplicate = comments.duplicate_mention_reason(minimal, database)
		if duplicate is not None:
			reason, count = duplicate
			counters.mentions.labels(type='duplicate').inc()
			line = f"Duplicate mention from u/{author} skipped ({reason}, repeat {count}): {message.id} : {permalink}"
			if comments.should_warn_duplicate(reason, count):
				log.warning(line)
			else:
				log.info(line)
			return True

		counters.mentions.labels(type='mention_only').inc()
		log_mention_seen(author, message.id, permalink)
		comments.process_comment(minimal, reddit, database, count_string)
		comments.record_processed_mention(minimal.id)
	except Exception as err:
		mark_read = not utils.process_error(
			f"Error processing mention: {message.id} : u/{author}",
			err, traceback.format_exc()
		)
	finally:
		database.commit()
	return mark_read
```

Note on ordering: the `mention_only` increment and the "Username mention from" line now happen after the duplicate check, so each inbox item increments exactly one `type`. A mention whose `MinimalComment` cannot be built (missing `context`) no longer increments `bot_mentions`; it is still counted on `bot_errors` by `process_error`.

- [ ] **Step 4: Run the whole suite**

Run: `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test -q`
Expected: `67 passed`

- [ ] **Step 5: Commit**

```bash
git add src/messages.py test/message_test.py
git commit -m "Skip inbox mentions that were already processed

Reddit sometimes keeps returning a username mention as unread for hours
after mark_read succeeds. Check an in-memory set of processed inbox ids
and then the database for an existing reminder from the same user and
comment before creating anything. Count skips as bot_mentions
type=duplicate and warn on the first repeat and every 60th after.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Final verification

**Files:** none modified.

- [ ] **Step 1: Run the full suite one more time from a clean tree**

Run: `git status --short` (expect only the pre-existing untracked `scripts/` files and the modified `scripts/explain_parse.py`), then `C:\Users\greg\.virtualenvs\RemindMeBot-ZD3GgvxA\Scripts\python.exe -m pytest test -q`
Expected: `67 passed`

- [ ] **Step 2: Review the diff against the spec**

Run: `git diff 2746bc4..HEAD --stat` and confirm only these files changed: `src/database/_reminders.py`, `src/comments.py`, `src/messages.py`, `test/comment_test.py`, `test/message_test.py`, and this plan file.

- [ ] **Step 3: Deploy note for the operator**

Nothing to migrate. Pull on the VPS and restart the bot. After the next incident, the Grafana `bot_mentions` panel shows a `duplicate` series and Discord gets one warning at the first repeat and then roughly every 30 minutes.
