import json
import os
from datetime import datetime

import parse_corpus
import utils


def read_corpus_lines(folder):
	with open(os.path.join(folder, parse_corpus.CORPUS_LOG_FILE), encoding="utf-8") as file_handle:
		return [json.loads(line) for line in file_handle if line.strip()]


def test_parse_time_records_corpus_line(tmp_path, monkeypatch):
	monkeypatch.setattr(parse_corpus, "CORPUS_LOG_FOLDER", str(tmp_path))
	monkeypatch.setattr(parse_corpus, "_logger", None)

	base_time = utils.datetime_force_utc(datetime.strptime("2019-01-01 01:23:45", "%Y-%m-%d %H:%M:%S"))
	result = utils.parse_time("1 day", base_time, "America/New_York")

	entry = read_corpus_lines(str(tmp_path))[-1]
	assert entry["s"] == "1 day"
	assert entry["base"] == "2019-01-01T01:23:45Z"
	assert entry["tz"] == "America/New_York"
	assert entry["result"] == result.strftime("%Y-%m-%dT%H:%M:%SZ")
	assert entry["stage"] == "dateparser"
	assert entry["ts"] > 0


def test_parse_time_records_failed_parse(tmp_path, monkeypatch):
	monkeypatch.setattr(parse_corpus, "CORPUS_LOG_FOLDER", str(tmp_path))
	monkeypatch.setattr(parse_corpus, "_logger", None)

	base_time = utils.datetime_force_utc(datetime.strptime("2019-01-01 01:23:45", "%Y-%m-%d %H:%M:%S"))
	result = utils.parse_time("total nonsense with no date at all", base_time, None)

	assert result is None
	entry = read_corpus_lines(str(tmp_path))[-1]
	assert entry["s"] == "total nonsense with no date at all"
	assert entry["tz"] is None
	assert entry["result"] is None
	assert entry["stage"] is None


def test_record_never_throws(monkeypatch):
	monkeypatch.setattr(parse_corpus, "CORPUS_LOG_FOLDER", "\0invalid\0path")
	monkeypatch.setattr(parse_corpus, "_logger", None)

	parse_corpus.record("1 day", None, None, None, None)


def test_disabled_records_nothing(tmp_path, monkeypatch):
	monkeypatch.setattr(parse_corpus, "CORPUS_LOG_FOLDER", str(tmp_path))
	monkeypatch.setattr(parse_corpus, "_logger", None)
	monkeypatch.setattr(parse_corpus, "enabled", False)

	base_time = utils.datetime_force_utc(datetime.strptime("2019-01-01 01:23:45", "%Y-%m-%d %H:%M:%S"))
	utils.parse_time("1 day", base_time, None)

	assert not os.path.exists(os.path.join(str(tmp_path), parse_corpus.CORPUS_LOG_FILE))
