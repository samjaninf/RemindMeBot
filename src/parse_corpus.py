import json
import logging
import logging.handlers
import os
import time

import pytz

# Every call to utils.parse_time appends one JSON line here, capturing the
# input string, the base time, the timezone, the parsed result and which
# parser stage produced it. The file is the oracle corpus for the Devvit
# migration: the TypeScript port replays these lines against candidate JS
# date-parsing libraries and diffs the answers. Raw duplicates are kept on
# purpose - frequency is the weighting for "the most common things work".

CORPUS_LOG_FOLDER = "logs"
CORPUS_LOG_FILE = "parse_corpus.log"

enabled = True
_logger = None


def _get_logger():
	global _logger
	if _logger is None:
		os.makedirs(CORPUS_LOG_FOLDER, exist_ok=True)
		logger = logging.getLogger("parse_corpus")
		logger.setLevel(logging.INFO)
		logger.propagate = False
		handler = logging.handlers.RotatingFileHandler(
			os.path.join(CORPUS_LOG_FOLDER, CORPUS_LOG_FILE),
			maxBytes=20 * 1024 * 1024,
			backupCount=30,
			encoding="utf-8")
		logger.addHandler(handler)
		_logger = logger
	return _logger


def _isoformat_utc(date_time):
	if date_time is None:
		return None
	return date_time.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(time_string, base_time, timezone_string, result, stage):
	if not enabled:
		return
	try:
		_get_logger().info(json.dumps({
			"ts": int(time.time()),
			"s": time_string,
			"base": _isoformat_utc(base_time),
			"tz": timezone_string,
			"result": _isoformat_utc(result),
			"stage": stage,
		}, ensure_ascii=False))
	except Exception:
		pass
